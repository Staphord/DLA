from django.utils import timezone
import datetime
from django.db.models import Q, F
from django_q.models import OrmQ, Task
from django.conf import settings
from django.core.cache import cache
from .models import EmailSettings, Solicitation, OEM, OEMUser, MailTemplate, SolicitationEmailStatus
import json
from django_q.tasks import async_task
import sys
import subprocess
import os

def check_scheduled_emails():
    """
    Task to check and process scheduled emails.
    This function is scheduled to run every 2 minutes via Django-Q.
    """
    try:
        now = timezone.now()
        current_day = now.strftime("%A").lower()  # e.g., 'monday', 'tuesday', etc.
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
        two_min_ago = (datetime.datetime.combine(datetime.date.today(), current_time) - 
                      datetime.timedelta(minutes=2)).time()
        two_min_ahead = (datetime.datetime.combine(datetime.date.today(), current_time) + 
                        datetime.timedelta(minutes=2)).time()
        
        print(f"Time window: {two_min_ago.strftime('%H:%M:%S')} to {two_min_ahead.strftime('%H:%M:%S')}")
        
        # Get all users with auto-send enabled and matching day (including daily option)
        auto_send_settings = EmailSettings.objects.filter(
            auto_send=True
        ).filter(
            # Either match the current day or have 'daily' selected
            Q(send_day=current_day) | Q(send_day='daily')
        )
        
        print(f"Users with auto-send enabled for today ({current_day}) or daily: {auto_send_settings.count()}")
        
        for setting in auto_send_settings:
            print(f"Checking user: {setting.user.username}")
            print(f"  Send day: {setting.send_day}")
            print(f"  Send time (as stored): {setting.send_time}")
            print(f"  Send time (formatted): {setting.send_time.strftime('%H:%M:%S')}")
            
            # Detailed time comparison
            print(f"  Comparing: {two_min_ago} <= {setting.send_time} <= {two_min_ahead}")
            print(f"  First condition: {two_min_ago <= setting.send_time}")
            print(f"  Second condition: {setting.send_time <= two_min_ahead}")
            
            if two_min_ahead < two_min_ago:  # Midnight boundary case
                print("  Using midnight boundary logic")
                if setting.send_time <= two_min_ahead or setting.send_time >= two_min_ago:
                    process_this_user = True
                else:
                    process_this_user = False
            else:  # Normal case
                print("  Using normal time window logic")
                if two_min_ago <= setting.send_time <= two_min_ahead:
                    process_this_user = True
                else:
                    process_this_user = False
                    
            print(f"  Process this user? {process_this_user}")
            
            if process_this_user:
                # Check if there are any pending solicitations for this user
                has_pending = check_pending_solicitations(setting.user)
                
                if not has_pending:
                    print(f"  Skipping user {setting.user.username} - no pending solicitations")
                    continue
                
                # Check if there's already a task running for this user
                if is_task_running(setting.user.id):
                    print(f"  Skipping user {setting.user.username} - task already running")
                    continue
                
                # Check if there's a lock for this user
                if cache.get(f"processing_solicitations_user_{setting.user.id}"):
                    print(f"  Skipping user {setting.user.username} - processing lock exists")
                    continue
                
                # Schedule a new task for this user
                task_id = async_task(
                    'solicitations.tasks.process_user_solicitations', 
                    setting.user.id,
                    task_name=f"Process emails for {setting.user.username}"
                )
                print(f"  Scheduled email processing task with ID: {task_id}")
            else:
                print(f"  Not processing user {setting.user.username} - outside time window")
        
        print("COMPLETED SCHEDULED EMAIL CHECK")
        print("------------------------")
        
    except Exception as e:
        print(f"Error in check_scheduled_emails: {str(e)}")
        import traceback
        print(traceback.format_exc())

def check_pending_solicitations(user):
    """
    Check if there are any pending solicitations for this user.
    """
    # Get all solicitations
    all_solicitations = Solicitation.objects.all()
    
    if not all_solicitations.exists():
        return False
    
    # Check if any solicitations need email sending for this user
    for sol in all_solicitations:
        status, created = SolicitationEmailStatus.objects.get_or_create(
            solicitation=sol,
            user=user,
            defaults={'email_status': 'pending', 'email_sent': False}
        )
        
        if status.email_sent == False and status.processing_attempts < 3:
            return True
    
    return False

