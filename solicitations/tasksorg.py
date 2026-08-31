from django.utils import timezone
from datetime import datetime, timedelta, date
import pytz
from django.db.models import Q, F
from django_q.models import OrmQ, Task
from django.conf import settings
from django.core.cache import cache
from .models import EmailSettings, Solicitation, OEM, OEMUser, MailTemplate, SolicitationEmailStatus
from django.db import transaction
import json
from django_q.tasks import async_task
import sys
import subprocess
import os
import traceback
import tempfile
import logging
import redis
import time
from contextlib import contextmanager
import asyncio
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)
# ===============================
# REDIS LOCK MANAGER FOR USER-SPECIFIC PROCESSING
# ===============================

class UserProcessingLock:
    """
    FIXED: Redis-based lock manager with proper bytes/string handling
    """
    
    def __init__(self, redis_connection=None):
        if redis_connection:
            self.redis = redis_connection
        else:
            # Get Redis connection from Django cache
            try:
                self.redis = cache._cache.get_client()
                logger.info("Using Django cache Redis connection for locks")
            except Exception as e:
                logger.warning(f"Could not get Redis from Django cache: {e}")
                # Fallback to direct Redis connection
                self.redis = redis.Redis(
                    host=getattr(settings, 'REDIS_HOST', 'localhost'),
                    port=getattr(settings, 'REDIS_PORT', 6379),
                    db=getattr(settings, 'REDIS_DB', 0),
                    decode_responses=True  #THIS IS KEY - ensures strings not bytes
                )
                logger.info("Using direct Redis connection for locks")
    
    def _ensure_string(self, value):
        """Helper to ensure value is a string, not bytes"""
        if isinstance(value, bytes):
            return value.decode('utf-8')
        return value
    
    def acquire_user_lock(self, user_id, lock_type="processing", timeout=72000):
        """
        FIXED: Acquire a Redis lock for a specific user
        """
        lock_key = f"user_processing_lock:{user_id}:{lock_type}"
        lock_id = f"{user_id}_{lock_type}_{int(time.time())}"
        
        try:
            # Try to acquire lock with expiration
            acquired = self.redis.set(lock_key, lock_id, nx=True, ex=timeout)
            
            if acquired:
                logger.info(f"LOCK ACQUIRED - User {user_id}, Type: {lock_type}, Lock ID: {lock_id}")
                return lock_id
            else:
                existing_lock = self.redis.get(lock_key)
                existing_lock = self._ensure_string(existing_lock)  #FIX: Handle bytes
                logger.info(f"LOCK EXISTS - User {user_id}, Type: {lock_type}, Existing: {existing_lock}")
                return None
                
        except Exception as e:
            logger.error(f"Error acquiring lock for user {user_id}: {e}")
            return None
    
    def release_user_lock(self, user_id, lock_type="processing", lock_id=None):
        """
        FIXED: Release a Redis lock for a specific user
        """
        lock_key = f"user_processing_lock:{user_id}:{lock_type}"
        
        try:
            if lock_id:
                # Verify we own the lock before releasing
                current_lock = self.redis.get(lock_key)
                current_lock = self._ensure_string(current_lock)  #FIX: Handle bytes
                lock_id = self._ensure_string(lock_id)           #FIX: Ensure string
                
                if current_lock != lock_id:
                    logger.warning(f"LOCK MISMATCH - User {user_id}, Expected: {lock_id}, Current: {current_lock}")
                    logger.warning(f"LOCK MISMATCH - Types: Expected {type(lock_id)}, Current {type(current_lock)}")
                    # FIX: Try to release anyway if the core ID matches
                    if current_lock and lock_id and current_lock.endswith(lock_id.split('_')[-1]):
                        logger.info("Lock IDs match structurally, proceeding with release")
                    else:
                        return False
            
            # Release the lock
            deleted = self.redis.delete(lock_key)
            
            if deleted:
                logger.info(f"LOCK RELEASED - User {user_id}, Type: {lock_type}, Lock ID: {lock_id}")
                return True
            else:
                logger.warning(f"LOCK NOT FOUND - User {user_id}, Type: {lock_type}")
                return False
                
        except Exception as e:
            logger.error(f"Error releasing lock for user {user_id}: {e}")
            return False
    
    def check_user_lock_status(self, user_id, lock_type="processing"):
        """
        FIXED: Check if a user has an active lock
        """
        lock_key = f"user_processing_lock:{user_id}:{lock_type}"
        
        try:
            lock_value = self.redis.get(lock_key)
            if lock_value:
                lock_value = self._ensure_string(lock_value)  #FIX: Handle bytes
                ttl = self.redis.ttl(lock_key)
                return {
                    'lock_id': lock_value,  # Now guaranteed to be string
                    'ttl_seconds': ttl,
                    'user_id': user_id,
                    'lock_type': lock_type
                }
            return None
            
        except Exception as e:
            logger.error(f"Error checking lock status for user {user_id}: {e}")
            return None
    
    def extend_user_lock(self, user_id, lock_type="processing", additional_seconds=1800):
        """
        Extend an existing lock TTL
        """
        lock_key = f"user_processing_lock:{user_id}:{lock_type}"
        
        try:
            current_ttl = self.redis.ttl(lock_key)
            if current_ttl > 0:
                new_ttl = current_ttl + additional_seconds
                self.redis.expire(lock_key, new_ttl)
                logger.info(f"LOCK EXTENDED - User {user_id}, New TTL: {new_ttl} seconds")
                return True
            else:
                logger.warning(f"LOCK NOT EXTENDABLE - User {user_id}, TTL: {current_ttl}")
                return False
                
        except Exception as e:
            logger.error(f"Error extending lock for user {user_id}: {e}")
            return False
    
    def cleanup_expired_locks(self):
        """
        Cleanup any expired locks
        """
        try:
            pattern = "user_processing_lock:*"
            lock_keys = self.redis.keys(pattern)
            
            active_locks = 0
            for key in lock_keys:
                # Ensure key is string
                key = self._ensure_string(key)
                ttl = self.redis.ttl(key)
                if ttl > 0:
                    active_locks += 1
                    
            logger.info(f"LOCK CLEANUP - Found {active_locks} active locks out of {len(lock_keys)} total")
            return active_locks
            
        except Exception as e:
            logger.error(f"Error during lock cleanup: {e}")
            return 0

# Global lock manager instance
lock_manager = UserProcessingLock()

