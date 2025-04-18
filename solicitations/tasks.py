from django.utils import timezone
from datetime import datetime, timedelta, date
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

def find_script_path():
    """Helper to find the script path"""
    possible_paths = [
        os.path.join(settings.BASE_DIR, "infoExtractorSendRfq.py"),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

def execute_script(script_path, json_data):
    """Helper to execute the external script"""
    venv_python = os.path.join(settings.BASE_DIR, "venv", "Scripts", "python.exe")
    return subprocess.run(
        [venv_python, script_path, json_data],
        capture_output=True,
        text=True
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
        print(f"Error retrieving mail template: {str(e)}")
    
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
    """Create email status records for solicitations that don't have them"""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    today = datetime.today().strftime("%m-%d-%Y")
    
    # Get all solicitations that are valid (have cage codes and haven't passed return date)
    valid_solicitations = []
    all_solicitations = Solicitation.objects.all().exclude(Q(cage='-') | Q(cage='N/A')).filter(return_by_date__gte=today)
    
    current_date = timezone.now().date()
    print(f"Current date: {current_date}")
    print(f"Found {all_solicitations.count()} total solicitations")
    
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
            print(f"Error processing date for solicitation {sol.id}: {str(e)}")
            continue
        
        valid_solicitations.append(sol)
    
    print(f"Found {len(valid_solicitations)} valid solicitations")
    
    # Get users with email settings enabled
    users_with_email = User.objects.filter(email_settings__auto_send=True)
    
    print(f"Found {users_with_email.count()} users with auto-send enabled")
    
    # Create status records for each valid solicitation for each user
    count = 0
    for user in users_with_email:
        print(f"Processing user: {user.username}")
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
                
    print(f"Created {count} new email status records")

def process_user_solicitations(user_id):
    """
    Process all pending solicitations for a user in batches.
    """
    lock_key = f"processing_solicitations_user_{user_id}"
    lock_timeout = 3600  # 60 minutes (increased from 30)
    
    # Immediate return if already processing
    if cache.get(lock_key):
        print(f"User {user_id} already being processed (lock exists), skipping")
        return
        
    try:
        # Acquire lock
        if not cache.add(lock_key, "true", timeout=lock_timeout):
            print(f"User {user_id} already being processed (lock acquisition failed), skipping")
            return
            
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # Get the user from the database
        user = User.objects.get(id=user_id)
        print(f"Starting processing for user: {user.username}")
        
        # Mark processing start in EmailSettings IMMEDIATELY
        EmailSettings.objects.filter(user=user).update(last_processed=timezone.now())
        
        # Get pending solicitations in a single query
        pending_statuses = SolicitationEmailStatus.objects.select_related('solicitation').filter(
            user=user,
            email_sent=False,
            processing_attempts__lt=3
        )
        
        if not pending_statuses.exists():
            print("No pending solicitations found")
            return
        
        print(f"Found {pending_statuses.count()} pending solicitations for user {user.username}")
        
        # Mark as processing in bulk
        pending_statuses.update(
            email_status='processing',
            processing_attempts=F('processing_attempts') + 1
        )
        
        # Prepare all data
        all_solicitations_data = []
        status_mapping = {}
        
        for status in pending_statuses:
            solicitation = status.solicitation
            # Skip invalid solicitations
            if not solicitation.cage or solicitation.cage.strip() == '-':
                print(f"Skipping solicitation {solicitation.id} due to empty or dash cage code: '{solicitation.cage}'")
                continue
                
            # Date validation
            try:
                return_date = None
                if solicitation.return_by_date:
                    if isinstance(solicitation.return_by_date, str):
                        # Try multiple date formats
                        for fmt in ('%m-%d-%Y', '%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d'):
                            try:
                                return_date = datetime.strptime(solicitation.return_by_date, fmt).date()
                                break
                            except ValueError:
                                continue
                        if not return_date:
                            raise ValueError(f"Unrecognized date format: {solicitation.return_by_date}")
                    else:
                        return_date = solicitation.return_by_date
                        
                    if return_date < timezone.now().date():
                        print(f"Skipping solicitation {solicitation.id} due to passed return date: {solicitation.return_by_date}")
                        continue
            except Exception as e:
                print(f"Skipping solicitation {solicitation.id} due to date error: {str(e)}")
                continue
            
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
            status_mapping[solicitation.id] = status.id
        
        if not all_solicitations_data:
            print("No valid solicitations to process after validation")
            return
            
        # Get user data and mail template data once
        user_data = get_user_data(user)
        mail_data = get_mail_template_data(user)
        
        # Process in batches
        BATCH_SIZE = 10
        total_batches = (len(all_solicitations_data) + BATCH_SIZE - 1) // BATCH_SIZE
        success_count = 0
        failure_count = 0
        
        # Find script path once
        script_path = find_script_path()
        if not script_path:
            raise FileNotFoundError("Selenium script not found")
        
        for batch_num in range(total_batches):
            start_idx = batch_num * BATCH_SIZE
            end_idx = start_idx + BATCH_SIZE
            batch_data = all_solicitations_data[start_idx:end_idx]
            
            print(f"\nProcessing batch {batch_num + 1}/{total_batches}")
            
            # Prepare the data for this batch (outside transaction)
            script_data = {
                "user_data": user_data,
                "mail_data": mail_data,
                "solicitations": batch_data,
                "auto_mode": True
            }
            
            json_data = json.dumps(script_data)
            
            try:
                # Execute script (outside transaction)
                print(f"Executing script for batch {batch_num + 1}")
                result = execute_script(script_path, json_data)
                
                print(f"Script execution result: returncode={result.returncode}")
                if len(result.stderr) > 0:
                    print(f"Script stderr: {result.stderr[:500]}...")  # Print first 500 chars of stderr
                
                # Process the results
                if result.returncode == 0:
                    # Success - update database in a transaction
                    status_ids = [status_mapping[sol['id']] for sol in batch_data]
                    print(f"Script succeeded. Updating {len(status_ids)} status records to 'sent'")
                    
                    try:
                        # Update in separate transaction
                        with transaction.atomic():
                            # Update statuses for successful batch
                            updated = SolicitationEmailStatus.objects.filter(
                                id__in=status_ids
                            ).update(
                                email_sent=True,
                                email_sent_at=timezone.now(),
                                email_status='sent'
                            )
                            print(f"Successfully updated {updated} of {len(status_ids)} status records")
                        
                        # Count as success if database updated
                        success_count += len(batch_data)
                        print(f"Batch {batch_num + 1} succeeded")
                    except Exception as db_e:
                        # Database error
                        print(f"Error updating database for batch {batch_num + 1}: {str(db_e)}")
                        failure_count += len(batch_data)
                else:
                    # Script failed
                    failure_count += len(batch_data)
                    print(f"Batch {batch_num + 1} failed: Script returned non-zero exit code")
                    
                    # Update status to 'failed' to prevent endless retries
                    try:
                        with transaction.atomic():
                            SolicitationEmailStatus.objects.filter(
                                id__in=[status_mapping[sol['id']] for sol in batch_data]
                            ).update(
                                email_status='failed'
                            )
                    except Exception as update_e:
                        print(f"Error updating statuses to 'failed': {str(update_e)}")
                        
            except Exception as e:
                failure_count += len(batch_data)
                print(f"Error processing batch {batch_num + 1}: {str(e)}")
                print(traceback.format_exc())
        
        print(f"\nProcessing complete. Results:")
        print(f"Total solicitations: {len(all_solicitations_data)}")
        print(f"Successfully processed: {success_count}")
        print(f"Failed: {failure_count}")
            
    except User.DoesNotExist:
        print(f"User with ID {user_id} does not exist")
    except Exception as e:
        print(f"Error in process_user_solicitations: {str(e)}")
        print(traceback.format_exc())
    finally:
        cache.delete(lock_key)
        print(f"Released lock for user {user_id}")

def check_scheduled_emails():
    """
    Task to check and process scheduled emails.
    This function is scheduled to run every 2 minutes via Django-Q.
    """
    try:
        now = timezone.now()
        current_day = now.strftime("%A").lower()
        current_time = now.time()
        
        print('--------------------------------------------------------------------------')
        print(f"Current server time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Current time object: {current_time}")
        print(f"Current day: {current_day}")
        
        # Check if any email settings exist at all
        total_settings = EmailSettings.objects.count()
        auto_enabled = EmailSettings.objects.filter(auto_send=True).count()

        print(f'Found {total_settings} email settings, {auto_enabled} with auto-send enabled')
        
        # Create a 4-minute buffer window (2 minutes before and 2 minutes after)
        two_min_ago = (datetime.combine(date.today(), current_time) - timedelta(minutes=2)).time()
        two_min_ahead = (datetime.combine(date.today(), current_time) + timedelta(minutes=2)).time()
        
        print(f"Time window: {two_min_ago.strftime('%H:%M:%S')} to {two_min_ahead.strftime('%H:%M:%S')}")
        
        # Get all users with auto-send enabled and matching day (including daily option)
        auto_send_settings = EmailSettings.objects.filter(
            auto_send=True
        ).filter(
            Q(send_day=current_day) | Q(send_day='daily')
        ).select_related('user')
        
        print(f"Users with auto-send enabled for today ({current_day}) or daily: {auto_send_settings.count()}")
        
        for setting in auto_send_settings:
            print(f"Checking user: {setting.user.username}")
            print(f"  Send day: {setting.send_day}")
            print(f"  Send time (as stored): {setting.send_time}")
            print(f"  Send time (formatted): {setting.send_time.strftime('%H:%M:%S')}")
            
            # Create a temporary lock key specifically for scheduling
            schedule_lock_key = f"scheduling_emails_user_{setting.user.id}"
            
            # Try to acquire this lock with a short timeout (5 minutes)
            if cache.get(schedule_lock_key):
                print(f"  Skipping user {setting.user.username} - scheduling lock exists")
                continue
                
            # Set lock before checking anything else
            cache.set(schedule_lock_key, "true", timeout=300)  # 5 minute lock
            
            try:
                # Check for existing tasks first
                existing_tasks = Task.objects.filter(
                    func='solicitations.tasks.process_user_solicitations',
                    args=str(setting.user.id),
                    stopped__isnull=True  # Either running or queued
                ).count()
                
                if existing_tasks > 0:
                    print(f"  Skipping user {setting.user.username} - {existing_tasks} tasks already exist")
                    continue
                    
                # Check cooldown period - increased from 30 to 60 minutes
                if setting.last_processed and (now - setting.last_processed) < timedelta(minutes=60):
                    print(f"  Skipping user {setting.user.username} - processed recently at {setting.last_processed}")
                    continue
                
                # For debugging
                print(f"  Comparing: {two_min_ago} <= {setting.send_time} <= {two_min_ahead}")
                
                # Time window logic
                if two_min_ahead < two_min_ago:  # Midnight boundary case
                    print("  Using midnight boundary logic")
                    time_window_match = (setting.send_time <= two_min_ahead or setting.send_time >= two_min_ago)
                else:  # Normal case
                    print("  Using normal time window logic")
                    time_window_match = (two_min_ago <= setting.send_time <= two_min_ahead)
                    
                print(f"  Time window match? {time_window_match}")
                
                if time_window_match:
                    # Check if there are any pending solicitations for this user
                    has_pending = check_pending_solicitations(setting.user)
                    
                    if not has_pending:
                        print(f"  Skipping user {setting.user.username} - no pending solicitations")
                        continue
                    
                    # Check if there's a lock for this user
                    if cache.get(f"processing_solicitations_user_{setting.user.id}"):
                        print(f"  Skipping user {setting.user.username} - processing lock exists")
                        continue
                    
                    # Mark the last processed time BEFORE scheduling the task
                    # This helps prevent duplicate scheduling
                    EmailSettings.objects.filter(user=setting.user).update(last_processed=timezone.now())
                    
                    # Schedule a new task for this user
                    task_id = async_task(
                        'solicitations.tasks.process_user_solicitations', 
                        setting.user.id,
                        task_name=f"Process emails for {setting.user.username}",
                        sync=False
                    )
                    print(f"  Scheduled email processing task with ID: {task_id}")
                else:
                    print(f"  Not processing user {setting.user.username} - outside time window")
            finally:
                # Release the scheduling lock when done with this user
                cache.delete(schedule_lock_key)
        
        print("COMPLETED SCHEDULED EMAIL CHECK")
        print("------------------------")
        
    except Exception as e:
        print(f"Error in check_scheduled_emails: {str(e)}")
        print(traceback.format_exc())

def setup_email_schedule():
    """Create the scheduled task to run every 2 minutes"""
    from django_q.models import Schedule
    
    try:
        # Delete existing schedules
        Schedule.objects.filter(name='check_scheduled_emails').delete()
        Schedule.objects.filter(name='create_solicitation_email_statuses').delete()
        
        # Create new schedules
        check_schedule = Schedule.objects.create(
            name='check_scheduled_emails',
            func='solicitations.tasks.check_scheduled_emails',
            schedule_type=Schedule.MINUTES,
            minutes=2,
            repeats=-1
        )
        
        # Run the status creation function once per hour
        status_schedule = Schedule.objects.create(
            name='create_solicitation_email_statuses',
            func='solicitations.tasks.create_solicitation_email_statuses',
            schedule_type=Schedule.MINUTES,
            minutes=60,  # Every hour
            repeats=-1
        )
        
        print(f"Scheduled tasks created: Check Emails (Next run: {check_schedule.next_run}), Create Statuses (Next run: {status_schedule.next_run})")
    except Exception as e:
        print(f"Error setting up schedule: {str(e)}")
        print(traceback.format_exc())