def is_task_running(user_id):
    """
    Check if there's already a task running for this user.
    """
    # Check Task table for running tasks
    existing_tasks = Task.objects.filter(
        func='solicitations.tasks.process_user_solicitations',
        args=str(user_id),
        started__isnull=False,  # Task has started
        stopped__isnull=True    # Task hasn't stopped yet
    ).exists()
    
    if not existing_tasks:
        existing_in_queue = OrmQ.objects.filter(
            payload__contains=f'"func": "solicitations.tasks.process_user_solicitations"'
        ).filter(
            payload__contains=f'"{user_id}"'  # Separated into separate filter call
        ).exists()
        return existing_in_queue
    
    return existing_tasks

def process_user_solicitations(user_id):
    """
    Process all pending solicitations for a user.
    This is run as an async task by Django-Q.
    """
    # Create a lock key specific to this user
    lock_key = f"processing_solicitations_user_{user_id}"
    
    # Try to acquire the lock
    if not cache.add(lock_key, "true", timeout=1800):  # 30 minute lock
        print(f"User {user_id} already being processed, skipping")
        return
        
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # Get the user from the database
        user = User.objects.get(id=user_id)
        print(f"Found user: {user.username}")
        
        # Get all solicitations
        all_solicitations = Solicitation.objects.all()
        
        if not all_solicitations.exists():
            print("No solicitations in the system")
            return
        
        # Get or create email status records for each solicitation for this user
        pending_status_list = []
        for sol in all_solicitations:
            status, created = SolicitationEmailStatus.objects.get_or_create(
                solicitation=sol,
                user=user,
                defaults={'email_status': 'pending', 'email_sent': False}
            )
            
            # Only add solicitations that haven't been processed yet
            if status.email_sent == False and status.processing_attempts < 3:
                pending_status_list.append(status)
        
        print(f"Found {len(pending_status_list)} pending solicitations for user {user.username}")
        
        if not pending_status_list:
            print("No pending solicitations found")
            return
        
        # Mark these solicitations as being processed
        for status in pending_status_list:
            status.email_status = 'processing'
            status.processing_attempts += 1
            status.save()
            print(f"Marked solicitation {status.solicitation.id} as processing")
        
        # Prepare data for processing
        solicitations_data = []
        for status in pending_status_list:
            solicitation = status.solicitation
            # Make sure to handle cases where any field might be null
            sol_data = {
                'cage': solicitation.cage or '',
                'nomenclature': solicitation.nomenclature or '',
                'quantity': str(solicitation.quantity) if solicitation.quantity else '1',  # Ensure quantity is a string
                'return_by_date': str(solicitation.return_by_date) if solicitation.return_by_date else '',
                'NSN': solicitation.NSN or '',
                'id': solicitation.id,
                'part_number': solicitation.part_number or ''
            }
            solicitations_data.append(sol_data)
            print(f"Added solicitation ID {solicitation.id} to processing list")
        
        if solicitations_data:
            print(f"Processing {len(solicitations_data)} solicitations for user {user.username}")
            
            # Get user data
            user_data = get_user_data(user)
            print(f"User data: {user_data}")
            
            # Get mail template data - ensure it's a dictionary
            mail_data = get_mail_template_data(user)
            print(f"Mail template data: {mail_data}")
            
            # Prepare the data to pass to script
            script_data = {
                "user_data": user_data,
                "mail_data": mail_data,  # Ensure mail_data is structured as expected
                "solicitations": solicitations_data,
                "auto_mode": True
            }
            
            # Convert to JSON for passing to the script
            json_data = json.dumps(script_data)
            
            try:
                # Define possible paths to the script
                possible_paths = [
                    os.path.join(settings.BASE_DIR, "infoExtractorSendRfq.py"),
                ]
                
                # Find the script path
                script_path = None
                for path in possible_paths:
                    if os.path.exists(path):
                        script_path = path
                        print(f"Found script at: {script_path}")
                        print(f"Checking path: {path}")
                        print(f"Path exists: {os.path.exists(path)}")
                        break
                
                if not script_path:
                    print(f"Could not find the Selenium script. Checked paths: {possible_paths}")
                    print("Please specify the full path to your selenium_script.py file in the tasks.py file")
                    
                    # Mark all as failed
                    for status in pending_status_list:
                        status.email_status = 'failed'
                        status.save()
                        
                    return
                
                # Path to the virtual environment's Python executable
                venv_python = os.path.join(settings.BASE_DIR, "venv", "Scripts", "python.exe")
                
                # Call the script with the JSON data
                print("Executing Selenium script...")
                result = subprocess.run(
                    [venv_python, script_path, json_data],
                    capture_output=True,
                    text=True
                )
                
                # Check the result
                if result.returncode == 0:
                    print("Script executed successfully")
                    print(f"Script output: {result.stdout}")
                    
                    # Update solicitation status
                    for status in pending_status_list:
                        status.email_sent = True
                        status.email_sent_at = timezone.now()
                        status.email_status = 'sent'
                        status.save()
                        print(f"Marked solicitation {status.solicitation.id} as sent for user {user.username}")
                    
                    print(f"Successfully processed {len(solicitations_data)} solicitations")
                else:
                    print("Script execution failed")
                    print(f"Return code: {result.returncode}")
                    print(f"Error output: {result.stderr}")
                    print(f"Standard output: {result.stdout}")
                    
                    # Mark all as failed
                    for status in pending_status_list:
                        status.email_status = 'failed'
                        status.save()
                        print(f"Marked solicitation {status.solicitation.id} as failed for user {user.username}")
                
            except Exception as e:
                print(f"Error running script: {str(e)}")
                import traceback
                print(traceback.format_exc())
                
                # Mark all as failed
                for status in pending_status_list:
                    status.email_status = 'failed'
                    status.save()
            
    except User.DoesNotExist:
        print(f"User with ID {user_id} does not exist")
    except Exception as e:
        print(f"Error in process_user_solicitations: {str(e)}")
        import traceback
        print(traceback.format_exc())
    finally:
        # Always release the lock when done
        cache.delete(lock_key)