def _create_schedules():
    """The actual logic for creating schedules"""
    from django_q.models import Schedule
    
    # Delete existing schedules
    Schedule.objects.filter(name='check_scheduled_emails').delete()
    Schedule.objects.filter(name='create_solicitation_email_statuses').delete()
    Schedule.objects.filter(name='cleanup_stale_user_locks').delete()
    
    # Create schedules with all required fields for django-q2
    check_schedule = Schedule.objects.create(
        name='check_scheduled_emails',
        func='solicitations.tasks.check_scheduled_emails',
        hook=None,
        args=None,
        kwargs=None,
        schedule_type=Schedule.MINUTES,
        minutes=2,
        repeats=-1,
        cron=None,
        task=None,
        cluster=None,
        intended_date_kwarg=None
    )
    
    status_schedule = Schedule.objects.create(
        name='create_solicitation_email_statuses',
        func='solicitations.tasks.create_solicitation_email_statuses',
        hook=None,
        args=None,
        kwargs=None,
        schedule_type=Schedule.MINUTES,
        minutes=60,
        repeats=-1,
        cron=None,
        task=None,
        cluster=None,
        intended_date_kwarg=None
    )
    
    cleanup_schedule = Schedule.objects.create(
        name='cleanup_stale_user_locks',
        func='solicitations.tasks.cleanup_stale_user_locks',
        hook=None,
        args=None,
        kwargs=None,
        schedule_type=Schedule.MINUTES,
        minutes=360,
        repeats=-1,
        cron=None,
        task=None,
        cluster=None,
        intended_date_kwarg=None
    )
    
    logger.info("Django-Q2 scheduled tasks created successfully")

def setup_email_schedule_threaded():
    """Thread-safe version that can be called from async contexts"""
    import threading
    
    def _setup_in_thread():
        try:
            with transaction.atomic():
                _create_schedules()
                logger.info("Django-Q2 scheduled tasks created successfully in thread")
        except Exception as e:
            logger.error(f"Error setting up schedule in thread: {str(e)}")
            logger.error(traceback.format_exc())
    
    # Run in a separate thread
    thread = threading.Thread(target=_setup_in_thread)
    thread.start()
    thread.join()  # Wait for completion


def setup_email_schedule_sync_only():
    """Synchronous version for app startup"""
    try:
        _create_schedules()
        return True
    except Exception as e:
        logger.error(f"Error setting up schedule: {str(e)}")
        logger.error(traceback.format_exc())
        return False

@contextmanager
def guaranteed_user_lock(user_id, lock_type, timeout=72000):
    """
    Context manager that GUARANTEES lock release
    Use like: with guaranteed_user_lock(user_id, "manual") as lock_info:
    """
    lock_id = None
    lock_key = f"user_processing_lock:{user_id}:{lock_type}"
    start_time = time.time()
    
    try:
        # Check for conflicts first
        conflicting_locks = []
        for check_type in ['automated', 'manual', 'large_batch']:
            existing_lock = lock_manager.check_user_lock_status(user_id, check_type)
            if existing_lock:
                conflicting_locks.append(f"{check_type} (TTL: {existing_lock['ttl_seconds']}s)")
        
        if conflicting_locks:
            raise Exception(f"User {user_id} has conflicting locks: {', '.join(conflicting_locks)}")
        
        # Acquire lock
        lock_id = lock_manager.acquire_user_lock(user_id, lock_type, timeout)
        
        if not lock_id:
            raise Exception(f"Failed to acquire {lock_type} lock for user {user_id}")
        
        logger.info(f"LOCK ACQUIRED: User {user_id}, Type {lock_type}, Lock ID: {lock_id}")
        
        # Yield lock info to the calling code
        yield {
            'user_id': user_id,
            'lock_type': lock_type, 
            'lock_id': lock_id,
            'acquired_at': start_time
        }
        
    except Exception as e:
        logger.error(f"Lock acquisition failed for user {user_id}: {e}")
        raise  # Re-raise the exception
        
    finally:
        # GUARANTEED RELEASE - This ALWAYS runs, no matter what
        release_attempted = False
        release_successful = False
        
        if lock_id:
            # Method 1: Try normal release with lock_id
            try:
                release_attempted = True
                released = lock_manager.release_user_lock(user_id, lock_type, lock_id)
                if released:
                    release_successful = True
                    elapsed = time.time() - start_time
                    logger.info(f"LOCK RELEASED: User {user_id}, Type {lock_type}, Duration: {elapsed:.2f}s")
                else:
                    logger.warning(f"Normal release failed for user {user_id}, trying force release")
            except Exception as e:
                logger.error(f"Normal release error for user {user_id}: {e}")
        
        if release_attempted and not release_successful:
            # Method 2: Force release without lock_id verification
            try:
                released = lock_manager.release_user_lock(user_id, lock_type)
                if released:
                    release_successful = True
                    logger.warning(f"FORCE RELEASED: User {user_id}, Type {lock_type}")
                else:
                    logger.error(f"Force release also failed for user {user_id}")
            except Exception as e:
                logger.error(f"Force release error for user {user_id}: {e}")
        
        if release_attempted and not release_successful:
            # Method 3: Direct Redis deletion (last resort)
            try:
                deleted = lock_manager.redis.delete(lock_key)
                if deleted:
                    release_successful = True
                    logger.warning(f"DIRECT REDIS DELETE: User {user_id}, Type {lock_type}")
                else:
                    logger.error(f"Direct Redis delete failed for user {user_id}")
            except Exception as e:
                logger.error(f"Direct Redis delete error for user {user_id}: {e}")
        
        if not release_successful and release_attempted:
            logger.critical(f"FAILED TO RELEASE LOCK: User {user_id}, Type {lock_type}, Key: {lock_key}")
            logger.critical("Manual intervention required to clean this lock!")

