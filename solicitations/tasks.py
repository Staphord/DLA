from django.utils import timezone
from datetime import datetime, timedelta, date
import pytz
from django.db.models import Q, F
from django_q.models import OrmQ, Task
from django.conf import settings
from django.core.cache import cache
from .models import (
    AutoScrapeQueueItem,
    DEFAULT_RESALE_NOTICE_TEXT,
    EmailSettings,
    MailTemplate,
    OEM,
    OEMImportJob,
    OEMUser,
    RfqAutoFetchSettings,
    RfqAutoFetchStatus,
    ScrapeNSNStatus,
    ScrapingSchedule,
    Solicitation,
    SolicitationEmailStatus,
    UserOEMCustomization,
)
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
import platform
import re
from contextlib import contextmanager
import asyncio
from asgiref.sync import sync_to_async
import pandas as pd
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


def process_oem_import_job(job_id: int):
    """
    Background task to import OEMs from an Excel file.
    Progress is persisted to OEMImportJob so refresh/navigation won't stop it.
    """
    try:
        job = OEMImportJob.objects.select_related('user').get(id=job_id)
    except OEMImportJob.DoesNotExist:
        return

    user = job.user
    job.status = OEMImportJob.STATUS_RUNNING
    job.error_message = ''
    job.save(update_fields=['status', 'error_message', 'updated_at'])

    def save_progress(force=False):
        # Reduce DB writes: save every ~10 rows or when forced.
        if force or (job.processed % 10 == 0):
            job.save(update_fields=[
                'processed', 'total',
                'added_active', 'updated_active', 'disabled',
                'skipped', 'errors',
                'status', 'failed_download_url',
                'error_message', 'updated_at'
            ])

    failed_rows = []
    try:
        if not job.file_path or not os.path.exists(job.file_path):
            job.status = OEMImportJob.STATUS_ERROR
            job.error_message = 'Import file not found on server.'
            job.save(update_fields=['status', 'error_message', 'updated_at'])
            return

        df = pd.read_excel(job.file_path)
        required_columns = ['Name', 'Cage', 'Email']
        if any(col not in df.columns for col in required_columns):
            job.status = OEMImportJob.STATUS_ERROR
            job.error_message = 'Missing required columns (Name, Cage, Email).'
            job.save(update_fields=['status', 'error_message', 'updated_at'])
            return

        job.total = int(len(df))
        job.processed = 0
        job.added_active = 0
        job.updated_active = 0
        job.disabled = 0
        job.skipped = 0
        job.errors = 0
        save_progress(force=True)

        def get_value(row, col, default='-'):
            try:
                v = row.get(col)
            except Exception:
                v = None
            if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip()):
                return default
            return str(v).strip()

        def normalize_cage(v):
            return str(v).strip().upper()

        def validate_emails(email_raw):
            # Supports multiple emails separated by ; or ,
            raw = (email_raw or '').strip()
            parts = [p.strip() for p in re.split(r'[;,]+', raw) if p.strip()]
            if not parts:
                return False, raw
            for p in parts:
                try:
                    validate_email(p)
                except ValidationError:
                    return False, raw
            return True, '; '.join(parts)

        for idx, row in df.iterrows():
            job.processed += 1
            try:
                name = get_value(row, 'Name', default='Unknown')
                cage = normalize_cage(get_value(row, 'Cage', default=''))
                email_raw = get_value(row, 'Email', default='')
                ok_email, email_clean = validate_emails(email_raw)

                if not cage or cage in {'-', 'N/A'}:
                    job.errors += 1
                    failed_rows.append({'row': int(idx) + 2, 'reason': 'Missing cage'})
                    continue

                if not ok_email:
                    # Save as disabled (errors) with customization for user reference
                    existing_oem = OEM.objects.filter(cage__iexact=cage).first()
                    if not existing_oem:
                        existing_oem = OEM.objects.create(
                            name=name,
                            cage=cage,
                            email=email_raw or 'invalid@email.com',
                            phone=get_value(row, 'Phone'),
                            fax=get_value(row, 'Fax'),
                            city=get_value(row, 'City'),
                            street=get_value(row, 'Street'),
                            postal_code=get_value(row, 'Zip Code'),
                            poc=get_value(row, 'POC'),
                            data_source='import',
                            manual_override=True,
                        )
                    oem_user, _ = OEMUser.objects.get_or_create(
                        user=user,
                        oem=existing_oem,
                        defaults={'is_disabled': True, 'reason': 'Import failed: invalid email'},
                    )
                    if not oem_user.is_disabled:
                        oem_user.is_disabled = True
                        oem_user.reason = 'Import failed: invalid email'
                        oem_user.save(update_fields=['is_disabled', 'reason'])
                    UserOEMCustomization.objects.update_or_create(
                        user=user,
                        oem=existing_oem,
                        defaults={
                            'custom_name': name,
                            'custom_email': email_raw or 'invalid@email.com',
                            'custom_phone': get_value(row, 'Phone'),
                            'custom_fax': get_value(row, 'Fax'),
                            'custom_city': get_value(row, 'City'),
                            'custom_street': get_value(row, 'Street'),
                            'custom_postal_code': get_value(row, 'Zip Code'),
                            'custom_poc': get_value(row, 'POC'),
                        },
                    )
                    job.disabled += 1
                    continue

                # Active import path
                oem = OEM.objects.filter(cage__iexact=cage).first()
                if not oem:
                    oem = OEM.objects.create(
                        name=name,
                        cage=cage,
                        email=email_clean,
                        phone=get_value(row, 'Phone'),
                        fax=get_value(row, 'Fax'),
                        city=get_value(row, 'City'),
                        street=get_value(row, 'Street'),
                        postal_code=get_value(row, 'Zip Code'),
                        poc=get_value(row, 'POC'),
                        data_source='import',
                        manual_override=True,
                    )
                    OEMUser.objects.get_or_create(user=user, oem=oem, defaults={'is_disabled': False})
                    UserOEMCustomization.objects.update_or_create(
                        user=user,
                        oem=oem,
                        defaults={
                            'custom_name': name,
                            'custom_email': email_clean,
                            'custom_phone': get_value(row, 'Phone'),
                            'custom_fax': get_value(row, 'Fax'),
                            'custom_city': get_value(row, 'City'),
                            'custom_street': get_value(row, 'Street'),
                            'custom_postal_code': get_value(row, 'Zip Code'),
                            'custom_poc': get_value(row, 'POC'),
                        },
                    )
                    job.added_active += 1
                else:
                    # Ensure association active and update user's customization only.
                    oem_user, created_assoc = OEMUser.objects.get_or_create(
                        user=user,
                        oem=oem,
                        defaults={'is_disabled': False},
                    )
                    # If this user didn't have the OEM before, it should be counted as "added".
                    if created_assoc:
                        job.added_active += 1
                    else:
                        if oem_user.is_disabled:
                            oem_user.is_disabled = False
                            oem_user.reason = ''
                            oem_user.save(update_fields=['is_disabled', 'reason'])
                        job.updated_active += 1
                    UserOEMCustomization.objects.update_or_create(
                        user=user,
                        oem=oem,
                        defaults={
                            'custom_name': name,
                            'custom_email': email_clean,
                            'custom_phone': get_value(row, 'Phone'),
                            'custom_fax': get_value(row, 'Fax'),
                            'custom_city': get_value(row, 'City'),
                            'custom_street': get_value(row, 'Street'),
                            'custom_postal_code': get_value(row, 'Zip Code'),
                            'custom_poc': get_value(row, 'POC'),
                        },
                    )

            except Exception as e:
                job.errors += 1
                failed_rows.append({'row': int(idx) + 2, 'reason': str(e)})
            finally:
                save_progress()

        # Save failed rows CSV if any
        if failed_rows:
            try:
                base_dir = os.path.join(settings.BASE_DIR, 'media', 'oem_import_failures')
                os.makedirs(base_dir, exist_ok=True)
                fname = f'oem_import_failed_{job.id}.json'
                out_path = os.path.join(base_dir, fname)
                with open(out_path, 'w') as f:
                    json.dump(failed_rows, f)
                media_url = getattr(settings, 'MEDIA_URL', '/media/')
                job.failed_download_url = f"{media_url.rstrip('/')}/oem_import_failures/{fname}"
            except Exception:
                pass

        job.status = OEMImportJob.STATUS_COMPLETED
        save_progress(force=True)

    except Exception as e:
        job.status = OEMImportJob.STATUS_ERROR
        job.error_message = str(e)
        job.save(update_fields=['status', 'error_message', 'updated_at'])

logger = logging.getLogger('rfq')

# Import RFQ reply extraction functions
try:
    from extractRfqReplies import extract_rfq_replies_for_user, extract_rfq_replies_for_all_users