def get_user_data(user):
    """
    Get user data needed for email processing.
    Using logic similar to your fetch_mail_preview view.
    """
    company_name = getattr(user, 'companyName', "Your Company Name")
    address = getattr(user, 'address', "Your Address")
    logo_url = user.logo.url if hasattr(user, 'logo') and user.logo else None
    phone = getattr(user, 'phone', "Not Provided")
    website = getattr(user, 'website', "https://example.com")
    
    return {
        'username': user.username,
        'email': user.email,
        'phone': phone,
        'address': address,
        'companyName': company_name,
        'logo': logo_url,
        'website': website,
    }

def get_mail_template_data(user):
    """
    Get mail template data for the user.
    Using logic similar to your fetch_mail_preview view.
    """
    # This ensures we always return a dictionary with the expected structure
    try:
        mail_template = MailTemplate.objects.filter(userMail=user).first()
        
        if mail_template:
            return {
                "salutation": mail_template.salutation or "Dear Mr/Ms",
                "heading": mail_template.heading or "REQUEST FOR QUOTATION",
                "body": mail_template.body or "I hope this message finds you well. We are currently looking for the following item. Kindly provide your lowest possible price.",
            }
        else:
            # Default values if no template exists
            return {
                "salutation": "Dear Mr/Ms",
                "heading": "REQUEST FOR QUOTATION",
                "body": "I hope this message finds you well. We are currently looking for the following item. Kindly provide your lowest possible price."
            }
    except Exception as e:
        print(f"Error retrieving mail template: {str(e)}")
        # Fallback defaults
        return {
            "salutation": "Dear Mr/Ms",
            "heading": "REQUEST FOR QUOTATION",
            "body": "I hope this message finds you well. We are currently looking for the following item. Kindly provide your lowest possible price."
        }

# Set up the scheduled task
def setup_email_schedule():
    """
    Create the scheduled task to run every 2 minutes.
    """
    from django_q.models import Schedule
    
    try:
        # Remove any existing schedule first
        Schedule.objects.filter(name='check_scheduled_emails').delete()
        
        # Create a new schedule with the correct parameters
        schedule = Schedule.objects.create(
            name='check_scheduled_emails',
            func='solicitations.tasks.check_scheduled_emails',
            schedule_type=Schedule.MINUTES,
            minutes=2,  # Run every 2 minutes (numeric value)
            repeats=-1  # -1 means repeat forever
        )
        print(f"Email schedule has been set up to run every 2 minutes (Next run: {schedule.next_run})")
    except Exception as e:
        print(f"Error setting up email schedule: {str(e)}")
        import traceback
        print(traceback.format_exc())