def get_filtered_solicitations_for_autosend(user, send_scope='all'):
    """
    EXACT MATCH to manual view filtering - no additional validation
    This replicates your solicitations view logic exactly
    """
    try:
        from django.db.models import Q, OuterRef, Exists
        from django.utils import timezone
        from datetime import timedelta
        
        today = timezone.now().date()
        cutoff_date = today - timedelta(days=14)
        
        logger.info(f"Autosend filtering for user {user.username}, scope: {send_scope}")
        
        # EXACT REPLICATION of your manual view filtering
        sent_emails_subquery = SolicitationEmailStatus.objects.filter(
            user=user,
            email_sent=True,
            solicitation=OuterRef('pk')
        )
        
        disabled_oems_subquery = OEMUser.objects.filter(
            user=user,
            is_disabled=True,  # Only exclude explicitly disabled OEMs
            oem__cage=OuterRef('cage')
        )
        
        # EXACT same exclusions as your manual view
        solicitations_qs = Solicitation.objects.exclude(
            Q(cage__in=['-', 'N/A', '']) |
            Q(organization_name__in=['N/A', '']) |
            Q(email__in=['n/a', '']) |
            Q(return_by_date__isnull=True) |
            Q(return_by_date='') |
            Q(email__contains='#') |
            Exists(sent_emails_subquery) |
            Exists(disabled_oems_subquery)  # EXACT same OEM filtering
        ).filter(
            scraped_date__gte=cutoff_date
        )
        
        # EXACT same regex filter as your manual view
        solicitations_qs = solicitations_qs.extra(
            where=["return_by_date REGEXP '^[0-9]{1,2}-[0-9]{1,2}-[0-9]{4}$'"]
        )
        
        # Apply send scope filtering
        if send_scope == 'today':
            solicitations_qs = solicitations_qs.filter(scraped_date=today)
        
        # Convert to list - NO ADDITIONAL VALIDATION
        # Your manual view trusts the database filtering, so we do too
        valid_solicitations = list(solicitations_qs)
        
        logger.info(f"Autosend filtering results for user {user.username}:")
        logger.info(f"  Found: {len(valid_solicitations)} solicitations")
        logger.info(f"  Send scope: {send_scope}")
        logger.info(f"  Cutoff date: {cutoff_date}")
        
        return valid_solicitations
        
    except Exception as e:
        logger.error(f"Error in filtering for user {user.username}: {e}")
        logger.error(traceback.format_exc())
        return []

# ===============================
# ENHANCED PROCESSING FUNCTIONS WITH USER LOCKS
# ===============================

def process_user_solicitations(user_id, send_scope='all'):
    """
    Process user solicitations with EXACT manual view filtering
    """
    lock_id = None
    
    try:
        # Try to acquire user-specific lock
        lock_id = lock_manager.acquire_user_lock(user_id, "automated", timeout=72000)
        
        if not lock_id:
            logger.info(f"SKIPPING: User {user_id} is already being processed (Redis lock exists)")
            return {"status": "skipped", "reason": "user_already_processing"}
        
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        user = User.objects.get(id=user_id)
        logger.info(f"AUTOMATED PROCESSING: Starting for user {user.username} (Lock ID: {lock_id}, Scope: {send_scope})")
        
        # Mark processing start
        EmailSettings.objects.filter(user=user).update(last_processed=timezone.now())
        
        # Use EXACT manual view filtering
        valid_solicitations = get_filtered_solicitations_for_autosend(user, send_scope)
        
        if not valid_solicitations:
            logger.info(f"No valid solicitations found for user {user.username}")
            return {"status": "completed", "message": "No valid solicitations"}
        
        logger.info(f"Found {len(valid_solicitations)} solicitations matching manual view filtering")
        
        # Create/get SolicitationEmailStatus records
        status_records = []
        status_mapping = {}
        
        for sol in valid_solicitations:
            # These should mostly be creates since we excluded already sent ones
            status, created = SolicitationEmailStatus.objects.get_or_create(
                solicitation=sol,
                user=user,
                defaults={
                    'email_sent': False,
                    'email_status': 'pending',
                    'processing_attempts': 0
                }
            )
            
            # Double-check (though filtering should have excluded these)
            if not status.email_sent and status.processing_attempts < 3:
                status_records.append(status)
                status_mapping[sol.id] = status.id
        
        if not status_records:
            logger.info(f"No pending solicitations to process for user {user.username}")
            return {"status": "completed", "message": "No pending solicitations"}
        
        logger.info(f"Will process {len(status_records)} solicitations for user {user.username}")
        
        # Mark as processing
        status_ids = [s.id for s in status_records]
        SolicitationEmailStatus.objects.filter(id__in=status_ids).update(
            email_status='processing',
            processing_attempts=F('processing_attempts') + 1
        )
        
        # Prepare solicitation data
        all_solicitations_data = []
        for status in status_records:
            solicitation = status.solicitation
            sol_data = {
                'cage': solicitation.cage or '',
                'nomenclature': solicitation.nomenclature or '',
                'quantity': str(solicitation.quantity) if solicitation.quantity else '1',
                'return_by_date': str(solicitation.return_by_date) if solicitation.return_by_date else '',
                'NSN': solicitation.NSN or '',
                'id': solicitation.id,
                'part_number': solicitation.part_number or ''
            }
            all_solicitations_data.append(sol_data)
        
        # Get user data and mail template
        user_data = get_user_data(user)
        mail_data = get_mail_template_data(user)
        
        # Use reliable batch size
        BATCH_SIZE = 15000
        total_batches = (len(all_solicitations_data) + BATCH_SIZE - 1) // BATCH_SIZE
        success_count = 0
        failure_count = 0
        
        # Find script path
        script_path = find_script_path()
        if not script_path:
            try:
                SolicitationEmailStatus.objects.filter(id__in=status_ids).update(email_status='failed')
                logger.error(f"CLEANUP: Script not found, marked records as failed")
            except Exception as cleanup_error:
                logger.error(f"CLEANUP ERROR: {cleanup_error}")
            raise FileNotFoundError("Email script not found")
        
        # Process in batches
        for batch_num in range(total_batches):
            # Extend lock if needed
            lock_status = lock_manager.check_user_lock_status(user_id, "automated")
            if lock_status and lock_status['ttl_seconds'] < 900:
                lock_manager.extend_user_lock(user_id, "automated", 1800)
            
            start_idx = batch_num * BATCH_SIZE
            end_idx = start_idx + BATCH_SIZE
            batch_data = all_solicitations_data[start_idx:end_idx]
            
            logger.info(f"Processing AUTOMATED batch {batch_num + 1}/{total_batches} for user {user.username}")
            
            script_data = {
                "user_data": user_data,
                "mail_data": mail_data,
                "solicitation_ids": [sol['id'] for sol in batch_data],
                "auto_mode": True
            }
            
            json_data = json.dumps(script_data)
            
            try:
                result = execute_script_with_json(script_path, json_data)
                logger.info(f"Script result: returncode={result.returncode}")
                
                if result.returncode == 0:
                    # Success
                    batch_status_ids = [status_mapping[sol['id']] for sol in batch_data]
                    
                    try:
                        with transaction.atomic():
                            updated = SolicitationEmailStatus.objects.filter(
                                id__in=batch_status_ids
                            ).update(
                                email_sent=True,
                                email_sent_at=timezone.now(),
                                email_status='sent'
                            )
                            logger.info(f"Updated {updated} records to 'sent'")
                        
                        success_count += len(batch_data)
                        logger.info(f"Batch {batch_num + 1} succeeded")
                    except Exception as db_e:
                        logger.error(f"Database error for batch {batch_num + 1}: {db_e}")
                        failure_count += len(batch_data)
                        
                        try:
                            with transaction.atomic():
                                SolicitationEmailStatus.objects.filter(
                                    id__in=batch_status_ids
                                ).update(email_status='failed')
                        except Exception as cleanup_error:
                            logger.error(f"CLEANUP ERROR: {cleanup_error}")
                else:
                    # Script failed
                    failure_count += len(batch_data)
                    logger.error(f"Batch {batch_num + 1} failed: Script returned {result.returncode}")
                    
                    try:
                        with transaction.atomic():
                            batch_status_ids = [status_mapping[sol['id']] for sol in batch_data]
                            SolicitationEmailStatus.objects.filter(
                                id__in=batch_status_ids
                            ).update(email_status='failed')
                    except Exception as update_e:
                        logger.error(f"Error updating failed statuses: {update_e}")
                        
            except Exception as e:
                failure_count += len(batch_data)
                logger.error(f"Error processing batch {batch_num + 1}: {e}")
                
                try:
                    with transaction.atomic():
                        batch_status_ids = [status_mapping[sol['id']] for sol in batch_data]
                        SolicitationEmailStatus.objects.filter(
                            id__in=batch_status_ids
                        ).update(email_status='failed')
                except Exception as cleanup_error:
                    logger.error(f"CLEANUP ERROR: {cleanup_error}")
        
        logger.info(f"AUTOMATED Processing complete for user {user.username}:")
        logger.info(f"  Total: {len(all_solicitations_data)}")
        logger.info(f"  Success: {success_count}")
        logger.info(f"  Failed: {failure_count}")
        
        return {
            "status": "completed",
            "total": len(all_solicitations_data),
            "success": success_count,
            "failed": failure_count,
            "user_id": user_id,
            "username": user.username
        }
            
    except Exception as e:
        logger.error(f"Error in process_user_solicitations for user {user_id}: {e}")
        
        # Clean up processing records
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.get(id=user_id)
            
            cleanup_count = SolicitationEmailStatus.objects.filter(
                user=user,
                email_status='processing'
            ).update(email_status='failed')
            
            logger.error(f"CLEANUP: Marked {cleanup_count} processing records as failed")
        except Exception as cleanup_error:
            logger.error(f"CLEANUP ERROR: {cleanup_error}")
        
        return {"status": "error", "error": str(e), "user_id": user_id}
    finally:
        if lock_id:
            lock_manager.release_user_lock(user_id, "automated", lock_id)
            logger.info(f"Released lock for user {user_id}")