except ImportError:
    logger.warning("Could not import extractRfqReplies module")
    extract_rfq_replies_for_user = None
    extract_rfq_replies_for_all_users = None

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
            # Get Redis connection from Django cache (django_redis backend)
            try:
                backend = cache
                if hasattr(backend, 'client') and hasattr(backend.client, 'get_client'):
                    self.redis = backend.client.get_client(write=True)
                    logger.info("Using Django cache Redis connection for locks")
                else:
                    raise AttributeError("Cache backend does not expose get_client")
            except Exception as e:
                logger.warning(f"Could not get Redis from Django cache: {e}")
                # Fallback to direct Redis connection
                self.redis = redis.Redis(
                    host=getattr(settings, 'REDIS_HOST', 'localhost'),
                    port=getattr(settings, 'REDIS_PORT', 6379),
                    db=getattr(settings, 'REDIS_DB', 0),
                    decode_responses=True  # THIS IS KEY - ensures strings not bytes
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
                logger.info(
                    f"LOCK ACQUIRED - User {user_id}, Type: {lock_type}, Lock ID: {lock_id}")
                return lock_id
            else:
                existing_lock = self.redis.get(lock_key)
                existing_lock = self._ensure_string(
                    existing_lock)  # FIX: Handle bytes
                logger.info(
                    f"LOCK EXISTS - User {user_id}, Type: {lock_type}, Existing: {existing_lock}")
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
                current_lock = self._ensure_string(
                    current_lock)  # FIX: Handle bytes
                lock_id = self._ensure_string(lock_id)  # FIX: Ensure string

                if current_lock != lock_id:
                    logger.warning(
                        f"LOCK MISMATCH - User {user_id}, Expected: {lock_id}, Current: {current_lock}")
                    logger.warning(
                        f"LOCK MISMATCH - Types: Expected {type(lock_id)}, Current {type(current_lock)}")
                    # FIX: Try to release anyway if the core ID matches
                    if current_lock and lock_id and current_lock.endswith(lock_id.split('_')[-1]):
                        logger.info(
                            "Lock IDs match structurally, proceeding with release")
                    else:
                        return False

            # Release the lock
            deleted = self.redis.delete(lock_key)

            if deleted:
                logger.info(
                    f"LOCK RELEASED - User {user_id}, Type: {lock_type}, Lock ID: {lock_id}")
                return True
            else:
                logger.warning(
                    f"LOCK NOT FOUND - User {user_id}, Type: {lock_type}")
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
                lock_value = self._ensure_string(
                    lock_value)  # FIX: Handle bytes
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
                logger.info(
                    f"LOCK EXTENDED - User {user_id}, New TTL: {new_ttl} seconds")
                return True
            else:
                logger.warning(
                    f"LOCK NOT EXTENDABLE - User {user_id}, TTL: {current_ttl}")
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

            logger.info(
                f"LOCK CLEANUP - Found {active_locks} active locks out of {len(lock_keys)} total")
            return active_locks

        except Exception as e:
            logger.error(f"Error during lock cleanup: {e}")
            return 0


# Global lock manager instance
lock_manager = UserProcessingLock()

def _extract_solicitations_running():
    """Return (is_running, alive_pids). Windows always (False, []) — same as prior behavior."""
    if platform.system() == "Windows":
        return False, []
    try:
        check_process = subprocess.run(
            ["pgrep", "-f", "extractSolicitations.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if check_process.returncode != 0:
            return False, []
        running_pids = [p for p in check_process.stdout.strip().split("\n") if p]
        alive_pids = []
        for pid in running_pids:
            try:
                result = subprocess.run(
                    ["kill", "-0", pid],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=2,
                )
                if result.returncode == 0:
                    alive_pids.append(pid)
            except Exception:
                pass
        return (len(alive_pids) > 0), alive_pids
    except (FileNotFoundError, subprocess.SubprocessError):
        return False, []


def _auto_scrape_queue_contains_phase(phase):
    try:
        return AutoScrapeQueueItem.objects.filter(phase=phase).exists()
    except Exception as e:
        logger.error(f"Auto-scrape queue: contains check failed: {e}")
        return False


def _auto_scrape_enqueue_phase(phase):
    """Append one queued phase (DB row). Dedupe: same phase not added twice."""
    if phase not in ("first", "second"):
        return False
    try:
        if AutoScrapeQueueItem.objects.filter(phase=phase).exists():
            logger.info(
                f"Auto-scrape queue: phase '{phase}' already queued, not duplicating."
            )
            return False
        AutoScrapeQueueItem.objects.create(phase=phase)
        logger.info(f"Auto-scrape queue: enqueued phase '{phase}' (FIFO, DB).")
        return True
    except Exception as e:
        logger.error(f"Auto-scrape queue: enqueue failed: {e}")
        return False


def _auto_scrape_requeue_phase_after_failed_start(phase):
    """
    If starting the subprocess fails after we removed a queue row, add it back
    (tail of FIFO). Skips if that phase is already queued.
    """
    if phase not in ("first", "second"):
        return
    try:
        if AutoScrapeQueueItem.objects.filter(phase=phase).exists():
            return
        AutoScrapeQueueItem.objects.create(phase=phase)
        logger.info(
            f"Auto-scrape queue: re-queued phase '{phase}' after failed start (tail)."
        )
    except Exception as e:
        logger.error(f"Auto-scrape queue: re-queue after failed start failed: {e}")


def _compute_auto_scrape_phase(schedule, today_date):
    """
    Decide if this tick has scheduled work (first/second window + NSN phase flags).
    Returns (phase_or_none, skip_payload_or_none). skip_payload is returned only when
    the tick should end immediately with no queue drain (nothing useful to do this tick).
    """
    try:
        has_first = ScrapeNSNStatus.objects.filter(
            scrape_date=today_date, phase=ScrapeNSNStatus.PHASE_FIRST
        ).exists()
        has_second = ScrapeNSNStatus.objects.filter(
            scrape_date=today_date, phase=ScrapeNSNStatus.PHASE_SECOND
        ).exists()

        in_first_window = check_scraping_schedule()

        in_second_window = False
        second_time = schedule.second_scrape_time
        if second_time:
            now_dt = timezone.localtime(timezone.now())
            current_time = now_dt.time()
            current_minutes = current_time.hour * 60 + current_time.minute
            scheduled_minutes = second_time.hour * 60 + second_time.minute
            minute_delta_second = current_minutes - scheduled_minutes
            if 0 <= minute_delta_second <= 2:
                in_second_window = True

        allow_first_rerun = False
        try:
            if (
                schedule.last_run
                and schedule.last_run.date() == today_date
                and schedule.last_run_status in ("failed", "stopped")
                and schedule.last_updated
                and schedule.last_updated.date() == today_date
            ):
                allow_first_rerun = True
        except Exception:
            allow_first_rerun = False

        if in_first_window and (not has_first or allow_first_rerun):
            phase_arg = "first"
            if allow_first_rerun and has_first:
                logger.info(
                    f"Auto-scrape: re-running FIRST phase for {today_date} after failed/stopped run "
                    f"and schedule update today."
                )
            else:
                logger.info(f"Auto-scrape: running FIRST phase for {today_date}")
            return phase_arg, None

        if in_second_window and not has_second:
            logger.info(
                f"Auto-scrape: running SECOND phase for {today_date} at second-phase time {second_time}"
            )
            return "second", None

        reason = "no_phase_selected"
        if has_first and has_second:
            reason = "both_phases_completed"
            logger.info(
                f"Auto-scrape: both first and second phases already recorded for {today_date}, skipping scheduled slot."
            )
        elif not in_first_window and not in_second_window:
            reason = "not_in_any_time_window"
            logger.info(
                f"Auto-scrape: not in time window for either phase "
                f"(first at {schedule.scrape_time}, second at {schedule.second_scrape_time})."
            )
        elif in_first_window and has_first:
            reason = "first_phase_already_recorded"
            logger.info(
                f"Auto-scrape: first-phase NSN status already recorded for {today_date} in first-phase window. Skipping."
            )
        elif in_second_window and has_second:
            reason = "second_phase_already_recorded"
            logger.info(
                f"Auto-scrape: second-phase NSN status already recorded for {today_date} in second-phase window. Skipping."
            )
        return None, {"status": "skipped", "reason": reason}

    except Exception as e:
        logger.error(f"Error determining scraping phase for {today_date}: {e}")
        logger.info("Falling back to FIRST phase due to error in phase selection.")
        return "first", None


def _auto_scrape_start_subprocess(schedule, phase_arg, today, log_label=""):
    """Start extractSolicitations.py; assumes paths validated. Sets last_run_status running."""
    BASE_DIR = settings.BASE_DIR
    if platform.system() == "Windows":
        python_exec = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
    else:
        python_exec = os.path.join(BASE_DIR, "venv", "bin", "python")
    script_path = os.path.join(BASE_DIR, "extractSolicitations.py")

    if not os.path.exists(script_path):
        logger.error(f"Scraping script not found at {script_path}")
        return {"status": "error", "message": f"Script not found at {script_path}"}
    if not os.path.exists(python_exec):
        logger.error(f"Python executable not found at {python_exec}")
        return {"status": "error", "message": f"Python executable not found at {python_exec}"}

    log_dir = os.path.join(settings.BASE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(
        log_dir, f"scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    working_dir = str(BASE_DIR)

    schedule.last_run_status = "running"
    schedule.save(update_fields=["last_run_status"])

    process = subprocess.Popen(
        [python_exec, script_path, today, phase_arg],
        stdout=open(log_file, "w"),
        stderr=subprocess.STDOUT,
        text=True,
        cwd=working_dir,
        start_new_session=True,
    )
    suffix = f" {log_label}" if log_label else ""
    logger.info(
        f"Automatic scraping started{suffix}: PID {process.pid}, Date: {today}, phase: {phase_arg}, Log: {log_file}"
    )

    return {
        "status": "started",
        "pid": process.pid,
        "date": today,
        "phase": phase_arg,
        "log_file": log_file,
    }


def _auto_scrape_try_start_after_runner_finished():
    """
    When a scrape just finished (idle), start the next queued job immediately if any.
    Serializes with other auto-scrape workers via ScrapingSchedule row lock.
    """
    schedule = ScrapingSchedule.objects.first()
    if not schedule or not schedule.enabled:
        return
    if _extract_solicitations_running()[0]:
        return
    if not AutoScrapeQueueItem.objects.exists():
        return

    claimed_phase = None
    try:
        with transaction.atomic():
            schedule = ScrapingSchedule.objects.select_for_update().first()
            if not schedule or not schedule.enabled:
                return
            if _extract_solicitations_running()[0]:
                return
            item = (
                AutoScrapeQueueItem.objects.order_by("created_at")
                .select_for_update()
                .first()
            )
            if not item:
                return
            claimed_phase = item.phase
            item.delete()
    except Exception as e:
        logger.error(f"Auto-scrape queue: post-completion claim failed: {e}")
        logger.error(traceback.format_exc())
        return

    schedule.refresh_from_db()
    today = datetime.now().strftime("%m-%d-%Y")
    logger.info(
        f"Auto-scrape queue: starting deferred phase '{claimed_phase}' for {today} after previous run finished."
    )
    result = _auto_scrape_start_subprocess(
        schedule, claimed_phase, today, log_label="(from queue)"
    )
    if result.get("status") == "error":
        _auto_scrape_requeue_phase_after_failed_start(claimed_phase)


def update_scraping_status_from_progress():
    """
    Check the scraping progress file and update ScrapingSchedule model accordingly.
    This should be called periodically to sync the status.
    """
    try:
        schedule = ScrapingSchedule.objects.first()
        if not schedule:
            return
        
        # Use dynamic path based on BASE_DIR
        logs_dir = os.path.join(settings.BASE_DIR, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        progress_file = os.path.join(logs_dir, 'scrape_progress.json')
        
        if os.path.exists(progress_file):
            try:
                with open(progress_file, 'r') as f:
                    progress_data = json.load(f)
                
                status = progress_data.get('status', '')
                prev_status = schedule.last_run_status

                # Only update if status changed
                if status == 'completed' and schedule.last_run_status != 'success':
                    schedule.last_run = timezone.now()
                    schedule.last_run_status = 'success'
                    schedule.save(update_fields=['last_run', 'last_run_status'])
                    logger.info("Scraping schedule updated: completed successfully")
                    if prev_status == 'running':
                        _auto_scrape_try_start_after_runner_finished()
                elif status == 'failed' and schedule.last_run_status != 'failed':
                    schedule.last_run = timezone.now()
                    schedule.last_run_status = 'failed'
                    schedule.save(update_fields=['last_run', 'last_run_status'])
                    logger.info("Scraping schedule updated: failed")
                    if prev_status == 'running':
                        _auto_scrape_try_start_after_runner_finished()
                elif status == 'stopped' and schedule.last_run_status != 'stopped':
                    schedule.last_run = timezone.now()
                    schedule.last_run_status = 'stopped'
                    schedule.save(update_fields=['last_run', 'last_run_status'])
                    logger.info("Scraping schedule updated: stopped by administrator")
                    if prev_status == 'running':
                        _auto_scrape_try_start_after_runner_finished()
                elif status == 'running' and schedule.last_run_status != 'running':
                    schedule.last_run_status = 'running'
                    schedule.save(update_fields=['last_run_status'])
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error reading progress file: {e}")
        else:
            # Progress file doesn't exist - check if process is still running
            try:
                check_process = subprocess.run(
                    ["pgrep", "-f", "extractSolicitations.py"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5
                )
                if check_process.returncode != 0:
                    # Process not running and no progress file - might have completed
                    # Only update if we were in 'running' status
                    if schedule.last_run_status == 'running':
                        # Check if we have a recent log file to determine success/failure
                        # For now, mark as success if we were running and process is gone
                        # (This is a best-effort approach)
                        schedule.last_run = timezone.now()
                        schedule.last_run_status = 'success'
                        schedule.save(update_fields=['last_run', 'last_run_status'])
                        logger.info("Scraping process completed (no progress file found)")
                        _auto_scrape_try_start_after_runner_finished()
            except (FileNotFoundError, subprocess.SubprocessError):
                pass
                
    except Exception as e:
        logger.error(f"Error updating scraping status from progress: {e}")


def check_scraping_schedule():
    """
    Check if it's time to run scraping based on schedule settings.
    This function runs periodically (every hour) and checks if scraping should run.
    Uses strict 0-2 minute window after scheduled time.
    """
    try:
        schedule = ScrapingSchedule.objects.first()
        if not schedule or not schedule.enabled:
            return False

        # Use local time (project time zone) for all schedule checks
        now_utc = timezone.now()
        now = timezone.localtime(now_utc)
        current_time = now.time()
        current_weekday = now.weekday()  # 0=Monday, 6=Sunday

        # Map weekday to our day choices
        # Python weekday: 0=Monday, 1=Tuesday, ..., 6=Sunday
        # Our choices: daily, monday, tuesday, ..., sunday
        weekday_mapping = {
            0: ScrapingSchedule.MONDAY,
            1: ScrapingSchedule.TUESDAY,
            2: ScrapingSchedule.WEDNESDAY,
            3: ScrapingSchedule.THURSDAY,
            4: ScrapingSchedule.FRIDAY,
            5: ScrapingSchedule.SATURDAY,
            6: ScrapingSchedule.SUNDAY,
        }

        current_day = weekday_mapping.get(current_weekday)

        # Check if today matches the schedule day
        if schedule.scrape_day != ScrapingSchedule.DAILY and schedule.scrape_day != current_day:
            return False

        # Check if current time matches scheduled time (within a small forward window)
        scheduled_time = schedule.scrape_time
        current_minutes = current_time.hour * 60 + current_time.minute
        scheduled_minutes = scheduled_time.hour * 60 + scheduled_time.minute
        # Positive value means "minutes after scheduled time"
        minute_delta = current_minutes - scheduled_minutes

        # Check if schedule was updated today (admin might have changed the time)
        schedule_updated_today = False
        if schedule.last_updated:
            schedule_updated_date = schedule.last_updated.date()
            if schedule_updated_date == now.date():
                schedule_updated_today = True

        # Check if we already ran today (successfully, failed, or stopped) - prevent retries
        already_ran_today = False
        ran_successfully_today = False
        ran_failed_today = False
        ran_stopped_today = False

        if schedule.last_run:
            last_run_date = schedule.last_run.date()
            if last_run_date == now.date():
                already_ran_today = True
                if schedule.last_run_status == 'success':
                    ran_successfully_today = True
                elif schedule.last_run_status == 'failed':
                    ran_failed_today = True
                elif schedule.last_run_status == 'stopped':
                    ran_stopped_today = True

        logger.info(
            f"Scraping schedule check: scheduled={scheduled_time}, current={current_time}, "
            f"delta={minute_delta} min, day={schedule.scrape_day}, enabled={schedule.enabled}, "
            f"already_ran_today={already_ran_today}, ran_successfully={ran_successfully_today}, "
            f"ran_failed={ran_failed_today}, ran_stopped={ran_stopped_today}, "
            f"schedule_updated_today={schedule_updated_today}"
        )

        # If a run was stopped or failed today, do NOT retry in the same schedule,
        # unless the schedule was updated today (admin changed the time).
        if (ran_stopped_today or ran_failed_today) and not schedule_updated_today:
            logger.info(
                f"Scraping was { 'stopped' if ran_stopped_today else 'failed' } today at {schedule.last_run}. "
                f"Schedule not updated today, so not retrying automatically."
            )
            return False

        # Special case: If schedule was updated today, allow run at new scheduled time
        # (strictly within the same 0-2 minute window after the new time)
        if schedule_updated_today:
            # If we're within 0-2 minutes after the new scheduled time, allow it
            if 0 <= minute_delta <= 2:
                logger.info(
                    f"Schedule was updated today to {scheduled_time}. Current time is within strict 0-2 minute window. "
                    "Allowing run (even if already ran today - admin may have cleared data)."
                )
                return True
            # If the new scheduled time hasn't arrived yet, wait for it
            else:
                logger.debug(f"Schedule was updated today to {scheduled_time}, but current time ({current_time}) hasn't reached it yet. Waiting.")
                return False

        # Allow a small 0-2 minute window for execution (since we check every 2 minutes)
        if 0 <= minute_delta <= 2:
            if ran_successfully_today:
                # Already ran successfully today, skip
                logger.info(f"Scraping already ran successfully today at {schedule.last_run}. Skipping.")
                return False

            # It's time to scrape!
            logger.info(f"Scraping schedule matched! Time to run scraping (scheduled: {scheduled_time}, current: {current_time}, delta: {minute_delta} min)")
            return True

        # Outside the strict 0-2 minute window and not covered by schedule-updated logic
        logger.debug(
            f"Time delta {minute_delta} minutes is outside allowed window "
            f"(scheduled: {scheduled_time}, current: {current_time})"
        )
        return False

    except Exception as e:
        logger.error(f"Error checking scraping schedule: {e}")
        return False


def auto_scrape_solicitations():
    """
    Automatically trigger scraping process for today's date.
    This function is called by django-q2 scheduler.

    If a phase is due while extractSolicitations.py is already running, the phase is
    enqueued (AutoScrapeQueueItem, FIFO by created_at). When the runner goes idle,
    the next queued phase starts on the next tick or immediately when progress
    reports completion. Concurrent workers coordinate via ScrapingSchedule row lock.
    """
    update_scraping_status_from_progress()

    schedule = ScrapingSchedule.objects.first()
    if not schedule or not schedule.enabled:
        logger.info("Automatic scraping is disabled. Skipping.")
        return {"status": "skipped", "reason": "disabled"}

    try:
        BASE_DIR = settings.BASE_DIR
        script_path = os.path.join(BASE_DIR, "extractSolicitations.py")
        if not os.path.exists(script_path):
            logger.error(f"Scraping script not found at {script_path}")
            return {"status": "error", "message": f"Script not found at {script_path}"}

        today = datetime.now().strftime("%m-%d-%Y")
        today_date = datetime.now().date()

        scheduled_phase, skip_payload = _compute_auto_scrape_phase(schedule, today_date)
        running, alive_pids = _extract_solicitations_running()

        if running:
            if scheduled_phase:
                _auto_scrape_enqueue_phase(scheduled_phase)
                return {
                    "status": "queued",
                    "phase": scheduled_phase,
                    "reason": "already_running",
                    "pids": alive_pids,
                }
            return {"status": "skipped", "reason": "already_running", "pids": alive_pids}

        claimed_phase = None
        from_queue = False
        try:
            with transaction.atomic():
                schedule_locked = ScrapingSchedule.objects.select_for_update().first()
                if not schedule_locked or not schedule_locked.enabled:
                    return {"status": "skipped", "reason": "disabled"}
                running2, pids2 = _extract_solicitations_running()
                if running2:
                    if scheduled_phase:
                        _auto_scrape_enqueue_phase(scheduled_phase)
                    return {
                        "status": "queued",
                        "reason": "already_running_race",
                        "pids": pids2,
                    }

                item = (
                    AutoScrapeQueueItem.objects.order_by("created_at")
                    .select_for_update()
                    .first()
                )
                if item:
                    claimed_phase = item.phase
                    from_queue = True
                    item.delete()
        except Exception as e:
            logger.error(f"Auto-scrape: DB claim transaction failed: {e}")
            logger.error(traceback.format_exc())
            if scheduled_phase:
                _auto_scrape_enqueue_phase(scheduled_phase)
            return {"status": "error", "message": str(e)}

        schedule.refresh_from_db()
        phase_to_start = claimed_phase or scheduled_phase

        if phase_to_start is None:
            if skip_payload:
                return skip_payload
            return {"status": "skipped", "reason": "no_work"}

        today_run = datetime.now().strftime("%m-%d-%Y")
        log_label = "(from queue)" if from_queue else ""
        result = _auto_scrape_start_subprocess(
            schedule, phase_to_start, today_run, log_label=log_label
        )
        if result.get("status") == "error" and from_queue and claimed_phase:
            _auto_scrape_requeue_phase_after_failed_start(claimed_phase)
        return result

    except Exception as e:
        error_msg = f"Error starting automatic scraping: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())

        if schedule:
            schedule.last_run = timezone.now()
            schedule.last_run_status = "failed"
            schedule.save(update_fields=["last_run", "last_run_status"])

        return {"status": "error", "message": error_msg}


def update_scraping_schedule():
    """
    Update the django-q scraping schedule based on ScrapingSchedule model.
    Called when admin updates settings via UI.
    """
    try:
        from django_q.models import Schedule
        
        schedule = ScrapingSchedule.objects.first()
        if not schedule:
            return {"success": False, "message": "No scraping schedule configuration found"}
        
        # Delete existing scraping schedule
        Schedule.objects.filter(name='auto_scrape_solicitations').delete()
        
        # Only create schedule if enabled
        if schedule.enabled:
            # Use MINUTES schedule type (runs every 2 minutes to check if it's time to scrape)
            scrape_schedule = Schedule.objects.create(
                name='auto_scrape_solicitations',
                func='solicitations.tasks.auto_scrape_solicitations',
                hook=None,
                args=None,
                kwargs=None,
                schedule_type=Schedule.MINUTES,
                minutes=2,  # Check every 2 minutes
                repeats=-1,
                cron=None,
                task=None,
                cluster=None,
                intended_date_kwarg=None
            )
            day_display = dict(ScrapingSchedule.DAY_CHOICES).get(schedule.scrape_day, schedule.scrape_day)
            time_display = schedule.scrape_time.strftime("%I:%M %p")
            logger.info(f"Updated auto-scrape schedule: {scrape_schedule.name} (checks every 2 minutes, runs on {day_display} at {time_display})")
            return {"success": True, "message": f"Scraping schedule updated: {day_display} at {time_display}"}
        else:
            logger.info("Auto-scraping is disabled. Schedule removed.")
            return {"success": True, "message": "Auto-scraping is disabled. Schedule removed."}
            
    except Exception as e:
        logger.error(f"Error updating scraping schedule: {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": f"Error updating schedule: {str(e)}"}


def _create_schedules():
    """The actual logic for creating schedules"""
    from django_q.models import Schedule

    # Delete existing schedules
    Schedule.objects.filter(name='check_scheduled_emails').delete()
    Schedule.objects.filter(name='create_solicitation_email_statuses').delete()
    Schedule.objects.filter(name='cleanup_stale_user_locks').delete()
    Schedule.objects.filter(name='check_rfq_auto_fetch').delete()
    Schedule.objects.filter(name='fetch_replied_rfqs_30min').delete()
    Schedule.objects.filter(name='auto_scrape_solicitations').delete()

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

    # Auto-fetch RFQ replies schedule (runs every 2 minutes to check window)
    try:
        rfq_fetch_schedule = Schedule.objects.create(
            name='check_rfq_auto_fetch',
            func='solicitations.tasks.check_rfq_auto_fetch',
            hook=None,
            args=None,
            kwargs=None,
            schedule_type=Schedule.MINUTES,
            minutes=1,
            repeats=-1,
            cron=None,
            task=None,
            cluster=None,
            intended_date_kwarg=None
        )
        logger.info(
            f"Created RFQ auto-fetch schedule: {rfq_fetch_schedule.name} (runs every {rfq_fetch_schedule.minutes} minutes)")
    except Exception as e:
        logger.error(f"Error creating RFQ auto-fetch schedule: {e}")
        raise

    # Fetch replied RFQs every 30 minutes (30-minute window)
    try:
        fetch_30min_schedule = Schedule.objects.create(
            name='fetch_replied_rfqs_30min',
            func='solicitations.tasks.fetch_replied_rfqs_30min',
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
        logger.info(
            f"Created 30-minute RFQ reply fetch schedule: {fetch_30min_schedule.name} (runs every {fetch_30min_schedule.minutes} minutes)")
    except Exception as e:
        logger.error(f"Error creating 30-minute RFQ reply fetch schedule: {e}")
        raise

    # Auto-scrape solicitations schedule - read from ScrapingSchedule model
    # Uses MINUTES schedule (checks every 2 minutes) instead of CRON to avoid croniter dependency
    try:
        schedule = ScrapingSchedule.objects.first()
        if schedule and schedule.enabled:
            scrape_schedule = Schedule.objects.create(
                name='auto_scrape_solicitations',
                func='solicitations.tasks.auto_scrape_solicitations',
                hook=None,
                args=None,
                kwargs=None,
                schedule_type=Schedule.MINUTES,
                minutes=2,  # Check every 2 minutes
                repeats=-1,
                cron=None,
                task=None,
                cluster=None,
                intended_date_kwarg=None
            )
            day_display = dict(ScrapingSchedule.DAY_CHOICES).get(schedule.scrape_day, schedule.scrape_day)
            time_display = schedule.scrape_time.strftime("%I:%M %p")
            logger.info(
                f"Created auto-scrape schedule: {scrape_schedule.name} (checks every 2 minutes, runs on {day_display} at {time_display})")
        else:
            logger.info("Auto-scraping is disabled in ScrapingSchedule model. Skipping schedule creation.")
    except Exception as e:
        logger.error(f"Error creating auto-scrape schedule: {e}")
        # Don't raise - allow other schedules to be created even if scraping schedule fails

    logger.info("Django-Q2 scheduled tasks created successfully")


def setup_email_schedule_threaded():
    """Thread-safe version that can be called from async contexts"""
    import threading

    def _setup_in_thread():
        try:
            with transaction.atomic():
                _create_schedules()
                logger.info(
                    "Django-Q2 scheduled tasks created successfully in thread")
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
            existing_lock = lock_manager.check_user_lock_status(
                user_id, check_type)
            if existing_lock:
                conflicting_locks.append(
                    f"{check_type} (TTL: {existing_lock['ttl_seconds']}s)")

        if conflicting_locks:
            raise Exception(
                f"User {user_id} has conflicting locks: {', '.join(conflicting_locks)}")

        # Acquire lock
        lock_id = lock_manager.acquire_user_lock(user_id, lock_type, timeout)

        if not lock_id:
            raise Exception(
                f"Failed to acquire {lock_type} lock for user {user_id}")

        logger.info(
            f"LOCK ACQUIRED: User {user_id}, Type {lock_type}, Lock ID: {lock_id}")

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
                released = lock_manager.release_user_lock(
                    user_id, lock_type, lock_id)
                if released:
                    release_successful = True
                    elapsed = time.time() - start_time
                    logger.info(
                        f"LOCK RELEASED: User {user_id}, Type {lock_type}, Duration: {elapsed:.2f}s")
                else:
                    logger.warning(
                        f"Normal release failed for user {user_id}, trying force release")
            except Exception as e:
                logger.error(f"Normal release error for user {user_id}: {e}")

        if release_attempted and not release_successful:
            # Method 2: Force release without lock_id verification
            try:
                released = lock_manager.release_user_lock(user_id, lock_type)
                if released:
                    release_successful = True
                    logger.warning(
                        f"FORCE RELEASED: User {user_id}, Type {lock_type}")
                else:
                    logger.error(
                        f"Force release also failed for user {user_id}")
            except Exception as e:
                logger.error(f"Force release error for user {user_id}: {e}")

        if release_attempted and not release_successful:
            # Method 3: Direct Redis deletion (last resort)
            try:
                deleted = lock_manager.redis.delete(lock_key)
                if deleted:
                    release_successful = True
                    logger.warning(
                        f"DIRECT REDIS DELETE: User {user_id}, Type {lock_type}")
                else:
                    logger.error(
                        f"Direct Redis delete failed for user {user_id}")
            except Exception as e:
                logger.error(
                    f"Direct Redis delete error for user {user_id}: {e}")

        if not release_successful and release_attempted:
            logger.critical(
                f"FAILED TO RELEASE LOCK: User {user_id}, Type {lock_type}, Key: {lock_key}")
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
        # Match tasksorg.py: lookback days (configurable so autosend can include older scraped data if needed)
        lookback_days = getattr(settings, 'AUTOSEND_DAYS_LOOKBACK', 14)
        cutoff_date = today - timedelta(days=lookback_days)

        logger.info(
            f"Autosend filtering for user {user.username}, scope: {send_scope}")

        # EXACT REPLICATION of tasksorg.py / manual view filtering
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

        # Same exclusions and order as tasksorg.py
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

        # Same date format as tasksorg (MM-DD-YYYY); DB-agnostic via Django __regex (MySQL REGEXP / PostgreSQL ~)
        solicitations_qs = solicitations_qs.filter(
            return_by_date__regex=r'^[0-9]{1,2}-[0-9]{1,2}-[0-9]{4}$'
        )

        count_after_exclusions = solicitations_qs.count()
        logger.info(f"  After exclusions + scraped_date (cutoff {cutoff_date}, lookback {lookback_days}d): {count_after_exclusions}")

        # Apply send scope filtering (same as tasksorg)
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
        lock_id = lock_manager.acquire_user_lock(
            user_id, "automated", timeout=72000)

        if not lock_id:
            logger.info(
                f"SKIPPING: User {user_id} is already being processed (Redis lock exists)")
            return {"status": "skipped", "reason": "user_already_processing"}

        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.get(id=user_id)
        logger.info(
            f"AUTOMATED PROCESSING: Starting for user {user.username} (Lock ID: {lock_id}, Scope: {send_scope})")

        # Mark processing start
        EmailSettings.objects.filter(user=user).update(
            last_processed=timezone.now())

        # Use EXACT manual view filtering
        valid_solicitations = get_filtered_solicitations_for_autosend(
            user, send_scope)

        if not valid_solicitations:
            logger.info(
                f"No valid solicitations found for user {user.username}")
            return {"status": "completed", "message": "No valid solicitations"}

        logger.info(
            f"Found {len(valid_solicitations)} solicitations matching manual view filtering")

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
            logger.info(
                f"No pending solicitations to process for user {user.username}")
            return {"status": "completed", "message": "No pending solicitations"}

        logger.info(
            f"Will process {len(status_records)} solicitations for user {user.username}")

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
        total_batches = (len(all_solicitations_data) +
                         BATCH_SIZE - 1) // BATCH_SIZE
        success_count = 0
        failure_count = 0

        # Find script path
        script_path = find_script_path()
        if not script_path:
            try:
                SolicitationEmailStatus.objects.filter(
                    id__in=status_ids).update(email_status='failed')
                logger.error(
                    f"CLEANUP: Script not found, marked records as failed")
            except Exception as cleanup_error:
                logger.error(f"CLEANUP ERROR: {cleanup_error}")
            raise FileNotFoundError("Email script not found")

        # Process in batches
        for batch_num in range(total_batches):
            # Extend lock if needed
            lock_status = lock_manager.check_user_lock_status(
                user_id, "automated")
            if lock_status and lock_status['ttl_seconds'] < 900:
                lock_manager.extend_user_lock(user_id, "automated", 1800)

            start_idx = batch_num * BATCH_SIZE
            end_idx = start_idx + BATCH_SIZE
            batch_data = all_solicitations_data[start_idx:end_idx]

            logger.info(
                f"Processing AUTOMATED batch {batch_num + 1}/{total_batches} for user {user.username}")

            script_data = {
                "user_data": user_data,
                "mail_data": mail_data,
                "solicitation_ids": [sol['id'] for sol in batch_data],
                "auto_mode": True
            }

            json_data = json.dumps(script_data)
            # Windows command line limit ~32k; pass large payload via file to avoid WinError 206
            max_cmd_json_len = getattr(settings, 'RFQ_SCRIPT_MAX_JSON_CMDLEN', 12000)

            try:
                if len(json_data) > max_cmd_json_len:
                    with tempfile.NamedTemporaryFile(
                            mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
                        f.write(json_data)
                        temp_file_path = f.name
                    try:
                        result = execute_script_with_file(script_path, temp_file_path)
                    finally:
                        try:
                            os.unlink(temp_file_path)
                        except OSError:
                            pass
                else:
                    result = execute_script_with_json(script_path, json_data)
                logger.info(f"Script result: returncode={result.returncode}")

                if result.returncode == 0:
                    # Success
                    batch_status_ids = [status_mapping[sol['id']]
                                        for sol in batch_data]

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
                        logger.error(
                            f"Database error for batch {batch_num + 1}: {db_e}")
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
                    logger.error(
                        f"Batch {batch_num + 1} failed: Script returned {result.returncode}")

                    try:
                        with transaction.atomic():
                            batch_status_ids = [
                                status_mapping[sol['id']] for sol in batch_data]
                            SolicitationEmailStatus.objects.filter(
                                id__in=batch_status_ids
                            ).update(email_status='failed')
                    except Exception as update_e:
                        logger.error(
                            f"Error updating failed statuses: {update_e}")

            except Exception as e:
                failure_count += len(batch_data)
                logger.error(f"Error processing batch {batch_num + 1}: {e}")

                try:
                    with transaction.atomic():
                        batch_status_ids = [status_mapping[sol['id']]
                                            for sol in batch_data]
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
        logger.error(
            f"Error in process_user_solicitations for user {user_id}: {e}")

        # Clean up processing records
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.get(id=user_id)

            cleanup_count = SolicitationEmailStatus.objects.filter(
                user=user,
                email_status='processing'
            ).update(email_status='failed')

            logger.error(
                f"CLEANUP: Marked {cleanup_count} processing records as failed")
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
    # Log immediately when function is called (before lock acquisition)
    logger.info(
        f"=== PROCESS_MANUAL_RFQ_BATCH CALLED: user_id={user_id}, batch_size={len(batch_ids) if batch_ids else 0} ===")
    try:
        # Use context manager for guaranteed lock release
        with guaranteed_user_lock(user_id, "manual") as lock_info:
            logger.info(
                f"MANUAL PROCESSING: Starting for user {user_id} with {len(batch_ids)} RFQs")

            from django.contrib.auth import get_user_model
            User = get_user_model()

            # Get user
            try:
                user = User.objects.get(id=user_id)
                logger.info(
                    f"Processing for user: {user.username} (ID: {user_id})")
            except User.DoesNotExist:
                logger.error(f"User with ID {user_id} not found")
                return {"status": "error", "error": f"User {user_id} not found"}

            # Get solicitations
            solicitations = Solicitation.objects.filter(id__in=batch_ids)
            found_count = solicitations.count()

            if found_count != len(batch_ids):
                logger.warning(
                    f"Found {found_count} solicitations out of {len(batch_ids)} requested")

            # Get user data and mail data if not provided
            if not user_data:
                user_data = get_user_data(user)
            if not mail_data:
                mail_data = get_mail_template_data(user)

            # Bulk update status to processing
            solicitation_ids_found = list(
                solicitations.values_list('id', flat=True))

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
                SolicitationEmailStatus.objects.filter(
                    id__in=status_updates).update(email_status='processing')

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
                    logger.error(
                        f"CLEANUP: Marked {len(batch_ids)} solicitations as failed (script not found)")
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

                logger.info(
                    f"Running script for user {user_id} with {len(batch_ids)} solicitations")

                result = execute_script_with_file(script_path, temp_file_path)

                logger.info(
                    f"Script execution completed for user {user_id}: returncode={result.returncode}")
                
                # Log script output for debugging
                if result.stdout:
                    logger.info(f"Script stdout for user {user_id}:\n{result.stdout}")
                if result.stderr:
                    logger.warning(f"Script stderr for user {user_id}:\n{result.stderr}")

                if result.returncode == 0:
                    logger.info(
                        f"SUCCESS: Script succeeded for user {user_id}")
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
                    # Include both stdout and stderr for debugging
                    error_details = []
                    if result.stdout:
                        error_details.append(f"STDOUT: {result.stdout}")
                    if result.stderr:
                        error_details.append(f"STDERR: {result.stderr}")
                    error_msg = "\n".join(error_details) if error_details else f"Script returned code {result.returncode}"
                    logger.error(
                        f"ERROR: Script failed for user {user_id}: {error_msg}")
                    logger.error(
                        f"Script return code: {result.returncode}")

                    try:
                        cleanup_count = SolicitationEmailStatus.objects.filter(
                            solicitation_id__in=batch_ids,
                            user=user,
                            email_status='processing'
                        ).update(email_status='failed')

                        logger.error(
                            f"CLEANUP: Marked {cleanup_count} processing records as failed due to script failure")
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
            logger.error(
                f"ERROR: Error processing MANUAL RFQ batch for user {user_id}: {e}")
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

                logger.error(
                    f"TASK CLEANUP: Marked {cleanup_count} processing records as failed due to task exception")
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
            logger.info(
                f"SKIPPING: User {user_id} has active locks: {lock_info}")
            return {
                "status": "skipped",
                "error": f"User has active processing operations: {[l['type'] for l in lock_info]}",
                "user_id": user_id,
                "reason": "user_has_locks",
                "active_locks": lock_info
            }

        # Try to acquire user-specific lock for large batch processing
        lock_id = lock_manager.acquire_user_lock(
            user_id, "large_batch", timeout=72000)  # 12 hours

        if not lock_id:
            logger.info(
                f"SKIPPING: User {user_id} failed to acquire large batch lock")
            return {
                "status": "skipped",
                "error": "Failed to acquire large batch processing lock",
                "user_id": user_id,
                "reason": "lock_acquisition_failed"
            }

        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.get(id=user_id)

        logger.info(
            f"LARGE BATCH PROCESSING: Starting for user {user.username} with {len(selected_ids)} RFQs (Lock ID: {lock_id})")
        logger.info(
            f"PARALLEL PROCESSING: Multiple users can process simultaneously")

        # Get mail template and user data once
        mail_data = get_mail_template_data(user)
        user_data = get_user_data(user)

        # Process all at once to maintain CAGE consolidation (script handles filtering)
        if len(selected_ids) <= batch_size:
            # Process all at once - script maintains CAGE consolidation
            logger.info(
                f"Processing {len(selected_ids)} RFQs in single batch - script will handle CAGE consolidation")

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

            logger.info(
                f"QUEUED: Queued single large batch for user {user_id}: Task {task_id}")

            # FIXED: Release the large_batch lock immediately after queuing
            # since the queued task will handle its own manual lock
            if lock_id:
                released = lock_manager.release_user_lock(
                    user_id, "large_batch", lock_id)
                logger.info(
                    f"Released large_batch lock after queuing single batch: {released}")
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
            logger.info(
                f"Very large batch ({len(selected_ids)} RFQs) - grouping by CAGE to maintain consolidation")

            # Get solicitations and group by CAGE
            from collections import defaultdict
            solicitations = Solicitation.objects.filter(
                id__in=selected_ids).values('id', 'cage')

            cage_groups = defaultdict(list)
            for sol in solicitations:
                cage_groups[sol['cage']].append(sol['id'])

            logger.info(
                f"Grouped {len(selected_ids)} RFQs into {len(cage_groups)} CAGE groups")

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

                logger.info(
                    f"QUEUED: Queued CAGE {cage_code} batch with {len(cage_rfq_ids)} RFQs: Task {task_id}")

            logger.info(
                f"TOTAL: Total queued tasks for user {user_id}: {len(task_ids)}")

            # FIXED: Release the large_batch lock after queuing all tasks
            if lock_id:
                released = lock_manager.release_user_lock(
                    user_id, "large_batch", lock_id)
                logger.info(
                    f"Released large_batch lock after queuing {len(task_ids)} CAGE batches: {released}")
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
        logger.error(
            f"ERROR: Error queuing large MANUAL RFQ batch for user {user_id}: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}
    finally:
        # FIXED: Only release if lock wasn't already released above
        if lock_id:
            released = lock_manager.release_user_lock(
                user_id, "large_batch", lock_id)
            logger.info(
                f"Released large_batch lock in finally block for user {user_id}: {released}")
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

        logger.info(
            '--------------------------------------------------------------------------')
        logger.info(
            f"Current server time (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(
            f"Current local time ({settings.TIME_ZONE}): {now_local.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Current day: {current_day}")
        logger.info(f"Current time (local): {current_time}")
        logger.info(
            "ENHANCED FILTERING: Using manual process filters for autosend")

        # Check if any email settings exist at all
        total_settings = EmailSettings.objects.count()
        auto_enabled = EmailSettings.objects.filter(auto_send=True).count()

        logger.info(
            f'Found {total_settings} email settings, {auto_enabled} with auto-send enabled')

        # Create a 4-minute buffer window (2 minutes before and 2 minutes after) in LOCAL TIME
        two_min_ago = (datetime.combine(
            date.today(), current_time) - timedelta(minutes=2)).time()
        two_min_ahead = (datetime.combine(
            date.today(), current_time) + timedelta(minutes=2)).time()

        logger.info(
            f"Time window ({settings.TIME_ZONE}): {two_min_ago.strftime('%H:%M:%S')} to {two_min_ahead.strftime('%H:%M:%S')}")

        # Get all users with auto-send enabled and matching day (including daily option)
        auto_send_settings = EmailSettings.objects.filter(
            auto_send=True
        ).filter(
            Q(send_day=current_day) | Q(send_day='daily')
        ).select_related('user')

        logger.info(
            f"Users with auto-send enabled for today ({current_day}) or daily: {auto_send_settings.count()}")

        for setting in auto_send_settings:
            logger.info(f"Checking user: {setting.user.username}")
            logger.info(f"  Send day: {setting.send_day}")
            logger.info(f"  Send scope: {setting.send_scope}")

            # Log enabled time intervals
            enabled_times = setting.get_enabled_times()
            if enabled_times:
                times_str = ', '.join([t.strftime('%H:%M:%S')
                                      for t in enabled_times])
                logger.info(f"  Enabled times: {times_str}")
            else:
                logger.info(f"  No time intervals enabled - skipping user")
                continue

            # FIXED: Check locks before processing
            user_has_any_lock = False
            user_lock_info = None
            for lock_type in ['automated', 'manual', 'large_batch']:
                lock_status = lock_manager.check_user_lock_status(
                    setting.user.id, lock_type)
                if lock_status:
                    user_has_any_lock = True
                    user_lock_info = f"{lock_type} lock (TTL: {lock_status['ttl_seconds']}s)"
                    break

            if user_has_any_lock:
                logger.info(
                    f"  Skipping user {setting.user.username} - Redis lock exists: {user_lock_info}")
                continue

            # Check for existing tasks first
            existing_tasks = Task.objects.filter(
                func='solicitations.tasks.process_user_solicitations',
                args=str(setting.user.id),
                stopped__isnull=True
            ).count()

            if existing_tasks > 0:
                logger.info(
                    f"  Skipping user {setting.user.username} - {existing_tasks} tasks already exist")
                continue

            # Check cooldown period - 60 minutes
            if setting.last_processed:
                # Convert last_processed to local timezone for comparison
                last_processed_local = setting.last_processed.astimezone(
                    local_tz)
                time_since_last = now_local - last_processed_local
                if time_since_last < timedelta(minutes=60):
                    logger.info(
                        f"  Skipping user {setting.user.username} - processed recently at {last_processed_local}")
                    continue

            # NEW: Use the model's is_time_to_send method for multiple time intervals
            time_window_match = setting.is_time_to_send(current_time)
            logger.info(f"  Time window match? {time_window_match}")

            if time_window_match:
                # Check if there are any pending solicitations for this user
                has_pending = check_pending_solicitations(setting.user)

                if not has_pending:
                    logger.info(
                        f"  Skipping user {setting.user.username} - no pending solicitations")
                    continue

                # PREVIEW: Show what filtering will find
                try:
                    preview_solicitations = get_filtered_solicitations_for_autosend(
                        setting.user, setting.send_scope)
                    logger.info(
                        f"  PREVIEW: Enhanced filtering found {len(preview_solicitations)} valid solicitations")
                except Exception as preview_e:
                    logger.warning(f"  PREVIEW ERROR: {preview_e}")

                # Mark the last processed time BEFORE scheduling the task
                EmailSettings.objects.filter(user=setting.user).update(
                    last_processed=timezone.now())

                # Schedule a new task for this user with send scope information
                # NOTE: This uses the ENHANCED process_user_solicitations function
                task_id = async_task(
                    'solicitations.tasks.process_user_solicitations',
                    setting.user.id,
                    setting.send_scope,  # Pass the send scope to the task
                    task_name=f"AUTOMATED ENHANCED Process emails for {setting.user.username} ({setting.send_scope})",
                    sync=False
                )
                logger.info(
                    f"  Scheduled ENHANCED email processing task with ID: {task_id} (scope: {setting.send_scope})")

                # ALSO: Schedule RFQ reply extraction (auto-fetch) for this user
                try:
                    async_task(
                        'solicitations.tasks.extract_user_rfq_replies',
                        setting.user.id,
                        1,  # days_back: roughly last day of replies
                        task_name=f"AUTOMATED RFQ reply extraction for {setting.user.username}",
                    )
                    logger.info(
                        f"  Scheduled RFQ reply auto-fetch for user {setting.user.username}"
                    )
                except Exception as fetch_e:
                    logger.warning(
                        f"  Failed to schedule RFQ reply auto-fetch for user {setting.user.username}: {fetch_e}"
                    )
            else:
                logger.info(
                    f"  Not processing user {setting.user.username} - outside time window")

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
                    logger.info(
                        f"Active lock: User {user_id}, Type: {lock_type}, TTL: {lock_info['ttl_minutes']} min")

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
                                    logger.warning(
                                        f"SAFETY NET: Cleaned stale lock: User {user_id}, Type {lock_type}, Age: {age_minutes:.1f} min")

                    except (ValueError, IndexError):
                        deleted = redis_client.delete(key)
                        if deleted:
                            cleaned_count += 1
                            logger.warning(
                                f"SAFETY NET: Cleaned unparseable lock: {key}")

            except Exception as e:
                logger.error(f"Error processing lock key {key}: {e}")

        if cleaned_count > 0:
            logger.warning(
                f"SAFETY NET: Cleaned {cleaned_count} stale locks (investigate why locks weren't released immediately)")
        else:
            logger.info(
                "SAFETY NET: No stale locks found (locks being released properly)")

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
        logger.warning(
            f"FORCE RELEASING lock for user {user_id}, type: {lock_type}")

        # Check if lock exists first
        lock_status = lock_manager.check_user_lock_status(user_id, lock_type)
        if not lock_status:
            logger.info(f"No lock found for user {user_id}, type: {lock_type}")
            return False

        logger.warning(f"Found lock: {lock_status}")

        # Force release without lock_id verification
        released = lock_manager.release_user_lock(
            user_id, lock_type, lock_id=None)

        if released:
            logger.warning(
                f"Successfully force-released lock for user {user_id}")
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
            lock_status = lock_manager.check_user_lock_status(
                user_id, lock_type)
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
        logger.error(
            f"Error getting processing status for user {user_id}: {e}")
        return None

# ===============================
# EXISTING FUNCTIONS (UNCHANGED)
# ===============================


def find_script_path():
    """Helper to find the script path - uses dynamic BASE_DIR"""
    BASE_DIR = settings.BASE_DIR
    possible_paths = [
        os.path.join(BASE_DIR, 'infoExtractorSendRfq.py'),
        # Legacy paths for backward compatibility
        "/home/gilgalrfq/DLA-NEW/infoExtractorSendRfq.py",
    ]
    for path in possible_paths:
        try:
            if os.path.exists(path):
                logger.info(f"Found script at: {path}")
                return path
            else:
                logger.warning(f"Script not found at: {path} (exists check returned False)")
        except Exception as e:
            logger.error(f"Error checking path {path}: {e}")
    logger.error(f"Script not found in any of the possible paths: {possible_paths}")
    # Log current working directory for debugging
    try:
        logger.error(f"Current working directory: {os.getcwd()}")
    except:
        pass
    return None


def execute_script_with_json(script_path, json_data):
    """Helper to execute the external script with JSON data as argument"""
    BASE_DIR = settings.BASE_DIR
    import platform
    if platform.system() == 'Windows':
        venv_python = os.path.join(BASE_DIR, 'venv', 'Scripts', 'python.exe')
    else:
        venv_python = os.path.join(BASE_DIR, 'venv', 'bin', 'python')
    return subprocess.run(
        [venv_python, script_path, json_data],
        capture_output=True,
        text=True,
        timeout=72000  # 12 hour timeout
    )


def execute_script_with_file(script_path, file_path):
    """Helper to execute the external script with file argument"""
    BASE_DIR = settings.BASE_DIR
    import platform
    if platform.system() == 'Windows':
        venv_python = os.path.join(BASE_DIR, 'venv', 'Scripts', 'python.exe')
    else:
        venv_python = os.path.join(BASE_DIR, 'venv', 'bin', 'python')
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
                # heading = resale notice line (same as email template configuration)
                "heading": mail_template.heading or DEFAULT_RESALE_NOTICE_TEXT,
                "body": mail_template.body or "I hope this message finds you well...",
            }
    except Exception as e:
        logger.error(f"Error retrieving mail template: {str(e)}")

    return {
        "salutation": "Dear Mr/Ms",
        "heading": DEFAULT_RESALE_NOTICE_TEXT,
        "body": "I hope this message finds you well..."
    }


def check_pending_solicitations(user):
    """
    Check if there are any pending solicitations for this user.
    First checks existing SolicitationEmailStatus records.
    If none exist, checks actual solicitations using get_filtered_solicitations_for_autosend.
    This handles cases where create_solicitation_email_statuses hasn't run yet.
    """
    # First check existing status records
    pending_count = SolicitationEmailStatus.objects.filter(
        user=user,
        email_sent=False,
        processing_attempts__lt=3
    ).count()

    if pending_count > 0:
        return True

    # If no status records exist, check actual solicitations
    # This handles the case where create_solicitation_email_statuses hasn't run yet
    # or new solicitations were scraped after the last run
    try:
        from solicitations.models import EmailSettings
        setting = EmailSettings.objects.get(user=user, auto_send=True)
        actual_solicitations = get_filtered_solicitations_for_autosend(user, setting.send_scope)
        has_solicitations = len(actual_solicitations) > 0
        
        if has_solicitations:
            logger.info(
                f"check_pending_solicitations: No status records found, but {len(actual_solicitations)} "
                f"actual solicitations exist for user {user.username} - returning True"
            )
        
        return has_solicitations
    except EmailSettings.DoesNotExist:
        # User doesn't have auto-send enabled, so no pending solicitations
        return False
    except Exception as e:
        logger.error(f"Error checking actual solicitations for user {user.username}: {e}")
        # On error, return False to be safe
        return False


def create_solicitation_email_statuses():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    today = datetime.today().strftime("%m-%d-%Y")

    # Get all solicitations that are valid (have cage codes and haven't passed return date)
    valid_solicitations = []
    all_solicitations = Solicitation.objects.all().exclude(
        Q(cage='-') | Q(cage='N/A')).filter(return_by_date__gte=today)

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
                        return_date = datetime.strptime(
                            sol.return_by_date, fmt).date()
                        break
                    except ValueError:
                        continue
                if not return_date:
                    continue

                if return_date < current_date:
                    continue
        except Exception as e:
            logger.error(
                f"Error processing date for solicitation {sol.id}: {str(e)}")
            continue

        valid_solicitations.append(sol)

    logger.info(f"Found {len(valid_solicitations)} valid solicitations")

    # Get users with email settings enabled
    users_with_email = User.objects.filter(email_settings__auto_send=True)

    logger.info(
        f"Found {users_with_email.count()} users with auto-send enabled")

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

            logger.warning(
                f"EMERGENCY CLEANUP: Reset {stale_count} stale processing records to pending")

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


# ===============================
# RFQ REPLY EXTRACTION TASKS
# ===============================

def extract_user_rfq_replies(user_id, days_back=30):
    """
    Background task to extract RFQ replies from user's email inbox

    Args:
        user_id: CustomUser ID
        days_back: How many days back to search (default: 30)

    Returns:
        Dict with extraction results
    """
    logger.info(f"Starting RFQ reply extraction for user ID: {user_id}")

    if extract_rfq_replies_for_user is None:
        logger.error("extractRfqReplies module not available")
        return {'success': False, 'error': 'Extraction module not available'}

    try:
        result = extract_rfq_replies_for_user(user_id, days_back=days_back)

        if result.get('success'):
            logger.info(
                f"RFQ reply extraction completed for user {user_id}: "
                f"{result.get('extracted', 0)} extracted, "
                f"{result.get('errors', 0)} errors"
            )
        else:
            logger.error(
                f"RFQ reply extraction failed for user {user_id}: "
                f"{result.get('error', 'Unknown error')}"
            )

        return result

    except Exception as e:
        logger.error(
            f"Error in RFQ reply extraction task for user {user_id}: {e}")
        logger.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}


def extract_user_rfq_replies_for_date(user_id, target_date_str):
    """
    Background task to extract RFQ replies for a specific calendar date
    for a single user.

    Args:
        user_id: CustomUser ID
        target_date_str: Date string in YYYY-MM-DD format
    """
    logger.info(
        f"Starting RFQ reply extraction for user ID {user_id} on date {target_date_str}"
    )

    if extract_rfq_replies_for_user is None:
        logger.error("extractRfqReplies module not available")
        return {'success': False, 'error': 'Extraction module not available'}

    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except Exception as e:
        logger.error(f"Invalid target_date_str '{target_date_str}': {e}")
        return {'success': False, 'error': 'Invalid date format'}

    try:
        result = extract_rfq_replies_for_user(
            user_id, days_back=None, start_date=target_date, end_date=target_date
        )

        success = bool(result.get('success'))
        extracted = int(result.get('extracted', 0) or 0)
        errors = int(result.get('errors', 0) or 0)
        total_processed = int(result.get('total', 0) or 0)

        if success:
            logger.info(
                f"RFQ reply extraction for user {user_id} on {target_date}: "
                f"{extracted} extracted, {errors} errors, total {total_processed}"
            )
        else:
            logger.error(
                f"RFQ reply extraction failed for user {user_id} on {target_date}: "
                f"{result.get('error', 'Unknown error')}"
            )

        # Update per-user auto-fetch status for this date-specific run
        try:
            status_obj, _ = RfqAutoFetchStatus.objects.get_or_create(
                user_id=user_id
            )
            status_obj.status = (
                RfqAutoFetchStatus.STATUS_COMPLETED
                if success
                else RfqAutoFetchStatus.STATUS_FAILED
            )
            if not status_obj.started_at:
                status_obj.started_at = timezone.now()
            status_obj.finished_at = timezone.now()
            status_obj.emails_scanned = total_processed
            status_obj.rfqs_created = extracted
            status_obj.errors_count = errors
            if success:
                status_obj.message = (
                    f"Fetch by date {target_date}: {extracted} RFQs, "
                    f"{errors} errors, {total_processed} emails processed."
                )
            else:
                status_obj.message = (
                    f"Fetch by date {target_date} failed: "
                    f"{result.get('error', 'Unknown error')}"
                )
            status_obj.save()
        except Exception as e:
            logger.error(
                f"Failed to update RFQ auto-fetch status (by date) for user {user_id}: {e}"
            )

        return result

    except Exception as e:
        logger.error(
            f"Error in RFQ reply extraction (by date) for user {user_id}: {e}"
        )
        logger.error(traceback.format_exc())
        # Mark status as failed if possible
        try:
            status_obj, _ = RfqAutoFetchStatus.objects.get_or_create(
                user_id=user_id
            )
            status_obj.status = RfqAutoFetchStatus.STATUS_FAILED
            if not status_obj.started_at:
                status_obj.started_at = timezone.now()
            status_obj.finished_at = timezone.now()
            status_obj.message = (
                f"Fetch by date {target_date} failed with exception: {e}"
            )
            status_obj.errors_count = status_obj.errors_count + 1
            status_obj.save()
        except Exception as se:
            logger.error(
                f"Failed to update RFQ auto-fetch status (by date) after exception for user {user_id}: {se}"
            )
        return {'success': False, 'error': str(e)}


def extract_all_users_rfq_replies(days_back=30):
    """
    Background task to extract RFQ replies for all active users

    Args:
        days_back: How many days back to search (default: 30)

    Returns:
        Dict with extraction results for all users
    """
    logger.info(f"Starting RFQ reply extraction for all users")

    if extract_rfq_replies_for_all_users is None:
        logger.error("extractRfqReplies module not available")
        return {'success': False, 'error': 'Extraction module not available'}

    try:
        results = extract_rfq_replies_for_all_users(days_back=days_back)

        total_extracted = sum(r.get('extracted', 0) for r in results.values())
        total_errors = sum(r.get('errors', 0) for r in results.values())

        logger.info(
            f"RFQ reply extraction completed for all users: "
            f"{total_extracted} total extracted, "
            f"{total_errors} total errors"
        )

        return results

    except Exception as e:
        logger.error(f"Error in RFQ reply extraction task for all users: {e}")
        logger.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}


def rfq_fetch_completion_hook(task):
    """
    Hook called when RFQ fetch task completes (success or failure).
    CRITICAL: Releases the Redis lock that was acquired during scheduling.
    
    The lock is kept active during the entire task execution to prevent
    duplicate instances. This hook ensures it's released when done.
    """
    try:
        # Extract user_id from task args
        if hasattr(task, 'args') and task.args:
            args_str = str(task.args)
            # Parse user_id from args string - handle various formats
            import re
            # Try multiple patterns: (123, or [123, or "123" or '123'
            match = re.search(r'[(\[](\d+)[,)]', args_str) or re.search(r'["\'](\d+)["\']', args_str)
            if match:
                user_id = int(match.group(1))
                
                # Always try to release the lock (it should exist)
                released = lock_manager.release_user_lock(
                    user_id, "rfq_auto_fetch")
                
                if released:
                    logger.info(
                        f"COMPLETION HOOK: Released lock for user {user_id} (task completed)")
                else:
                    # Lock might have already expired or been released
                    lock_status = lock_manager.check_user_lock_status(
                        user_id, "rfq_auto_fetch")
                    if lock_status:
                        logger.warning(
                            f"COMPLETION HOOK: Lock still exists for user {user_id} "
                            f"(TTL: {lock_status['ttl_seconds']}s) - force deleting")
                        # Force delete
                        lock_key = f"user_processing_lock:{user_id}:rfq_auto_fetch"
                        lock_manager.redis.delete(lock_key)
                        logger.warning(f"COMPLETION HOOK: Force-deleted lock for user {user_id}")
                    else:
                        logger.debug(
                            f"COMPLETION HOOK: Lock already released for user {user_id} (normal)")
            else:
                logger.warning(
                    f"COMPLETION HOOK: Could not parse user_id from args: {args_str}")

    except Exception as e:
        logger.error(f"COMPLETION HOOK: Error processing task completion: {e}")
        logger.error(traceback.format_exc())


def check_rfq_auto_fetch():
    """
    Check RFQ auto-fetch settings and schedule extraction tasks.

    TRIPLE-LAYER PROTECTION:
    1. Redis lock (fast, prevents scheduler race conditions)
    2. Database lock (prevents database-level race conditions)  
    3. Task deduplication (prevents queue duplicates)
    """
    try:
        now = timezone.now()
        local_tz = pytz.timezone(settings.TIME_ZONE)
        now_local = now.astimezone(local_tz)
        current_time = now_local.time()
        current_day = now_local.strftime("%A").lower()

        # CRITICAL: 30-second window (was 2 minutes - too wide!)
        fifteen_sec_ago = (datetime.combine(
            date.today(), current_time) - timedelta(seconds=15)).time()
        fifteen_sec_ahead = (datetime.combine(
            date.today(), current_time) + timedelta(seconds=15)).time()

        logger.info("=== RFQ AUTO-FETCH CHECK ===")
        logger.info(
            f"Time: {now_local.strftime('%Y-%m-%d %H:%M:%S')} ({current_day})")
        logger.info(
            f"Window: {fifteen_sec_ago.strftime('%H:%M:%S')} - {fifteen_sec_ahead.strftime('%H:%M:%S')}")

        settings_qs = RfqAutoFetchSettings.objects.filter(
            enabled=True
        ).filter(
            Q(day=RfqAutoFetchSettings.DAILY) | Q(day=current_day)
        ).select_related('user')

        logger.info(f"Candidates: {settings_qs.count()} users")

        for cfg in settings_qs:
            fetch_time = cfg.fetch_time
            user_id = cfg.user.id
            username = cfg.user.username

            # Quick time check
            in_window = False
            if fifteen_sec_ahead < fifteen_sec_ago:  # Midnight wrap
                in_window = fetch_time <= fifteen_sec_ahead or fetch_time >= fifteen_sec_ago
            else:
                in_window = fifteen_sec_ago <= fetch_time <= fifteen_sec_ahead

            if not in_window:
                continue

            logger.info(f"[{username}] IN WINDOW - acquiring lock...")

            # ==========================================
            # LAYER 1: REDIS LOCK (Immediate protection)
            # ==========================================
            lock_id = lock_manager.acquire_user_lock(
                user_id,
                "rfq_auto_fetch",
                timeout=7200  # 2 hours
            )

            if not lock_id:
                logger.warning(f"[{username}] REDIS LOCK EXISTS - skipping")
                continue

            try:
                logger.info(f"[{username}] Redis lock acquired: {lock_id}")

                # ==========================================
                # LAYER 2: DATABASE LOCK + COOLDOWN CHECK
                # ==========================================
                skip_reason = None

                with transaction.atomic():
                    # Database-level row lock
                    cfg = RfqAutoFetchSettings.objects.select_for_update().get(id=cfg.id)

                    # Aggressive cooldown: 50 minutes minimum
                    if cfg.last_fetched:
                        last_fetched_local = cfg.last_fetched.astimezone(
                            local_tz)
                        time_since = now_local - last_fetched_local
                        minutes_ago = int(time_since.total_seconds() / 60)

                        if time_since.total_seconds() < 3000:  # 50 minutes
                            skip_reason = f"cooldown active ({minutes_ago} min ago, need 50 min)"

                if skip_reason:
                    logger.warning(f"[{username}] {skip_reason}")
                    continue

                # ==========================================
                # LAYER 3: TASK DEDUPLICATION CHECK
                # ==========================================
                from django_q.models import OrmQ

                # Check ALL task states comprehensively
                user_id_patterns = [
                    f'"{user_id}"',
                    f"'{user_id}'",
                    f'({user_id},',
                    f'[{user_id},',
                    str(user_id)
                ]

                # Build complex query
                task_q = Q()
                for pattern in user_id_patterns:
                    task_q |= Q(args__contains=pattern)

                # Running tasks (not stopped)
                running = Task.objects.filter(
                    func='solicitations.tasks.extract_user_rfq_replies',
                    stopped__isnull=True
                ).filter(task_q).count()

                # Recently started (last 15 minutes - catching stragglers)
                recent = Task.objects.filter(
                    func='solicitations.tasks.extract_user_rfq_replies',
                    started__gte=timezone.now() - timedelta(minutes=15)
                ).filter(task_q).count()

                # Queued tasks
                queued = OrmQ.objects.filter(
                    func='solicitations.tasks.extract_user_rfq_replies'
                ).filter(task_q).count()

                if running > 0 or recent > 0 or queued > 0:
                    logger.warning(
                        f"[{username}] TASKS EXIST - "
                        f"running:{running}, recent:{recent}, queued:{queued}"
                    )
                    continue

                logger.info(f"[{username}] No existing tasks found")

                # ==========================================
                # COMMIT POINT: Update timestamp FIRST
                # ==========================================
                with transaction.atomic():
                    cfg.refresh_from_db()
                    cfg.last_fetched = timezone.now()
                    cfg.save(update_fields=['last_fetched'])

                logger.info(f"[{username}] Updated last_fetched timestamp")

                # ==========================================
                # SCHEDULE TASK
                # ==========================================
                task_timestamp = now_local.strftime(
                    '%Y%m%d_%H%M%S_%f')  # Include microseconds

                task_id = async_task(
                    'solicitations.tasks.extract_user_rfq_replies',
                    user_id,
                    cfg.days_back,
                    task_name=f"RFQ_AF_{username}_{task_timestamp}",
                    group=f'RFQ_AutoFetch_U{user_id}',
                    timeout=7200,
                    hook='solicitations.tasks.rfq_fetch_completion_hook',  # Add completion hook
                )

                logger.info(
                    f"[{username}] SCHEDULED - Task:{task_id}, Days:{cfg.days_back}"
                )

                # Brief sleep to ensure task is committed to queue
                time.sleep(0.1)
                
                # CRITICAL: DO NOT release lock here!
                # The lock must stay active until the task completes.
                # The completion hook (rfq_fetch_completion_hook) will release it.
                # Lock timeout (2 hours) acts as safety net if task crashes.
                logger.info(
                    f"[{username}] Lock {lock_id} will be released by completion hook when task finishes"
                )
                # Set lock_id to None so finally block doesn't release it
                lock_id = None

            except Exception as e:
                logger.error(f"[{username}] ERROR: {e}")
                logger.error(traceback.format_exc())

                # Rollback last_fetched on failure
                try:
                    with transaction.atomic():
                        cfg = RfqAutoFetchSettings.objects.select_for_update().get(id=cfg.id)
                        if cfg.last_fetched and (timezone.now() - cfg.last_fetched).total_seconds() < 15:
                            cfg.last_fetched = None
                            cfg.save(update_fields=['last_fetched'])
                            logger.info(
                                f"[{username}] Rolled back last_fetched")
                except Exception as rb_err:
                    logger.error(f"[{username}] Rollback error: {rb_err}")

            finally:
                # Only release lock if scheduling failed (lock_id still set)
                # If scheduling succeeded, lock stays active for task duration
                if lock_id:
                    released = lock_manager.release_user_lock(
                        user_id, "rfq_auto_fetch", lock_id)
                    if released:
                        logger.warning(f"[{username}] Lock released due to scheduling failure")
                    else:
                        logger.error(f"[{username}] Lock release FAILED")

        logger.info("=== AUTO-FETCH CHECK COMPLETE ===")

    except Exception as e:
        logger.error(f"Fatal error in check_rfq_auto_fetch: {e}")
        logger.error(traceback.format_exc())


def fetch_replied_rfqs_30min():
    """
    Fetch replied RFQ emails every 30 minutes.
    Fetches emails from the previous 30-minute window.
    For example, if this runs at 7:20 AM, it fetches emails from 6:50 AM to 7:20 AM.
    
    This task runs for all users with enabled auto-fetch settings.
    """
    try:
        now = timezone.now()
        
        # Calculate 30 minutes ago
        thirty_min_ago = now - timedelta(minutes=30)
        
        logger.info("=== 30-MINUTE RFQ REPLY FETCH ===")
        logger.info(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Fetching emails from: {thirty_min_ago.strftime('%Y-%m-%d %H:%M:%S')} to {now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Get all users with enabled auto-fetch settings
        users_with_auto_fetch = RfqAutoFetchSettings.objects.filter(
            enabled=True
        ).select_related('user')
        
        logger.info(f"Found {users_with_auto_fetch.count()} users with enabled auto-fetch")
        
        if extract_rfq_replies_for_user is None:
            logger.error("extractRfqReplies module not available")
            return {'success': False, 'error': 'Extraction module not available'}
        
        total_extracted = 0
        total_errors = 0
        
        for cfg in users_with_auto_fetch:
            user = cfg.user
            user_id = user.id
            username = user.username
            lock_id = None
            
            try:
                # ==========================================
                # LAYER 1: REDIS LOCK (Prevent concurrent execution)
                # ==========================================
                lock_id = lock_manager.acquire_user_lock(
                    user_id,
                    "rfq_30min_fetch",
                    timeout=1800  # 30 minutes (enough for email extraction)
                )
                
                if not lock_id:
                    logger.info(f"[{username}] Lock exists - skipping (already being processed by another instance)")
                    continue
                
                logger.info(f"[{username}] Lock acquired: {lock_id} - processing user")
                
                # Extract RFQ replies for the 30-minute window
                # Convert datetime to date objects for the extractor
                # The extractor will handle the date range, but since we're on the same day
                # most of the time, we'll use the date of 30 minutes ago and current date
                start_date = thirty_min_ago.date()
                end_date = now.date()
                
                # If both dates are the same, we still pass both to ensure we get that day's emails
                result = extract_rfq_replies_for_user(
                    user_id,
                    days_back=None,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if result.get('success'):
                    extracted = result.get('extracted', 0)
                    errors = result.get('errors', 0)
                    total_extracted += extracted
                    total_errors += errors
                    
                    logger.info(
                        f"[{username}] Extraction complete: {extracted} extracted, {errors} errors"
                    )
                else:
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(
                        f"[{username}] Extraction failed: {error_msg}"
                    )
                    total_errors += 1
                    
            except Exception as e:
                logger.error(f"[{username}] Error processing user: {e}")
                logger.error(traceback.format_exc())
                total_errors += 1
            finally:
                # Always release the lock, even if processing fails
                if lock_id:
                    released = lock_manager.release_user_lock(
                        user_id, "rfq_30min_fetch", lock_id
                    )
                    if released:
                        logger.info(f"[{username}] Lock released successfully")
                    else:
                        logger.warning(f"[{username}] Failed to release lock (may have expired)")
        
        logger.info("=== 30-MINUTE RFQ REPLY FETCH COMPLETE ===")
        logger.info(f"Total extracted: {total_extracted}, Total errors: {total_errors}")
        
        return {
            'success': True,
            'extracted': total_extracted,
            'errors': total_errors,
            'users_processed': users_with_auto_fetch.count()
        }
        
    except Exception as e:
        logger.error(f"Fatal error in fetch_replied_rfqs_30min: {e}")
        logger.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}
