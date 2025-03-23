from django.utils import timezone
import datetime
from django.db.models import Q
from django_q.models import OrmQ
from django.conf import settings
from .models import EmailSettings, Solicitation, OEM, OEMUser, MailTemplate
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
                pending_count = Solicitation.objects.all().count()
                
                print(f"  Total solicitations in system: {pending_count}")
                
                if pending_count == 0:
                    print(f"  Skipping user {setting.user.username} - no pending solicitations")
                    continue
                
                # Check if this user is already being processed
                print("Current OrmQ payload values:")
                print(list(OrmQ.objects.values_list("payload", flat=True)[:5]))
                
                existing_tasks = OrmQ.objects.filter(
                    payload__contains=f'"func": "solicitations.tasks.process_user_solicitations"'
                ).filter(
                    payload__contains=f'"{setting.user.id}"'  # Check if user ID is in the payload
                )

                if not existing_tasks.exists():
                    task_id = async_task(
                        'solicitations.tasks.process_user_solicitations', 
                        setting.user.id,
                        task_name=f"Process emails for {setting.user.username}"
                    )
                    print(f"  Scheduled email processing task with ID: {task_id}")
                else:
                    print(f"  Skipping user {setting.user.username} - task already in queue")
            else:
                print(f"  Not processing user {setting.user.username} - outside time window")
        
        print("COMPLETED SCHEDULED EMAIL CHECK")
        print("------------------------")
        
    except Exception as e:
        print(f"Error in check_scheduled_emails: {str(e)}")
        import traceback
        print(traceback.format_exc())

def process_user_solicitations(user_id):
    """
    Process all pending solicitations for a user.
    This is run as an async task by Django-Q.
    """
    print(f"Starting to process solicitations for user ID: {user_id}")
    
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    try:
        # Get the user from the database
        user = User.objects.get(id=user_id)
        print(f"Found user: {user.username}")
        
        pending_solicitations = Solicitation.objects.all()
        
        print(f"Found {pending_solicitations.count()} pending solicitations")
        
        if not pending_solicitations.exists():
            print("No pending solicitations found")
            return
        
        # Prepare data for processing
        solicitations_data = []
        for solicitation in pending_solicitations:
            # Make sure to handle cases where any field might be null
            sol_data = {
                'cage': solicitation.cage or '',
                'nomenclature': solicitation.nomenclature or '',
                'quantity': str(solicitation.quantity) if solicitation.quantity else '1',  # Ensure quantity is a string
                'return_by_date': str(solicitation.return_by_date) if solicitation.return_by_date else '',
                'NSN': solicitation.NSN or '',
                'id': solicitation.id
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
                    
                    # Update solicitation status (if needed)
                    for solicitation_id in [item['id'] for item in solicitations_data]:
                        sol = Solicitation.objects.get(id=solicitation_id)
                        # Add logic to update solicitation status here
                    
                    print(f"Successfully processed {len(solicitations_data)} solicitations")
                else:
                    print("Script execution failed")
                    print(f"Return code: {result.returncode}")
                    print(f"Error output: {result.stderr}")
                    print(f"Standard output: {result.stdout}")
                
            except Exception as e:
                print(f"Error running script: {str(e)}")
                import traceback
                print(traceback.format_exc())
            
    except User.DoesNotExist:
        print(f"User with ID {user_id} does not exist")
    except Exception as e:
        print(f"Error in process_user_solicitations: {str(e)}")
        import traceback
        print(traceback.format_exc())

def get_user_data(user):
    """
    Get user data needed for email processing.
    Using logic similar to your fetch_mail_preview view.
    """
    company_name = getattr(user, 'companyName', "Your Company Name")
    address = getattr(user, 'address', "Your Address")
    logo_url = user.logo.url if hasattr(user, 'logo') and user.logo else None
    phone = getattr(user, 'phone', "Not Provided")
    
    return {
        'username': user.username,
        'email': user.email,
        'phone': phone,
        'address': address,
        'companyName': company_name,
        'logo': logo_url,
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