def process_manual_rfq_batch(batch_ids, user_id, mail_data=None, user_data=None):
    """
    FIXED: GUARANTEED LOCK RELEASE and status cleanup using context manager approach
    """
    try:
        # Use context manager for guaranteed lock release
        with guaranteed_user_lock(user_id, "manual") as lock_info:
            logger.info(f"MANUAL PROCESSING: Starting for user {user_id} with {len(batch_ids)} RFQs")
            
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            # Get user
            try:
                user = User.objects.get(id=user_id)
                logger.info(f"Processing for user: {user.username} (ID: {user_id})")
            except User.DoesNotExist:
                logger.error(f"User with ID {user_id} not found")
                return {"status": "error", "error": f"User {user_id} not found"}
            
            # Get solicitations
            solicitations = Solicitation.objects.filter(id__in=batch_ids)
            found_count = solicitations.count()
            
            if found_count != len(batch_ids):
                logger.warning(f"Found {found_count} solicitations out of {len(batch_ids)} requested")
            
            # Get user data and mail data if not provided
            if not user_data:
                user_data = get_user_data(user)
            if not mail_data:
                mail_data = get_mail_template_data(user)
            
            # Bulk update status to processing
            solicitation_ids_found = list(solicitations.values_list('id', flat=True))
            
            status_updates = []
            for sol_id in solicitation_ids_found:
                status, created = SolicitationEmailStatus.objects.get_or_create(
                    solicitation_id=sol_id,
                    user=user,
                    defaults={'email_status': 'processing'}
                )
                if not created and status.email_status != 'processing':
                    status_updates.append(status.id)
            
            if status_updates:
                SolicitationEmailStatus.objects.filter(id__in=status_updates).update(email_status='processing')
            
            # Log CAGE code distribution
            from collections import defaultdict
            cage_summary = defaultdict(int)
            for sol in solicitations:
                cage_summary[sol.cage] += 1
            
            logger.info(f"CAGE code distribution for user {user_id}:")
            for cage, count in cage_summary.items():
                logger.info(f"   - CAGE {cage}: {count} items")
            
            # Find script path
            script_path = find_script_path()
            if not script_path:
                # CRITICAL FIX: Clean up processing status if script not found
                try:
                    SolicitationEmailStatus.objects.filter(
                        solicitation_id__in=batch_ids,
                        user=user,
                        email_status='processing'
                    ).update(email_status='failed')
                    logger.error(f"CLEANUP: Marked {len(batch_ids)} solicitations as failed (script not found)")
                except Exception as cleanup_error:
                    logger.error(f"CLEANUP ERROR: {cleanup_error}")
                
                raise FileNotFoundError("Email script not found")
            
            # Prepare data for script
            combined_data = {
                "user_data": user_data,
                "mail_data": mail_data,
                "solicitation_ids": batch_ids,
                "auto_mode": False
            }
            
            # Create temporary file and run script
            temp_file_path = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                    json.dump(combined_data, temp_file)
                    temp_file_path = temp_file.name
                
                logger.info(f"Running script for user {user_id} with {len(batch_ids)} solicitations")
                
                result = execute_script_with_file(script_path, temp_file_path)
                
                logger.info(f"Script execution completed for user {user_id}: returncode={result.returncode}")
                
                if result.returncode == 0:
                    logger.info(f"SUCCESS: Script succeeded for user {user_id}")
                    unique_cages = len(cage_summary)
                    
                    return {
                        "status": "success", 
                        "processed": len(batch_ids),
                        "unique_cage_codes": unique_cages,
                        "cage_distribution": dict(cage_summary),
                        "user_id": user_id,
                        "username": user.username,
                        "message": f"User {user.username} processed {len(batch_ids)} solicitations across {unique_cages} CAGE codes"
                    }
                else:
                    # SCRIPT FAILED - CRITICAL FIX: Clean up processing records
                    error_msg = result.stderr if result.stderr else f"Script returned code {result.returncode}"
                    logger.error(f"ERROR: Script failed for user {user_id}: {error_msg}")
                    
                    try:
                        cleanup_count = SolicitationEmailStatus.objects.filter(
                            solicitation_id__in=batch_ids,
                            user=user,
                            email_status='processing'
                        ).update(email_status='failed')
                        
                        logger.error(f"CLEANUP: Marked {cleanup_count} processing records as failed due to script failure")
                    except Exception as cleanup_error:
                        logger.error(f"CLEANUP ERROR: {cleanup_error}")
                    
                    return {
                        "status": "failed", 
                        "error": error_msg, 
                        "processed": 0,
                        "user_id": user_id,
                        "username": user.username,
                        "message": f"Script execution failed for user {user.username}"
                    }
                    
            finally:
                # Clean up temporary file
                if temp_file_path and os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            
        # Lock is automatically released here by the context manager
        
    except Exception as e:
        if "conflicting locks" in str(e):
            # Return skipped status for lock conflicts
            return {
                "status": "skipped", 
                "error": str(e),
                "user_id": user_id,
                "reason": "user_lock_exists"
            }
        else:
            logger.error(f"ERROR: Error processing MANUAL RFQ batch for user {user_id}: {e}")
            logger.error(traceback.format_exc())
            
            # CRITICAL FIX: Clean up processing status on task exception
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.get(id=user_id)
                
                cleanup_count = SolicitationEmailStatus.objects.filter(
                    solicitation_id__in=batch_ids,
                    user=user,
                    email_status='processing'
                ).update(email_status='failed')
                
                logger.error(f"TASK CLEANUP: Marked {cleanup_count} processing records as failed due to task exception")
            except Exception as cleanup_error:
                logger.error(f"TASK CLEANUP ERROR: {cleanup_error}")
            
            return {"status": "error", "error": str(e), "processed": 0, "user_id": user_id}

def process_large_manual_rfq_batch(selected_ids, user_id, batch_size=15000):
    """
    FIXED: Process large manual batch with Redis user lock
    Only one large batch operation can run per user at a time
    """
    lock_id = None
    
    try:
        # Check for conflicting locks first
        has_locks, lock_info = user_has_any_active_locks(user_id)
        if has_locks:
            logger.info(f"SKIPPING: User {user_id} has active locks: {lock_info}")
            return {
                "status": "skipped",
                "error": f"User has active processing operations: {[l['type'] for l in lock_info]}",
                "user_id": user_id,
                "reason": "user_has_locks",
                "active_locks": lock_info
            }
        
        # Try to acquire user-specific lock for large batch processing
        lock_id = lock_manager.acquire_user_lock(user_id, "large_batch", timeout=72000)  # 12 hours
        
        if not lock_id:
            logger.info(f"SKIPPING: User {user_id} failed to acquire large batch lock")
            return {
                "status": "skipped",
                "error": "Failed to acquire large batch processing lock",
                "user_id": user_id,
                "reason": "lock_acquisition_failed"
            }
        
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.get(id=user_id)
        
        logger.info(f"LARGE BATCH PROCESSING: Starting for user {user.username} with {len(selected_ids)} RFQs (Lock ID: {lock_id})")
        logger.info(f"PARALLEL PROCESSING: Multiple users can process simultaneously")
        
        # Get mail template and user data once
        mail_data = get_mail_template_data(user)
        user_data = get_user_data(user)
        
        # Process all at once to maintain CAGE consolidation (script handles filtering)
        if len(selected_ids) <= batch_size:
            # Process all at once - script maintains CAGE consolidation
            logger.info(f"Processing {len(selected_ids)} RFQs in single batch - script will handle CAGE consolidation")
            
            task_id = async_task(
                'solicitations.tasks.process_manual_rfq_batch',
                selected_ids,  # All IDs at once
                user_id,
                mail_data,
                user_data,
                task_name=f'MANUAL_RFQ_U{user_id}_{len(selected_ids)}items',
                group=f'Manual_RFQ_User_{user_id}',  # Shortened group name
                timeout=72000,  # 12 hours for large batch
            )
            
            logger.info(f"QUEUED: Queued single large batch for user {user_id}: Task {task_id}")
            
            # FIXED: Release the large_batch lock immediately after queuing
            # since the queued task will handle its own manual lock
            if lock_id:
                released = lock_manager.release_user_lock(user_id, "large_batch", lock_id)
                logger.info(f"Released large_batch lock after queuing single batch: {released}")
                lock_id = None  # Prevent double release in finally block
            
            return {
                "status": "queued",
                "total_batches": 1,
                "total_rfqs": len(selected_ids),
                "task_ids": [task_id],
                "batch_size": len(selected_ids),
                "consolidation": "handled_by_script"
            }
        else:
            # For extremely large batches, group by CAGE first to maintain consolidation
            logger.info(f"Very large batch ({len(selected_ids)} RFQs) - grouping by CAGE to maintain consolidation")
            
            # Get solicitations and group by CAGE
            from collections import defaultdict
            solicitations = Solicitation.objects.filter(id__in=selected_ids).values('id', 'cage')
            
            cage_groups = defaultdict(list)
            for sol in solicitations:
                cage_groups[sol['cage']].append(sol['id'])
            
            logger.info(f"Grouped {len(selected_ids)} RFQs into {len(cage_groups)} CAGE groups")
            
            # Process each CAGE group separately to maintain consolidation within each CAGE
            task_ids = []
            batch_num = 0
            
            for cage_code, cage_rfq_ids in cage_groups.items():
                batch_num += 1
                
                task_id = async_task(
                    'solicitations.tasks.process_manual_rfq_batch',
                    cage_rfq_ids,  # All RFQs for this CAGE
                    user_id,
                    mail_data,
                    user_data,
                    task_name=f'MANUAL_RFQ_U{user_id}_CAGE_{cage_code}_B{batch_num}',
                    group=f'Manual_RFQ_User_{user_id}',
                    timeout=72000,  # 12 hour per CAGE group
                )
                task_ids.append(task_id)
                
                logger.info(f"QUEUED: Queued CAGE {cage_code} batch with {len(cage_rfq_ids)} RFQs: Task {task_id}")
            
            logger.info(f"TOTAL: Total queued tasks for user {user_id}: {len(task_ids)}")
            
            # FIXED: Release the large_batch lock after queuing all tasks
            if lock_id:
                released = lock_manager.release_user_lock(user_id, "large_batch", lock_id)
                logger.info(f"Released large_batch lock after queuing {len(task_ids)} CAGE batches: {released}")
                lock_id = None  # Prevent double release in finally block
            
            return {
                "status": "queued",
                "total_batches": len(cage_groups),
                "total_rfqs": len(selected_ids),
                "task_ids": task_ids,
                "batch_size": "grouped_by_cage",
                "consolidation": "maintained_per_cage",
                "cage_groups": list(cage_groups.keys())
            }
        
    except Exception as e:
        logger.error(f"ERROR: Error queuing large MANUAL RFQ batch for user {user_id}: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}
    finally:
        # FIXED: Only release if lock wasn't already released above
        if lock_id:
            released = lock_manager.release_user_lock(user_id, "large_batch", lock_id)
            logger.info(f"Released large_batch lock in finally block for user {user_id}: {released}")
# ===============================
# ENHANCED SCHEDULING WITH LOCK CHECKING
# ===============================
def user_has_any_active_locks(user_id):
    """
    Check if a user has any active locks of any type
    Returns: (has_locks: bool, lock_info: list)
    """
    active_locks = []
    for lock_type in ['automated', 'manual', 'large_batch']:
        lock_status = lock_manager.check_user_lock_status(user_id, lock_type)
        if lock_status:
            active_locks.append({
                'type': lock_type,
                'ttl_seconds': lock_status['ttl_seconds'],
                'lock_id': lock_status['lock_id']
            })
    
    return len(active_locks) > 0, active_locks


def check_scheduled_emails():
    """
    ENHANCED: Check scheduled emails with proper timezone handling and filtering
    NOW USES ENHANCED FILTERING FOR BETTER QUALITY CONTROL
    """
    try:
        # Get timezone-aware current time
        now = timezone.now()
        
        # Convert to the configured timezone
        local_tz = pytz.timezone(settings.TIME_ZONE)  # America/New_York
        now_local = now.astimezone(local_tz)
        
        current_day = now_local.strftime("%A").lower()
        current_time = now_local.time()
        
        logger.info('--------------------------------------------------------------------------')
        logger.info(f"Current server time (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Current local time ({settings.TIME_ZONE}): {now_local.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Current day: {current_day}")
        logger.info(f"Current time (local): {current_time}")
        logger.info("ENHANCED FILTERING: Using manual process filters for autosend")
        
        # Check if any email settings exist at all
        total_settings = EmailSettings.objects.count()
        auto_enabled = EmailSettings.objects.filter(auto_send=True).count()

        logger.info(f'Found {total_settings} email settings, {auto_enabled} with auto-send enabled')
        
        # Create a 4-minute buffer window (2 minutes before and 2 minutes after) in LOCAL TIME
        two_min_ago = (datetime.combine(date.today(), current_time) - timedelta(minutes=2)).time()
        two_min_ahead = (datetime.combine(date.today(), current_time) + timedelta(minutes=2)).time()
        
        logger.info(f"Time window ({settings.TIME_ZONE}): {two_min_ago.strftime('%H:%M:%S')} to {two_min_ahead.strftime('%H:%M:%S')}")
        
        # Get all users with auto-send enabled and matching day (including daily option)
        auto_send_settings = EmailSettings.objects.filter(
            auto_send=True
        ).filter(
            Q(send_day=current_day) | Q(send_day='daily')
        ).select_related('user')
        
        logger.info(f"Users with auto-send enabled for today ({current_day}) or daily: {auto_send_settings.count()}")
        
        for setting in auto_send_settings:
            logger.info(f"Checking user: {setting.user.username}")
            logger.info(f"  Send day: {setting.send_day}")
            logger.info(f"  Send scope: {setting.send_scope}")
            
            # Log enabled time intervals
            enabled_times = setting.get_enabled_times()
            if enabled_times:
                times_str = ', '.join([t.strftime('%H:%M:%S') for t in enabled_times])
                logger.info(f"  Enabled times: {times_str}")
            else:
                logger.info(f"  No time intervals enabled - skipping user")
                continue
            
            # FIXED: Check locks before processing
            user_has_any_lock = False
            user_lock_info = None
            for lock_type in ['automated', 'manual', 'large_batch']:
                lock_status = lock_manager.check_user_lock_status(setting.user.id, lock_type)
                if lock_status:
                    user_has_any_lock = True
                    user_lock_info = f"{lock_type} lock (TTL: {lock_status['ttl_seconds']}s)"
                    break
            
            if user_has_any_lock:
                logger.info(f"  Skipping user {setting.user.username} - Redis lock exists: {user_lock_info}")
                continue
            
            # Check for existing tasks first
            existing_tasks = Task.objects.filter(
                func='solicitations.tasks.process_user_solicitations',
                args=str(setting.user.id),
                stopped__isnull=True
            ).count()
            
            if existing_tasks > 0:
                logger.info(f"  Skipping user {setting.user.username} - {existing_tasks} tasks already exist")
                continue
                
            # Check cooldown period - 60 minutes
            if setting.last_processed:
                # Convert last_processed to local timezone for comparison
                last_processed_local = setting.last_processed.astimezone(local_tz)
                time_since_last = now_local - last_processed_local
                if time_since_last < timedelta(minutes=60):
                    logger.info(f"  Skipping user {setting.user.username} - processed recently at {last_processed_local}")
                    continue
            
            # NEW: Use the model's is_time_to_send method for multiple time intervals
            time_window_match = setting.is_time_to_send(current_time)
            logger.info(f"  Time window match? {time_window_match}")
            
            if time_window_match:
                # Check if there are any pending solicitations for this user
                has_pending = check_pending_solicitations(setting.user)
                
                if not has_pending:
                    logger.info(f"  Skipping user {setting.user.username} - no pending solicitations")
                    continue
                
                # PREVIEW: Show what filtering will find
                try:
                    preview_solicitations = get_filtered_solicitations_for_autosend(setting.user, setting.send_scope)
                    logger.info(f"  PREVIEW: Enhanced filtering found {len(preview_solicitations)} valid solicitations")
                except Exception as preview_e:
                    logger.warning(f"  PREVIEW ERROR: {preview_e}")
                
                # Mark the last processed time BEFORE scheduling the task
                EmailSettings.objects.filter(user=setting.user).update(last_processed=timezone.now())
                
                # Schedule a new task for this user with send scope information
                # NOTE: This uses the ENHANCED process_user_solicitations function
                task_id = async_task(
                    'solicitations.tasks.process_user_solicitations', 
                    setting.user.id,
                    setting.send_scope,  # Pass the send scope to the task
                    task_name=f"AUTOMATED ENHANCED Process emails for {setting.user.username} ({setting.send_scope})",
                    sync=False
                )
                logger.info(f"  Scheduled ENHANCED email processing task with ID: {task_id} (scope: {setting.send_scope})")
            else:
                logger.info(f"  Not processing user {setting.user.username} - outside time window")
        
        logger.info("COMPLETED ENHANCED SCHEDULED EMAIL CHECK")
        logger.info("------------------------")
        
    except Exception as e:
        logger.error(f"Error in check_scheduled_emails: {str(e)}")
        logger.error(traceback.format_exc())
# ===============================
# LOCK MONITORING AND MANAGEMENT FUNCTIONS
# ===============================

def get_all_user_locks():
    """
    Get status of all user processing locks
    Useful for monitoring and debugging
    """
    try:
        logger.info("=== USER LOCK STATUS REPORT ===")
        
        # Get all active locks
        pattern = "user_processing_lock:*"
        redis_client = lock_manager.redis
        lock_keys = redis_client.keys(pattern)
        
        if not lock_keys:
            logger.info("No active user locks found")
            return []
        
        active_locks = []
        for key in lock_keys:
            try:
                # Parse key: user_processing_lock:USER_ID:LOCK_TYPE
                parts = key.split(':')
                if len(parts) >= 3:
                    user_id = parts[1]
                    lock_type = parts[2]
                    
                    lock_value = redis_client.get(key)
                    ttl = redis_client.ttl(key)
                    
                    lock_info = {
                        'user_id': user_id,
                        'lock_type': lock_type,
                        'lock_id': lock_value,
                        'ttl_seconds': ttl,
                        'ttl_minutes': round(ttl / 60, 1) if ttl > 0 else 0
                    }
                    
                    active_locks.append(lock_info)
                    logger.info(f"Active lock: User {user_id}, Type: {lock_type}, TTL: {lock_info['ttl_minutes']} min")
                    
            except Exception as e:
                logger.error(f"Error parsing lock key {key}: {e}")
        
        logger.info(f"Total active locks: {len(active_locks)}")
        return active_locks
        
    except Exception as e:
        logger.error(f"Error getting user lock status: {e}")
        return []

def cleanup_stale_user_locks():
    """
    SAFETY NET: This should rarely find anything to clean
    since locks are released immediately when tasks finish
    """
    try:
        logger.info("=== SAFETY NET LOCK CLEANUP ===")
        
        pattern = "user_processing_lock:*"
        redis_client = lock_manager.redis
        lock_keys = redis_client.keys(pattern)
        
        if not lock_keys:
            logger.info("No stale locks found (this is good!)")
            return {'cleaned': 0, 'total': 0}
        
        current_time = time.time()
        cleaned_count = 0
        
        for key in lock_keys:
            try:
                lock_value = redis_client.get(key)
                if lock_value:
                    try:
                        timestamp = int(lock_value.split('_')[-1])
                        age_minutes = (current_time - timestamp) / 60
                        
                        # VERY AGGRESSIVE: Clean locks older than 2 minutes
                        # (since normal tasks complete in 0.05 seconds)
                        if age_minutes > 2:
                            parts = key.split(':')
                            if len(parts) >= 3:
                                user_id = parts[1]
                                lock_type = parts[2]
                                
                                deleted = redis_client.delete(key)
                                if deleted:
                                    cleaned_count += 1
                                    logger.warning(f"SAFETY NET: Cleaned stale lock: User {user_id}, Type {lock_type}, Age: {age_minutes:.1f} min")
                                
                    except (ValueError, IndexError):
                        deleted = redis_client.delete(key)
                        if deleted:
                            cleaned_count += 1
                            logger.warning(f"SAFETY NET: Cleaned unparseable lock: {key}")
                            
            except Exception as e:
                logger.error(f"Error processing lock key {key}: {e}")
        
        if cleaned_count > 0:
            logger.warning(f"SAFETY NET: Cleaned {cleaned_count} stale locks (investigate why locks weren't released immediately)")
        else:
            logger.info("SAFETY NET: No stale locks found (locks being released properly)")
        
        return {
            'cleaned': cleaned_count,
            'total': len(lock_keys),
            'remaining': len(lock_keys) - cleaned_count
        }
        
    except Exception as e:
        logger.error(f"Error during safety net cleanup: {e}")
        return {'error': str(e)}

def force_release_user_lock(user_id, lock_type="processing"):
    """
    Force release a user lock (emergency function)
    Use with caution - only when you're sure no legitimate process is running
    """
    try:
        logger.warning(f"FORCE RELEASING lock for user {user_id}, type: {lock_type}")
        
        # Check if lock exists first
        lock_status = lock_manager.check_user_lock_status(user_id, lock_type)
        if not lock_status:
            logger.info(f"No lock found for user {user_id}, type: {lock_type}")
            return False
        
        logger.warning(f"Found lock: {lock_status}")
        
        # Force release without lock_id verification
        released = lock_manager.release_user_lock(user_id, lock_type, lock_id=None)
        
        if released:
            logger.warning(f"Successfully force-released lock for user {user_id}")
        else:
            logger.error(f"Failed to force-release lock for user {user_id}")
            
        return released
        
    except Exception as e:
        logger.error(f"Error force-releasing lock for user {user_id}: {e}")
        return False

# ===============================
# ENHANCED MONITORING FUNCTIONS
# ===============================

def get_user_processing_status(user_id):
    """
    Get comprehensive processing status for a specific user
    Includes Redis locks, database tasks, and email status
    """
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        user = User.objects.get(id=user_id)
        
        # Check Redis locks
        locks = {}
        for lock_type in ['automated', 'manual', 'large_batch', 'processing']:
            lock_status = lock_manager.check_user_lock_status(user_id, lock_type)
            if lock_status:
                locks[lock_type] = lock_status
        
        # Check active Django Q tasks
        active_tasks = Task.objects.filter(
            args__contains=str(user_id),
            stopped__isnull=True
        ).values('id', 'name', 'func', 'started', 'task_name')
        
        # Check pending solicitations
        pending_count = SolicitationEmailStatus.objects.filter(
            user=user,
            email_sent=False,
            processing_attempts__lt=3
        ).count()
        
        # Check email settings
        email_settings = EmailSettings.objects.filter(user=user).first()
        
        status = {
            'user_id': user_id,
            'username': user.username,
            'redis_locks': locks,
            'active_tasks': list(active_tasks),
            'pending_solicitations': pending_count,
            'email_settings': {
                'auto_send': email_settings.auto_send if email_settings else False,
                'last_processed': email_settings.last_processed if email_settings else None,
                'send_day': email_settings.send_day if email_settings else None,
                'send_time': email_settings.send_time if email_settings else None
            } if email_settings else None,
            'can_process': len(locks) == 0,  # Can process if no locks
            'processing_blocked_by': list(locks.keys()) if locks else []
        }
        
        return status
        
    except Exception as e:
        logger.error(f"Error getting processing status for user {user_id}: {e}")
        return None

# ===============================
# EXISTING FUNCTIONS (UNCHANGED)
# ===============================

def find_script_path():
    """Helper to find the script path"""
    possible_paths = [
        "/home/gilgalrfq/DLA/infoExtractorSendRfq.py",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

def execute_script_with_json(script_path, json_data):
    """Helper to execute the external script with JSON data as argument"""
    venv_python = "/home/gilgalrfq/env/bin/python"
    return subprocess.run(
        [venv_python, script_path, json_data],
        capture_output=True,
        text=True,
        timeout=72000  # 12 hour timeout
    )

def execute_script_with_file(script_path, file_path):
    """Helper to execute the external script with file argument"""
    venv_python = "/home/gilgalrfq/env/bin/python"
    return subprocess.run(
        [venv_python, script_path, f"--file={file_path}"],
        capture_output=True,
        text=True,
        timeout=72000  # 35 min timeout
    )

def get_user_data(user):
    """Get user data needed for email processing"""
    return {
        'username': user.username,
        'email': user.email,
        'phone': getattr(user, 'phone', "Not Provided"),
        'address': getattr(user, 'address', "Your Address"),
        'companyName': getattr(user, 'companyName', "Your Company Name"),
        'logo': user.logo.url if hasattr(user, 'logo') and user.logo else None,
        'website': getattr(user, 'website', "https://example.com"),
        'personal_email': getattr(user, 'personal_email', ""),
        'title': getattr(user, 'title', ""),
        'first_name': user.first_name,
        'last_name': user.last_name,
        'fax': getattr(user, 'fax', ""),
    }

def get_mail_template_data(user):
    """Get mail template data for the user"""
    try:
        mail_template = MailTemplate.objects.filter(userMail=user).first()
        if mail_template:
            return {
                "salutation": mail_template.salutation or "Dear Mr/Ms",
                "heading": mail_template.heading or "REQUEST FOR QUOTATION",
                "body": mail_template.body or "I hope this message finds you well...",
            }
    except Exception as e:
        logger.error(f"Error retrieving mail template: {str(e)}")
    
    return {
        "salutation": "Dear Mr/Ms",
        "heading": "REQUEST FOR QUOTATION",
        "body": "I hope this message finds you well..."
    }

def check_pending_solicitations(user):
    """
    Check if there are any pending solicitations for this user.
    """
    # Get all solicitations that need processing for this user
    pending_count = SolicitationEmailStatus.objects.filter(
        user=user,
        email_sent=False,
        processing_attempts__lt=3
    ).count()
    
    return pending_count > 0

def create_solicitation_email_statuses():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    today = datetime.today().strftime("%m-%d-%Y")
    
    # Get all solicitations that are valid (have cage codes and haven't passed return date)
    valid_solicitations = []
    all_solicitations = Solicitation.objects.all().exclude(Q(cage='-') | Q(cage='N/A')).filter(return_by_date__gte=today)
    
    current_date = timezone.now().date()
    logger.info(f"Current date: {current_date}")
    logger.info(f"Found {all_solicitations.count()} total solicitations")
    
    for sol in all_solicitations:
        # Skip invalid solicitations
        if not sol.cage or sol.cage.strip() == '-':
            continue
            
        # Date validation
        try:
            return_date = None
            if sol.return_by_date:
                # Try multiple date formats
                for fmt in ('%m-%d-%Y', '%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d'):
                    try:
                        return_date = datetime.strptime(sol.return_by_date, fmt).date()
                        break
                    except ValueError:
                        continue
                if not return_date:
                    continue
                    
                if return_date < current_date:
                    continue
        except Exception as e:
            logger.error(f"Error processing date for solicitation {sol.id}: {str(e)}")
            continue
        
        valid_solicitations.append(sol)
    
    logger.info(f"Found {len(valid_solicitations)} valid solicitations")
    
    # Get users with email settings enabled
    users_with_email = User.objects.filter(email_settings__auto_send=True)
    
    logger.info(f"Found {users_with_email.count()} users with auto-send enabled")
    
    # Create status records for each valid solicitation for each user
    count = 0
    for user in users_with_email:
        logger.info(f"Processing user: {user.username}")
        for sol in valid_solicitations:
            # Check if status already exists
            status, created = SolicitationEmailStatus.objects.get_or_create(
                solicitation=sol,
                user=user,
                defaults={
                    'email_status': 'pending',
                    'email_sent': False,
                    'processing_attempts': 0
                }
            )
            if created:
                count += 1
                
    logger.info(f"Created {count} new email status records")

def setup_email_schedule():
    """Universal function that works in both sync and async contexts"""
    import asyncio
    
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context, use threaded version
        logger.info("Detected async context, using threaded setup")
        setup_email_schedule_threaded()
    except RuntimeError:
        # We're in a sync context, use normal version
        logger.info("Detected sync context, using direct setup")
        setup_email_schedule_sync_only()

def emergency_cleanup_stale_processing():
    """
    Emergency cleanup of stale processing records - to be run periodically
    This is a safety net to prevent accumulation of stale records
    """
    try:
        from datetime import timedelta
        
        # Clean up records stuck in processing for more than 30 minutes
        cutoff_time = timezone.now() - timedelta(minutes=30)
        
        # Find stale processing records
        stale_records = SolicitationEmailStatus.objects.filter(
            email_status='processing'
            # Note: Add timestamp filtering when you have updated_at field
            # updated_at__lt=cutoff_time
        )
        
        stale_count = stale_records.count()
        
        if stale_count > 0:
            # Reset them to pending (not failed) so they can be retried
            stale_records.update(
                email_status='pending',
                processing_attempts=0
            )
            
            logger.warning(f"EMERGENCY CLEANUP: Reset {stale_count} stale processing records to pending")
            
            # Also clear any user selection states that reference these
            UserSelectionState.objects.filter(
                processing_ids__isnull=False
            ).exclude(
                processing_ids=[]
            ).update(
                processing_ids=[],
                is_submitting=False
            )
            
            logger.warning(f"EMERGENCY CLEANUP: Cleared user selection states")
        else:
            logger.info("EMERGENCY CLEANUP: No stale processing records found")
        
        return stale_count
        
    except Exception as e:
        logger.error(f"Error in emergency cleanup: {e}")
        return 0

def setup_emergency_cleanup_schedule():
    """
    Set up periodic emergency cleanup - django-q2 compatible
    """
    from django_q.models import Schedule
    
    try:
        # Check if schedule already exists
        if Schedule.objects.filter(name='emergency_cleanup_stale_processing').exists():
            logger.info("Emergency cleanup schedule already exists")
            return Schedule.objects.get(name='emergency_cleanup_stale_processing')
        
        cleanup_schedule = Schedule.objects.create(
            name='emergency_cleanup_stale_processing',
            func='solicitations.tasks.emergency_cleanup_stale_processing',
            hook=None,
            args=None,
            kwargs=None,
            schedule_type=Schedule.MINUTES,
            minutes=30,
            repeats=-1,
            cron=None,
            task=None,
            cluster=None,
            intended_date_kwarg=None
        )
        
        logger.info("Created emergency cleanup schedule (every 30 minutes)")
        return cleanup_schedule
        
    except Exception as e:
        logger.error(f"Error setting up emergency cleanup schedule: {e}")
        return None