import json
import MySQLdb  # Use mysqlclient (MySQLdb)
from MySQLdb.cursors import DictCursor  # Import DictCursor from MySQLdb.cursors
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import imaplib
import email
from email.mime.application import MIMEApplication  # For PDF attachments
import time
import os
import django
import sys
import argparse  # Add this for better argument parsing
from collections import defaultdict  # Import for grouping cage codes
from io import BytesIO  # For PDF generation
import re

import logging
logger = logging.getLogger('rfq')
import redis

def setup_database_logging(created_by_user, auto_mode):
    """Setup database logging alongside existing file logging"""
    try:
        task_id = f"{created_by_user.username}-{uuid4().hex[:8]}"
    except Exception as e:
        task_id = f"rfq-{uuid4().hex[:8]}"
    
    db_logger, script_session_id = initialize_database_logging(
        created_by_user, 
        task_id, 
        auto_mode
    )
    
    if db_logger:
        logger.info("Database logging initialized successfully")
        return db_logger, task_id, script_session_id
    else:
        logger.warning("Database logging failed, using file logging only")
        return None, task_id, None


# ===============================
# REDIS LOCK INTEGRATION
# ===============================

class ScriptLockManager:
    """
    Script-side lock manager that communicates with Django's Redis locks
    This ensures the script respects the same locking mechanism
    """
    
    def __init__(self):
        try:
            # Connect to the same Redis instance as Django
            self.redis = redis.Redis(
                host=os.environ.get('REDIS_HOST', 'localhost'),
                port=int(os.environ.get('REDIS_PORT', 6379)),
                db=int(os.environ.get('REDIS_DB', 0)),
                decode_responses=True
            )
            logger.info("Connected to Redis for lock checking")
        except Exception as e:
            logger.error(f"Could not connect to Redis: {e}")
            self.redis = None
    
    def check_user_lock_exists(self, user_id, lock_type="processing"):
        """
        Check if a user lock exists (called from script to verify Django lock)
        """
        if not self.redis:
            logger.warning("Redis not available - cannot check locks")
            return False
        
        try:
            lock_key = f"user_processing_lock:{user_id}:{lock_type}"
            lock_exists = self.redis.exists(lock_key)
            
            if lock_exists:
                ttl = self.redis.ttl(lock_key)
                logger.info(f"SCRIPT LOCK CHECK: User {user_id} has {lock_type} lock with TTL {ttl}s")
                return True
            else:
                logger.warning(f"SCRIPT LOCK CHECK: No {lock_type} lock found for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error checking user lock: {e}")
            return False
    
    def extend_user_lock(self, user_id, lock_type="processing", additional_seconds=1800):
        """
        Extend a user lock from the script side
        """
        if not self.redis:
            return False
        
        try:
            lock_key = f"user_processing_lock:{user_id}:{lock_type}"
            current_ttl = self.redis.ttl(lock_key)
            
            if current_ttl > 0:
                new_ttl = current_ttl + additional_seconds
                self.redis.expire(lock_key, new_ttl)
                logger.info(f"SCRIPT: Extended user {user_id} lock by {additional_seconds}s (new TTL: {new_ttl}s)")
                return True
            else:
                logger.warning(f"SCRIPT: Cannot extend lock for user {user_id} - lock not found or expired")
                return False
                
        except Exception as e:
            logger.error(f"Error extending user lock: {e}")
            return False

# Global script lock manager
script_lock_manager = ScriptLockManager()

try:
    import weasyprint
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = False   ### set to true if you want to attach pdf to email 
    logger.info("WeasyPrint available for PDF generation")
except ImportError:
    WEASYPRINT_AVAILABLE = False
    logger.error("WeasyPrint not available - PDF attachments will be skipped")

# Add project to Python path (dynamic - use script's directory)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)  # Go up one level from script to project root
sys.path.append(project_root)
# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RFQ.settings')

# Initialize Django
django.setup()

from django.conf import settings
from solicitations.models import (
    Solicitation,
    OEM,
    RFQ,
    OEMUser,
    UserOEMCustomization,
    SolicitationEmailStatus,
    RFQTaskSummary,
    EmailTemplateConfig,
    EmailTextStyleOverride,
    RFQIDTemplate,
    DEFAULT_RESALE_NOTICE_TEXT,
)
from solicitations.views import (
    _get_template_styles, _show_items_col, _generate_signature_section, _generate_items_table,
    _items_table_visible_columns,
    generate_layout_classic, generate_layout_two_column, generate_layout_card_based,
    generate_layout_compact, generate_layout_modern_grid, generate_layout_header_banner,
    apply_text_style_overrides_to_html
)
from accounts.models import CustomUser
from django.utils.timezone import now
from datetime import timedelta
from django.db import IntegrityError
from django.core.mail import get_connection
from django.core.mail.message import EmailMultiAlternatives
from uuid import uuid4
from solicitations.utils.logging_utils import (
    initialize_database_logging, 
    DatabaseLogger
)
from django.core.mail import send_mail

# Variables from Django settings
DB_HOST = settings.DB_HOST
DB_USER = settings.DB_USER
DB_PASSWORD = settings.DB_PASSWORD
DB_NAME = settings.DB_NAME
DB_PORT = settings.DB_PORT
EMAIL_ADDRESS = settings.DEFAULT_FROM_EMAIL
EMAIL_PASSWORD = settings.EMAIL_HOST_PASSWORD

start_time = now()  # Track when the task started

def is_testing_mode():
    """
    Simple testing mode control
    True = Send emails to logged-in user (testing)
    False = Send emails to actual OEMs (production)
    """
    # CHANGE THIS VALUE TO CONTROL MODE:
    TESTING_MODE = False   # Set to False for production 
    
    return TESTING_MODE

def load_data_from_input():
    """
    Load data from either command line JSON argument or file argument
    Returns tuple: (data, user_data, solicitation_ids, mail_data, auto_mode, username, created_by_user)
    """
    parser = argparse.ArgumentParser(description='Process RFQ emails')
    parser.add_argument('json_data', nargs='?', help='JSON data as string')
    parser.add_argument('--file', help='Path to JSON file containing data')
    
    args = parser.parse_args()
    
    # Determine input source
    if args.file:
        logger.info(f"Loading data from file: {args.file}")
        try:
            with open(args.file, 'r') as f:
                data = json.load(f)
            logger.info("Successfully loaded data from file")
        except Exception as e:
            logger.error(f"Error loading file {args.file}: {e}")
            sys.exit(1)
    elif args.json_data:
        logger.info("Loading data from command line argument")
        try:
            data = json.loads(args.json_data)
            logger.info("Successfully parsed JSON from command line")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON argument: {e}")
            sys.exit(1)
    else:
        logger.error("No data source provided. Use either JSON argument or --file parameter")
        sys.exit(1)
    
    logger.info('--------------------------------------------------------------------------')
    logger.info(f"Loaded data keys: {list(data.keys())}")
    
    # Extract data components
    user_data = data.get("user_data", {})
    solicitation_ids = data.get("solicitation_ids", [])  
    mail_data = data.get("mail_data", {})
    auto_mode = data.get("auto_mode", False)
    
    logger.info(f"User data keys: {list(user_data.keys())}")
    logger.info(f"Number of solicitation IDs: {len(solicitation_ids)}")
    logger.info(f"Mail data keys: {list(mail_data.keys())}")
    logger.info(f"Auto mode: {auto_mode}")
    
    # Extract username and get user
    username = user_data.get("username")
    if not username:
        logger.error("Username missing in user_data")
        sys.exit(1)
    
    logger.info(f"Processing for username: {username}")
    
    # Retrieve the CustomUser instance
    try:
        created_by_user = CustomUser.objects.get(username=username)
        logger.info(f"Retrieved CustomUser: {created_by_user}")
    except CustomUser.DoesNotExist:
        logger.error(f"No CustomUser found with username '{username}'")
        sys.exit(1)
    
    return data, user_data, solicitation_ids, mail_data, auto_mode, username, created_by_user

def get_user_email_connection(user):
    """Get email connection with user-specific settings - Updated version"""
    try:
        from solicitations.models import UserEmailConfig
        user_config = UserEmailConfig.objects.filter(user=user, is_active=True).first()
        
        if user_config:
            logger.info(f"Found user email configuration for {user.username}")
            return {
                'host': user_config.email_host,
                'port': user_config.email_port,
                'username': user_config.email_host_user,
                'password': user_config.email_host_password,
                'use_tls': user_config.email_use_tls,
                'from_email': user_config.default_from_email or user_config.email_host_user
            }
        else:
            logger.error(f"No email configuration found for user {user.username}")
            return None
            
    except Exception as e:
        logger.error(f"Error getting user email connection: {e}")
        return None

def format_phone_number(phone):
    """Format phone number to (XXX) XXX-XXXX format"""
    if not phone or not isinstance(phone, str):
        return phone or '-'
    
    # Remove all non-digit characters
    digits = re.sub(r'\D', '', phone)
    
    # Check if we have exactly 10 digits
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits[0] == '1':
        # Handle numbers with country code
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    else:
        # Return original if not standard format
        return phone

def check_user_stop_requested(user):
    """
    Enhanced check if user requested stop - minimal database check with better error handling
    Returns True if user wants to stop, False otherwise
    """
    try:
        from solicitations.models import UserProcessingControl
        
        control = UserProcessingControl.objects.filter(user=user).first()
        if control and control.stop_requested:
            logger.info(f"STOP DETECTED: User {user.username} requested stop: {control.stop_reason}")
            logger.info(f"STOP DETECTED: Stop requested at: {control.stop_requested_at}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking stop request for user {user.username}: {e}")
        return False 

def clear_user_stop_flag(user):
    """
    Clear the stop flag since we're handling the stop request
    """
    try:
        from solicitations.models import UserProcessingControl
        control = UserProcessingControl.objects.filter(user=user).first()
        if control:
            control.clear_stop()
            logger.info(f"Cleared stop flag for user {user.username}")
    except Exception as e:
        logger.error(f"Error clearing stop flag for user {user.username}: {e}")

def handle_user_stop_gracefully(user, current_ids, processing_rounds, session_failed_ids, original_total):
    """
    Handle user stop request gracefully with proper cleanup
    CLEARS remaining IDs completely (does NOT reset to pending)
    """
    logger.info(f"USER STOP DETECTED - gracefully exiting")
    logger.info(f"Remaining IDs to be CLEARED: {len(current_ids)}")
    
    # Clear the stop flag since we're handling it
    clear_user_stop_flag(user)
    
    # CLEAR remaining IDs completely (don't reset to pending)
    cleared_count = 0
    try:
        remaining_count = len(current_ids)
        if remaining_count > 0:
            # DELETE/CLEAR remaining items completely - don't reset to pending
            # Option 1: Delete the status records entirely
            deleted_count = SolicitationEmailStatus.objects.filter(
                solicitation_id__in=current_ids,
                user=user,
                email_sent=False  # Only delete unsent ones
            ).delete()
            
            cleared_count = deleted_count[0] if isinstance(deleted_count, tuple) else deleted_count
            logger.info(f"STOP HANDLING: CLEARED {cleared_count} remaining items completely")
            
            # Log the stop action
            if 'db_logger' in globals() and db_logger:
                from solicitations.utils.logging_utils import log_to_database
                log_to_database(
                    message=f"Processing stopped by user request. CLEARED {cleared_count} items completely.",
                    level='INFO',
                    category='processing',
                    user=user,
                    extra_data={
                        'stop_reason': 'User requested stop',
                        'round_stopped': processing_rounds,
                        'items_cleared': cleared_count,
                        'cleared_ids': current_ids[:10],  # First 10 for logging
                        'action': 'cleared_completely'
                    }
                )
    except Exception as e:
        logger.error(f"Error clearing remaining items during stop: {e}")
    
    # After clearing, get final counts
    try:
        final_remaining, final_sent, final_failed = get_remaining_solicitation_ids([], user)  # Empty list since we cleared
    except:
        final_remaining, final_sent, final_failed = [], [], []
    
    # Return with stopped status - remaining should be 0 since we cleared them
    logger.info(f"STOP COMPLETE: Processing stopped after {processing_rounds} rounds")
    logger.info(f"STOP COMPLETE: {cleared_count} items CLEARED completely")
    return {
        'total_requested': original_total,
        'successfully_sent': len(final_sent),
        'failed': 0,  # Don't count as failed since user stopped
        'remaining': 0,  # 0 because we cleared them
        'cleared': cleared_count,  # New field to track cleared items
        'status': 'stopped_by_user',
        'message': f'Processing stopped by user request after {processing_rounds} rounds. {cleared_count} items cleared completely.',
        'rounds': processing_rounds,
        'stop_reason': 'User clicked stop button',
        'session_failed_ids': session_failed_ids
    }



def get_imap_sent_folder_name(email_host, custom_folder=None):
    """Get the correct sent folder name based on email provider"""
    if custom_folder and custom_folder.strip():
        return custom_folder.strip()
    
    email_host_lower = email_host.lower()
    
    # Check for major providers
    if 'gmail' in email_host_lower:
        return '[Gmail]/Sent Mail'
    elif 'outlook' in email_host_lower or 'hotmail' in email_host_lower or 'live' in email_host_lower:
        return 'Sent Items'
    elif 'yahoo' in email_host_lower:
        return 'Sent'
    elif 'icloud' in email_host_lower:
        return 'Sent Messages'
    else:
        # For custom domains (most common patterns)
        return ['INBOX.Sent', 'Sent Items', 'Sent', 'Sent Messages']

def get_imap_server_settings(email_host, custom_imap_host=None, custom_imap_port=None):
    """Get IMAP server settings based on SMTP host"""
    if custom_imap_host and custom_imap_host.strip():
        return {
            'server': custom_imap_host.strip(),
            'port': custom_imap_port or 993,
            'use_ssl': True
        }
    
    email_host_lower = email_host.lower()
    
    # Check for major providers
    if 'gmail' in email_host_lower:
        return {'server': 'imap.gmail.com', 'port': 993, 'use_ssl': True}
    elif 'outlook' in email_host_lower or 'hotmail' in email_host_lower or 'live' in email_host_lower:
        return {'server': 'imap-mail.outlook.com', 'port': 993, 'use_ssl': True}
    elif 'yahoo' in email_host_lower:
        return {'server': 'imap.mail.yahoo.com', 'port': 993, 'use_ssl': True}
    elif 'icloud' in email_host_lower:
        return {'server': 'imap.mail.me.com', 'port': 993, 'use_ssl': True}
    else:
        # For custom domains, try common IMAP server patterns
        if email_host.startswith('smtp.'):
            imap_host = email_host.replace('smtp.', 'imap.')
        elif email_host.startswith('mail.'):
            imap_host = email_host  # mail.domain.com often works for both
        else:
            imap_host = f"mail.{email_host}"
        
        return {'server': imap_host, 'port': custom_imap_port or 993, 'use_ssl': True}

def save_to_sent_folder(email_message, user_config):
    """
    Save the sent email to the user's IMAP sent folder
    This makes the email appear in their email client's Sent folder
    """
    try:
        # Skip if user disabled this feature
        if not user_config.save_to_sent_folder:
            logger.info("Sent folder saving is disabled by user")
            return False
            
        # Get IMAP settings
        imap_settings = get_imap_server_settings(
            user_config.email_host,
            user_config.custom_imap_host,
            user_config.custom_imap_port
        )
        sent_folder = get_imap_sent_folder_name(
            user_config.email_host,
            user_config.custom_sent_folder
        )
        
        logger.info(f"Saving email to sent folder: {sent_folder}")
        logger.info(f"IMAP server: {imap_settings['server']}:{imap_settings['port']}")
        
        # Connect to IMAP server
        if imap_settings['use_ssl']:
            imap_server = imaplib.IMAP4_SSL(imap_settings['server'], imap_settings['port'])
        else:
            imap_server = imaplib.IMAP4(imap_settings['server'], imap_settings['port'])
        
        # Login to IMAP using same credentials as SMTP
        imap_server.login(user_config.email_host_user, user_config.email_host_password)
        logger.info("Successfully logged into IMAP server")
        
        # Handle multiple possible sent folder names
        sent_folder_names = [sent_folder] if isinstance(sent_folder, str) else sent_folder
        
        saved = False
        for folder_name in sent_folder_names:
            try:
                # Try to select the sent folder
                status, _ = imap_server.select(folder_name)
                if status == 'OK':
                    logger.info(f"Successfully selected folder: {folder_name}")
                    
                    # Add proper email headers
                    email_message['Date'] = email.utils.formatdate(localtime=True)
                    email_message['Message-ID'] = email.utils.make_msgid()
                    
                    # Add headers that help email clients recognize this as a sent email
                    email_message['X-Mailer'] = 'RFQ System'
                    email_message['X-Priority'] = '3'
                    
                    # Convert message to bytes
                    email_bytes = email_message.as_bytes()
                    
                    # Append to sent folder with \Seen flag (mark as read)
                    status, result = imap_server.append(
                        folder_name,
                        '\\Seen',  # Mark as read so it appears properly
                        imaplib.Time2Internaldate(time.time()),
                        email_bytes
                    )
                    
                    if status == 'OK':
                        logger.info(f"SUCCESS! Email saved to {folder_name}")
                        logger.info(f"RFQ will now appear in {user_config.email_host_user}'s email client Sent folder")
                        logger.info(f"Check Gmail/Outlook/webmail to see the sent RFQ email")
                        saved = True
                        break
                    else:
                        logger.warning(f"Failed to append to {folder_name}: {result}")
                        
            except Exception as folder_error:
                logger.warning(f"Could not access folder {folder_name}: {folder_error}")
                continue
        
        if not saved:
            logger.warning("Could not save to any sent folder")
            logger.warning("Email was sent successfully, but copy not saved to sent folder")
            logger.info("Try configuring custom IMAP settings in email configuration")
        
        # Close IMAP connection
        imap_server.close()
        imap_server.logout()
        
        return saved
        
    except Exception as e:
        logger.error(f"Error saving to sent folder: {e}")
        logger.error("Email was sent successfully, but could not save copy to sent folder")
        logger.info("Check your email password and IMAP settings")
        return False

##helper function to parse multiple emails
def parse_multiple_emails(email_string):
    """
    Parse multiple emails from a string separated by semicolons or commas
    Returns list of valid email addresses
    """
    if not email_string or not email_string.strip():
        return []
    
    # Split by semicolon or comma and clean up
    separators = [';', ',']
    emails = [email_string]
    
    for separator in separators:
        temp_emails = []
        for email in emails:
            temp_emails.extend(email.split(separator))
        emails = temp_emails
    
    # Clean and validate emails
    valid_emails = []
    for email in emails:
        cleaned_email = email.strip()
        if cleaned_email and '@' in cleaned_email and '.' in cleaned_email:
            valid_emails.append(cleaned_email)
    
    return valid_emails

def get_oem_data_with_customization(oem, user):
    """
    Get OEM data with user customization priority
    Returns OEM data preferring UserOEMCustomization data over base OEM data
    """
    try:
        # Try to get user's customization for this OEM
        customization = UserOEMCustomization.objects.filter(user=user, oem=oem).first()
        
        if customization:
            logger.info(f"Found user customization for CAGE {oem.cage} (User: {user.username})")
            
            # Build data preferring custom fields over OEM fields
            oem_data = {
                'organization_name': customization.custom_name or oem.name,
                'cage': oem.cage,  # CAGE code never changes
                'street': customization.custom_street or oem.street,
                'city': customization.custom_city or oem.city,
                'postal_code': customization.custom_postal_code or oem.postal_code,
                'phone': customization.custom_phone or oem.phone,
                'fax': customization.custom_fax or oem.fax,
                'email': customization.custom_email or oem.email,
                'poc': customization.custom_poc or getattr(oem, 'poc', '')
            }
            
            # Log what customizations are being used
            custom_fields = []
            if customization.custom_name: custom_fields.append('name')
            if customization.custom_email: custom_fields.append('email')
            if customization.custom_phone: custom_fields.append('phone')
            if customization.custom_fax: custom_fields.append('fax')
            if customization.custom_city: custom_fields.append('city')
            if customization.custom_street: custom_fields.append('street')
            if customization.custom_postal_code: custom_fields.append('postal_code')
            if customization.custom_poc: custom_fields.append('poc')
            
            logger.info(f"Using custom data for fields: {custom_fields}")
            
        else:
            logger.info(f"No user customization found for CAGE {oem.cage} (User: {user.username}), using base OEM data")
            
            # Use base OEM data
            oem_data = {
                'organization_name': oem.name,
                'cage': oem.cage,
                'street': oem.street,
                'city': oem.city,
                'postal_code': oem.postal_code,
                'phone': oem.phone,
                'fax': oem.fax,
                'email': oem.email,
                'poc': getattr(oem, 'poc', '')
            }
        
        return oem_data
        
    except Exception as e:
        logger.error(f"Error getting OEM data with customization for CAGE {oem.cage}: {e}")
        
        # Fallback to base OEM data
        return {
            'organization_name': oem.name,
            'cage': oem.cage,
            'street': oem.street,
            'city': oem.city,
            'postal_code': oem.postal_code,
            'phone': oem.phone,
            'fax': oem.fax,
            'email': oem.email,
            'poc': getattr(oem, 'poc', '')
        }

def filter_already_sent_solicitations(solicitation_ids, user):
    """
    Filter out solicitations that have already been sent emails for this user
    Returns list of solicitation IDs that still need processing
    NOTE: We do NOT filter out 'failed' status here to allow manual retries from UI
    """
    try:
        # Get solicitations that have already been sent emails (successfully sent only)
        already_processed = SolicitationEmailStatus.objects.filter(
            solicitation_id__in=solicitation_ids,
            user=user,
            email_sent=True  # Only check if email was actually sent
        ).values_list('solicitation_id', flat=True)
        
        already_processed_list = list(already_processed)
        
        # Filter out already processed ones (sent only, NOT failed)
        remaining_ids = [sid for sid in solicitation_ids if sid not in already_processed_list]
        
        logger.info(f"Total solicitation IDs received: {len(solicitation_ids)}")
        logger.info(f"Already sent: {len(already_processed_list)}")
        logger.info(f"Remaining to process: {len(remaining_ids)}")
        
        if already_processed_list:
            logger.info(f"Skipping already sent solicitation IDs: {already_processed_list}")
        
        return remaining_ids
        
    except Exception as e:
        logger.error(f"Error filtering already sent solicitations: {e}")
        return solicitation_ids  # Return all if error occurs

def check_and_lock_solicitations_for_sending(solicitation_ids, user):
    """
    Check status right before sending and atomically mark as processing
    Returns list of IDs that are safe to send (not already sent by concurrent tasks)
    """
    try:
        from django.db import transaction
        
        safe_to_send = []
        
        # Use atomic transaction to check and update status
        with transaction.atomic():
            # Re-check status right before sending (in case another task processed them)
            current_statuses = SolicitationEmailStatus.objects.filter(
                solicitation_id__in=solicitation_ids,
                user=user
            ).select_for_update()  # Lock the rows
            
            for status in current_statuses:
                if not status.email_sent:  # Only if not already sent
                    # Mark as processing to prevent other tasks from sending
                    status.email_status = 'processing'
                    status.processing_attempts = (status.processing_attempts or 0) + 1
                    status.save()
                    safe_to_send.append(status.solicitation_id)
                else:
                    logger.info(f"Solicitation {status.solicitation_id} already sent by another task, skipping")
        
        logger.info(f"Checked {len(solicitation_ids)} solicitations, {len(safe_to_send)} are safe to send")
        return safe_to_send
        
    except Exception as e:
        logger.error(f"Error checking solicitation status before sending: {e}")
        return []  # Return empty list on error to be safe

def mark_solicitations_as_sent(solicitation_ids, user, rfq_ids=None):
    """
    Mark solicitations as successfully sent and link RFQs
    """
    try:
        from django.utils import timezone
        from django.db import transaction
        
        with transaction.atomic():
            # Update all solicitations in the list
            updated_count = SolicitationEmailStatus.objects.filter(
                solicitation_id__in=solicitation_ids,
                user=user
            ).update(
                email_status='sent',
                email_sent=True,
                email_sent_at=timezone.now(),
                rfq_created=True
            )
            
            # If RFQ IDs provided, link them
            if rfq_ids:
                for i, sol_id in enumerate(solicitation_ids):
                    if i < len(rfq_ids):
                        SolicitationEmailStatus.objects.filter(
                            solicitation_id=sol_id,
                            user=user
                        ).update(rfq_id=rfq_ids[i])
            
            logger.info(f"Successfully marked {updated_count} solicitations as SENT")
            
            # Database logging (FIXED SYNTAX)
            try:
                from solicitations.utils.logging_utils import log_to_database
                log_to_database(
                    message=f"Marked {updated_count} solicitations as SENT",
                    level='INFO',
                    category='status',
                    user=user,
                    items_processed=len(solicitation_ids),
                    items_successful=updated_count,
                    extra_data={
                        'solicitation_ids': solicitation_ids[:5],
                        'status_change': 'sent',
                        'rfq_ids': rfq_ids[:5] if rfq_ids else []
                    }
                )  # ? ADDED MISSING CLOSING PARENTHESIS
            except Exception as e:
                logger.error(f"Failed to log status update to database: {e}")
            
            return updated_count  # ? ADDED RETURN STATEMENT
            
    except Exception as e:
        logger.error(f"Error marking solicitations as sent: {e}")
        return 0 

def test_mark_solicitations_as_sent(user):
    """
    Direct test of mark_solicitations_as_sent function
    """
    logger.info("=== TESTING mark_solicitations_as_sent FUNCTION ===")
    
    try:
        # Find some existing processing records for this user
        test_records = SolicitationEmailStatus.objects.filter(
            user=user,
            email_status='processing'
        )[:2]  # Take just 2 records for testing
        
        if not test_records.exists():
            logger.error("TEST: No processing records found to test with")
            
            # Alternative: Look for any records that aren't 'sent'
            alternative_records = SolicitationEmailStatus.objects.filter(
                user=user
            ).exclude(email_status='sent')[:2]
            
            if alternative_records.exists():
                logger.info(f"TEST: Using alternative records with status: {[r.email_status for r in alternative_records]}")
                test_records = alternative_records
            else:
                logger.error("TEST: No records found at all for testing")
                return False
        
        test_ids = [record.solicitation_id for record in test_records]
        logger.info(f"TEST: Using solicitation IDs for testing: {test_ids}")
        
        # Show BEFORE state
        logger.info("TEST: BEFORE update:")
        for record in test_records:
            logger.info(f"  - ID {record.solicitation_id}: status={record.email_status}, sent={record.email_sent}, sent_at={record.email_sent_at}")
        
        # Call the function directly
        logger.info("TEST: Calling mark_solicitations_as_sent()...")
        result = mark_solicitations_as_sent(test_ids, user)
        logger.info(f"TEST: Function returned: {result}")
        
        # Check AFTER state immediately
        logger.info("TEST: AFTER update (immediate check):")
        updated_records = SolicitationEmailStatus.objects.filter(
            solicitation_id__in=test_ids,
            user=user
        )
        
        for record in updated_records:
            logger.info(f"  - ID {record.solicitation_id}: status={record.email_status}, sent={record.email_sent}, sent_at={record.email_sent_at}")
        
        # Count how many are actually 'sent'
        sent_count = updated_records.filter(email_status='sent').count()
        logger.info(f"TEST: {sent_count} out of {len(test_ids)} records are now marked as 'sent'")
        
        if sent_count == len(test_ids):
            logger.info("TEST:mark_solicitations_as_sent() WORKS CORRECTLY!")
            return True
        else:
            logger.error("TEST:mark_solicitations_as_sent() DID NOT WORK!")
            return False
            
    except Exception as e:
        logger.error(f"TEST: Exception during test: {e}")
        import traceback
        logger.error(f"TEST: Traceback: {traceback.format_exc()}")
        return False

def mark_solicitations_as_failed(solicitation_ids, user, error_message=None):
    """
    Mark solicitations as failed
    """
    try:
        from django.db import transaction
        
        with transaction.atomic():
            updated_count = SolicitationEmailStatus.objects.filter(
                solicitation_id__in=solicitation_ids,
                user=user
            ).update(
                email_status='failed'
            )
            
            logger.info(f"Marked {updated_count} solicitations as FAILED")
            if error_message:
                logger.info(f"Failure reason: {error_message}")
            return updated_count
            
    except Exception as e:
        logger.error(f"Error marking solicitations as failed: {e}")
        return 0

def get_enabled_cage_codes(user):
    """Get enabled CAGE codes for the specific user"""
    try:
        connection = MySQLdb.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            port=DB_PORT,
            cursorclass=DictCursor
        )
        cursor = connection.cursor()
        
        # Get enabled OEMs for the specific user
        enabled_oems_query = """
        SELECT o.cage
        FROM solicitations_oemuser ou
        JOIN solicitations_oem o ON ou.oem_id = o.id
        WHERE ou.user_id = %s AND ou.is_disabled = FALSE
        """
        cursor.execute(enabled_oems_query, (user.id,))  # USER-SPECIFIC
        enabled_cages = [row["cage"] for row in cursor.fetchall()]
        
        cursor.close()
        connection.close()
        
        logger.info(f"Found {len(enabled_cages)} enabled CAGE codes for user {user.username} (ID: {user.id})")
        return enabled_cages
        
    except Exception as e:
        logger.error(f"Error getting enabled CAGE codes for user {user.username}: {e}")
        return []


def get_oem_by_cage_for_user(cage_code, user=None):
    """
    Return one OEM row for this CAGE. If duplicate rows exist:
    - Prefer the OEM where this user has OEMUser with is_disabled=False (active).
    - Else prefer an OEM with no OEMUser row for this user (neutral target).
    - Else fall back to lowest id (all duplicates only have disabled links for this user).
    If user is None, only the lowest-id row is used (legacy / no preference).
    """
    if not cage_code or not str(cage_code).strip():
        return None
    candidates = list(OEM.objects.filter(cage=cage_code).order_by('id'))
    if not candidates:
        return None
    if user is None or len(candidates) == 1:
        return candidates[0]

    for oem in candidates:
        ou = OEMUser.objects.filter(user=user, oem=oem).first()
        if ou and not ou.is_disabled:
            return oem

    for oem in candidates:
        if not OEMUser.objects.filter(user=user, oem=oem).exists():
            return oem

    return candidates[0]


def get_solicitations_data_individual(solicitation_ids, user):
    """
    Get solicitation data from database - INDIVIDUAL PROCESSING (NO CONSOLIDATION)
    Each solicitation will be processed individually
    Enhanced to include OEM creation but NO consolidation
    """
    try:
        # First filter out already sent solicitations
        remaining_ids = filter_already_sent_solicitations(solicitation_ids, user)
        
        if not remaining_ids:
            logger.info("No solicitations remaining to process after filtering")
            return {}
        
        # Get solicitation data from database
        solicitations = Solicitation.objects.filter(id__in=remaining_ids)
        
        if not solicitations.exists():
            logger.info("No solicitations found in database")
            return {}
        
        # Get enabled CAGE codes for this user
        enabled_cages = get_enabled_cage_codes(user)
        logger.info(f"Initially found {len(enabled_cages)} enabled CAGE codes for user {user.username}")
        
        # Process each solicitation individually (NO grouping by CAGE)
        individual_groups = {}  # Will be {unique_key: [single_solicitation]}
        processed_cage_codes = set()
        new_cages_added = []
        
        for solicitation in solicitations:
            cage_code = solicitation.cage
                
            # Skip invalid solicitations
            if not cage_code or cage_code.strip() == '-':
                logger.info(f"Skipping solicitation {solicitation.id} - invalid CAGE code")
                continue
            
            # AUTO-CREATE AND ENABLE OEM if not in enabled list
            if cage_code not in enabled_cages:
                logger.info(f"CAGE {cage_code} not enabled for user {user.username} - auto-creating and enabling...")
                
                # Create or update OEM record
                oem_record = extract_oem_data(cage_code)
                if oem_record:
                    oem_obj = get_oem_by_cage_for_user(cage_code, user)
                    if oem_obj:
                        # Create OEMUser relationship to enable this CAGE for the user
                        from solicitations.models import OEMUser
                        oem_user, created = OEMUser.objects.get_or_create(
                            user=user,
                            oem=oem_obj,
                            defaults={'is_disabled': False}
                        )
                        
                        if created:
                            logger.info(f"Created OEMUser relationship for CAGE {cage_code} and user {user.username}")
                            new_cages_added.append(cage_code)
                        else:
                            # Enable if it was disabled
                            if oem_user.is_disabled:
                                oem_user.is_disabled = False
                                oem_user.save()
                                logger.info(f"Re-enabled CAGE {cage_code} for user {user.username}")
                                new_cages_added.append(cage_code)
                            else:
                                logger.info(f"CAGE {cage_code} already enabled for user {user.username}")
                        
                        # Add to enabled cages list for this session
                        enabled_cages.append(cage_code)
                    else:
                        logger.error(f"Failed to find OEM for CAGE {cage_code} after extraction attempt")
                        continue
                else:
                    logger.error(f"Failed to create/extract OEM data for CAGE {cage_code}")
                    continue
                        
            # Create unique key for each individual solicitation
            # Using solicitation ID to ensure each one gets processed separately
            unique_key = f"{cage_code}_{solicitation.id}"
            
            # Add as individual item (no grouping)
            individual_groups[unique_key] = [{
                'id': solicitation.id,
                'cage': solicitation.cage,
                'nomenclature': solicitation.nomenclature or '',
                'quantity': str(solicitation.quantity) if solicitation.quantity else '1',
                'return_by_date': str(solicitation.return_by_date) if solicitation.return_by_date else '',
                'NSN': solicitation.NSN or '',
                'part_number': solicitation.part_number or '',
                'solicitation_number': getattr(solicitation, 'solicitation', '') or '',
                'unit': getattr(solicitation, 'unit', 'EA'),
                'inspection_point': getattr(solicitation, 'inspection_point', '-'),
                'acceptance_point': getattr(solicitation, 'acceptance_point', '-'),
                'deliver_fob': getattr(solicitation, 'deliver_fob', '-'),
                'deliver_days': getattr(solicitation, 'deliver_days', '-')
            }]
            
            processed_cage_codes.add(cage_code)
        
        if new_cages_added:
            logger.info(f"AUTO-CREATED and ENABLED {len(new_cages_added)} new CAGE codes for user {user.username}: {new_cages_added}")
        
        # NO CONSOLIDATION - Skip the consolidation check entirely
        logger.info("INDIVIDUAL PROCESSING MODE - Skipping consolidation opportunities check")
        
        logger.info(f"Final result: Created {len(individual_groups)} individual solicitation groups (no consolidation)")
        logger.info(f"Total enabled CAGE codes after auto-creation: {len(enabled_cages)}")
        
        # Log summary by individual solicitation
        for unique_key, items in individual_groups.items():
            cage = items[0]['cage']
            sol_id = items[0]['id']
            status = "NEW" if cage in new_cages_added else "EXISTING"
            logger.info(f"  - Individual solicitation {sol_id} for CAGE {cage} ({status}): 1 item")
        
        return dict(individual_groups)
        
    except Exception as e:
        logger.error(f"Error getting individual solicitations data: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return {}

def get_remaining_solicitation_ids(original_ids, user):
    """
    Get the remaining solicitation IDs that still need processing
    This dynamically removes already processed IDs from the original list
    NOTE: We do NOT filter out 'failed' status here to allow manual retries from UI
    """
    try:
        # Get solicitations that have been successfully sent
        successfully_sent = SolicitationEmailStatus.objects.filter(
            solicitation_id__in=original_ids,
            user=user,
            email_sent=True  # Only count actually sent emails
        ).values_list('solicitation_id', flat=True)
        
        successfully_sent_list = list(successfully_sent)
        
        # Get failed solicitations (for logging purposes only - don't exclude them)
        failed_solicitations = SolicitationEmailStatus.objects.filter(
            solicitation_id__in=original_ids,
            user=user,
            email_status='failed'
        ).values_list('solicitation_id', flat=True)
        
        failed_list = list(failed_solicitations)
        
        # Remove only successfully sent IDs from the original list
        # Do NOT remove failed ones - let user retry them manually
        remaining_ids = [sid for sid in original_ids if sid not in successfully_sent_list]
        
        logger.info(f"PROGRESSIVE REMOVAL - Original IDs: {original_ids}")
        logger.info(f"PROGRESSIVE REMOVAL - Successfully sent: {successfully_sent_list}")
        logger.info(f"PROGRESSIVE REMOVAL - Previously failed (keeping for retry): {failed_list}")
        logger.info(f"PROGRESSIVE REMOVAL - Remaining to process: {remaining_ids}")
        
        return remaining_ids, successfully_sent_list, failed_list
        
    except Exception as e:
        logger.error(f"Error getting remaining solicitation IDs: {e}")
        return original_ids, [], []

def reset_stale_processing_status(user, max_processing_time_minutes=30):
    """
    Reset solicitations that have been stuck in 'processing' status.
    This prevents deadlocks from previous failed runs.
    """
    try:
        from django.utils import timezone
        cutoff_time = timezone.now() - timedelta(minutes=max_processing_time_minutes)

        # Find all solicitations stuck in processing for too long
        stale_processing = SolicitationEmailStatus.objects.filter(
            user=user,
            email_status='processing',
            email_sent=False,
            updated_at__lt=cutoff_time,
        )
        
        stale_count = stale_processing.count()
        if stale_count > 0:
            stale_ids = list(stale_processing.values_list('solicitation_id', flat=True))
            logger.info(f"STALE PROCESSING RESET - Found {stale_count} stale processing entries for user {user.username}")
            logger.info(f"STALE PROCESSING RESET - Resetting IDs: {stale_ids}")
            
            # Reset them back to pending
            stale_processing.update(
                email_status='pending',
                processing_attempts=0
            )
            
            logger.info(f"STALE PROCESSING RESET - Reset {stale_count} stale entries to pending")
        else:
            logger.info(f"STALE PROCESSING RESET - No stale processing entries found for user {user.username}")
            
    except Exception as e:
        logger.error(f"Error resetting stale processing status: {e}")

def process_individual_solicitation(cage_code, records, created_by_user, user_data, mail_data, user_email_interval):
    """
    FIXED: Process a single solicitation with correct flow
    
    Step 1: Generate RFQ IDs WITHOUT incrementing sequence
    Step 2: Send Email WITH RFQ IDs
    Step 3: ONLY if email succeeds, finalize sequence & save RFQ
    """
    record_ids = [record['id'] for record in records]
    
    try:
        logger.info(f"INDIVIDUAL PROCESSING - Starting for CAGE {cage_code} with {len(records)} record(s)")
        
        # Should only have 1 record for individual processing
        if len(records) > 1:
            logger.warning(f"INDIVIDUAL PROCESSING - Got {len(records)} records for {cage_code}, processing all individually")
        
        # Priority Logic Implementation
        logger.info(f"INDIVIDUAL PROCESSING - Starting priority data retrieval for CAGE {cage_code}")
        
        # First, check if OEM exists and is associated with user
        existing_oem = get_oem_by_cage_for_user(cage_code, created_by_user)
        oem_ready = False
        if existing_oem is not None:
            logger.info(f"INDIVIDUAL PROCESSING - OEM {cage_code} found in database")
            try:
                oem_user = OEMUser.objects.get(oem=existing_oem, user=created_by_user)
                if not oem_user.is_disabled:
                    logger.info(f"INDIVIDUAL PROCESSING - OEM {cage_code} is associated with user {created_by_user.username}")
                    oem_ready = True
                else:
                    logger.info(f"INDIVIDUAL PROCESSING - OEM {cage_code} is disabled for user {created_by_user.username}")
            except OEMUser.DoesNotExist:
                logger.info(f"INDIVIDUAL PROCESSING - OEM {cage_code} exists but NOT associated with user {created_by_user.username}")

        if not oem_ready:
            logger.info(f"INDIVIDUAL PROCESSING - OEM {cage_code} not found or not associated, creating from solicitation data")
            
            # Get solicitation data
            solicitation = Solicitation.objects.filter(id__in=record_ids).first()
            if not solicitation:
                logger.error(f"INDIVIDUAL PROCESSING - No solicitation found for CAGE {cage_code}")
                mark_solicitations_as_failed(record_ids, created_by_user, f"No solicitation found for CAGE {cage_code}")
                return False
            
            # Create OEM from solicitation data
            oem_data = {
                'cage': cage_code,
                'name': solicitation.organization_name or f"Unknown - {cage_code}",
                'street': solicitation.street_name or '',
                'city': solicitation.city or '',
                'postal_code': solicitation.postal_code or '',
                'phone': solicitation.phone or '',
                'fax': solicitation.fax or '',
                'email': solicitation.email or 'williamdemo01@gmail.com',
                'data_source': 'script',
                'manual_override': False
            }
            
            anchor_oem = get_oem_by_cage_for_user(cage_code, created_by_user)
            if anchor_oem is None:
                existing_oem = OEM.objects.create(**oem_data)
                logger.info(f"INDIVIDUAL PROCESSING - Created new OEM for CAGE {cage_code}")
            else:
                existing_oem = anchor_oem
                if hasattr(existing_oem, 'manual_override') and existing_oem.manual_override:
                    logger.info(f"INDIVIDUAL PROCESSING - OEM {cage_code} has manual override, not updating")
                elif hasattr(existing_oem, 'data_source') and existing_oem.data_source in ['manual', 'import']:
                    logger.info(f"INDIVIDUAL PROCESSING - OEM {cage_code} was added via {existing_oem.data_source}, not updating")
                else:
                    for key, value in oem_data.items():
                        if key != 'cage':
                            setattr(existing_oem, key, value)
                    existing_oem.save()
                    logger.info(f"INDIVIDUAL PROCESSING - Updated OEM for CAGE {cage_code}")
            
            # Create association with user
            OEMUser.objects.get_or_create(
                user=created_by_user,
                oem=existing_oem,
                defaults={'is_disabled': False}
            )
            logger.info(f"INDIVIDUAL PROCESSING - Associated OEM {cage_code} with user {created_by_user.username}")
        
        # Now get OEM data with customization priority
        oem_info = get_oem_data_with_customization(existing_oem, created_by_user)
        logger.info(f"INDIVIDUAL PROCESSING - Retrieved final OEM data for {cage_code} with user customizations applied")
        
        # Parse multiple emails
        oem_emails = parse_multiple_emails(oem_info['email'])
        
        if not oem_emails:
            logger.error(f"INDIVIDUAL PROCESSING - OEM {cage_code} has no valid email addresses")
            mark_solicitations_as_failed(record_ids, created_by_user, f"OEM {cage_code} has no valid email addresses")
            return False
        
        logger.info(f"INDIVIDUAL PROCESSING - Found {len(oem_emails)} email(s) for CAGE {cage_code}: {oem_emails}")
        
        # Get solicitation objects
        solicitation_objects = []
        invalid_solicitation_ids = []
        
        for record in records:
            try:
                solicitation = Solicitation.objects.get(id=record['id'])
                solicitation_objects.append(solicitation)
            except Solicitation.DoesNotExist:
                logger.error(f"INDIVIDUAL PROCESSING - Solicitation {record['id']} not found")
                invalid_solicitation_ids.append(record['id'])
                continue
        
        # Mark invalid solicitations as failed
        if invalid_solicitation_ids:
            mark_solicitations_as_failed(invalid_solicitation_ids, created_by_user, "Solicitation not found in database")
        
        # Continue with valid solicitations only
        if not solicitation_objects:
            logger.error(f"INDIVIDUAL PROCESSING - No valid solicitations for CAGE {cage_code}")
            return False
        
        # Update record_ids to only include valid ones
        valid_record_ids = [sol.id for sol in solicitation_objects]
        
        # ========== STEP 1: GENERATE RFQ IDs (WITHOUT SAVING SEQUENCE) ==========
        logger.info(f"INDIVIDUAL PROCESSING - STEP 1: Generating RFQ IDs WITHOUT incrementing sequence")
        
        items_for_email = []
        rfq_ids_to_generate = []  # Store IDs to save LATER if email succeeds
        
        try:
            # Get user's RFQ template
            try:
                rfq_template = RFQIDTemplate.objects.get(user=created_by_user)
            except RFQIDTemplate.DoesNotExist:
                logger.error(f"INDIVIDUAL PROCESSING - No RFQ ID template found for user {created_by_user.username}")
                mark_solicitations_as_failed(valid_record_ids, created_by_user, "No RFQ ID template configured")
                return False
            
            for i, solicitation in enumerate(solicitation_objects):
                record = [r for r in records if r['id'] == solicitation.id][0]
                
                # GENERATE RFQ ID WITHOUT SAVING SEQUENCE
                rfq_data = rfq_template.get_next_rfq_id_without_saving(
                    created_by_user,
                    existing_oem.cage,
                    solicitation.id
                )
                rfq_unique_id = rfq_data['rfq_id']
                next_sequence = rfq_data['next_sequence']
                
                logger.info(f"INDIVIDUAL PROCESSING - Generated RFQ ID: {rfq_unique_id} (sequence will be {next_sequence} if email succeeds)")
                
                # Store for later (sequence finalization after email success)
                rfq_ids_to_generate.append({
                    'solicitation': solicitation,
                    'rfq_unique_id': rfq_unique_id,
                    'next_sequence': next_sequence
                })
                
                # Add RFQ ID to items for email
                items_for_email.append({
                    'nomenclature': record['nomenclature'],
                    'quantity': record['quantity'],
                    'return_by_date': record['return_by_date'],
                    'NSN': record['NSN'],
                    'part_number': record['part_number'],
                    'solicitation_number': getattr(solicitation, 'solicitation', '') or '',
                    'unit': record['unit'],
                    'inspection_point': record['inspection_point'],
                    'acceptance_point': record['acceptance_point'],
                    'deliver_fob': record['deliver_fob'],
                    'deliver_days': record['deliver_days'],
                    'rfq_unique_id': rfq_unique_id  # RFQ ID INCLUDED IN EMAIL
                })
                logger.info(f"INDIVIDUAL PROCESSING - Prepared email item with RFQ ID {rfq_unique_id}")
                
        except Exception as rfq_gen_error:
            logger.error(f"INDIVIDUAL PROCESSING - Error generating RFQ IDs: {rfq_gen_error}")
            mark_solicitations_as_failed(valid_record_ids, created_by_user, f"RFQ ID generation error: {str(rfq_gen_error)}")
            return False
        
        logger.info(f"INDIVIDUAL PROCESSING - STEP 1 COMPLETE: Generated {len(rfq_ids_to_generate)} RFQ IDs (sequences NOT finalized yet)")
        
        # ========== STEP 2: SEND EMAIL WITH RFQ IDs ==========
        logger.info(f"INDIVIDUAL PROCESSING - STEP 2: Sending emails for CAGE {cage_code}")
        
        successful_sends = 0
        failed_sends = 0
        send_errors = []
        
        for rfq_index, item in enumerate(items_for_email):
            logger.info(f"INDIVIDUAL PROCESSING - Sending individual email for RFQ {item['rfq_unique_id']} ({rfq_index + 1}/{len(items_for_email)})")
            
            try:
                email_sent = send_individual_email_with_cc_spam_safe(
                    oem_emails,
                    [item],
                    user_data,
                    oem_info,
                    now(),
                    created_by_user
                )
                
                if email_sent:
                    successful_sends += 1
                    if len(oem_emails) == 1:
                        logger.info(f"INDIVIDUAL PROCESSING - RFQ {item['rfq_unique_id']} sent successfully to {oem_emails[0]}")
                    else:
                        logger.info(f"INDIVIDUAL PROCESSING - RFQ {item['rfq_unique_id']} sent successfully TO: {oem_emails[0]}, CC: {oem_emails[1:]}")
                else:
                    failed_sends += 1
                    error_msg = f"RFQ {item['rfq_unique_id']} failed to send"
                    logger.error(f"INDIVIDUAL PROCESSING - {error_msg}")
                    send_errors.append(error_msg)
                
                # Add delay between RFQs
                if rfq_index < len(items_for_email) - 1:
                    logger.info(f"INDIVIDUAL PROCESSING - Waiting {user_email_interval} seconds before next RFQ...")
                    time.sleep(user_email_interval)
                    
            except Exception as email_error:
                failed_sends += 1
                error_msg = f"RFQ {item['rfq_unique_id']} exception: {str(email_error)}"
                logger.error(f"INDIVIDUAL PROCESSING - {error_msg}")
                send_errors.append(error_msg)
        
        logger.info(f"INDIVIDUAL PROCESSING - STEP 2 COMPLETE: {successful_sends} emails sent, {failed_sends} failed")
        
        # ========== STEP 3: ONLY IF EMAIL SUCCEEDED, FINALIZE SEQUENCE & SAVE RFQ ==========
        logger.info(f"INDIVIDUAL PROCESSING - STEP 3: Conditional RFQ creation based on email success")
        
        rfq_ids_for_linking = []
        
        if successful_sends > 0:
            logger.info(f"INDIVIDUAL PROCESSING - Email(s) sent successfully, now FINALIZING SEQUENCE and SAVING RFQs")
            
            try:
                for rfq_data in rfq_ids_to_generate:
                    solicitation = rfq_data['solicitation']
                    rfq_unique_id = rfq_data['rfq_unique_id']
                    next_sequence = rfq_data['next_sequence']
                    
                    # STEP 3A: FINALIZE SEQUENCE (only after email succeeds)
                    try:
                        rfq_template.finalize_sequence_after_success(next_sequence)
                        logger.info(f"INDIVIDUAL PROCESSING - Finalized sequence to {next_sequence} for RFQ {rfq_unique_id}")
                    except Exception as seq_error:
                        logger.error(f"INDIVIDUAL PROCESSING - Error finalizing sequence: {seq_error}")
                    
                    # STEP 3B: CREATE RFQ with pre-generated unique_id
                    rfq = create_rfq(solicitation, existing_oem, created_by_user, rfq_unique_id)
                    
                    if rfq:
                        rfq_ids_for_linking.append(rfq.id)
                        logger.info(f"INDIVIDUAL PROCESSING - Saved RFQ {rfq_unique_id} to database")
                    else:
                        logger.error(f"INDIVIDUAL PROCESSING - Failed to save RFQ {rfq_unique_id} to database")
                        successful_sends -= 1
                        failed_sends += 1
                        send_errors.append(f"Failed to save RFQ {rfq_unique_id}")
                        
            except Exception as save_error:
                logger.error(f"INDIVIDUAL PROCESSING - Error saving RFQs to database: {save_error}")
                mark_solicitations_as_failed(valid_record_ids, created_by_user, f"RFQ save error: {str(save_error)}")
                return False
            
            logger.info(f"INDIVIDUAL PROCESSING - Successfully finalized sequences and saved {len(rfq_ids_for_linking)} RFQs to database")
            
            # NOW mark solicitations as sent with RFQ links
            try:
                mark_solicitations_as_sent(valid_record_ids, created_by_user, rfq_ids_for_linking)
                logger.info(f"INDIVIDUAL PROCESSING - Successfully marked {len(valid_record_ids)} solicitations as SENT")
                logger.info(f"INDIVIDUAL PROCESSING - STEP 3 COMPLETE: All steps successful for CAGE {cage_code}")
                return True
            except Exception as mark_sent_error:
                logger.error(f"INDIVIDUAL PROCESSING - Error marking as sent: {mark_sent_error}")
                return False
        else:
            logger.error(f"INDIVIDUAL PROCESSING - All emails failed for CAGE {cage_code}, NOT finalizing any sequences")
            
            # Mark as failed
            try:
                mark_solicitations_as_failed(valid_record_ids, created_by_user, f"All emails failed: {'; '.join(send_errors)}")
                logger.info(f"INDIVIDUAL PROCESSING - Successfully marked {len(valid_record_ids)} solicitations as FAILED")
            except Exception as mark_failed_error:
                logger.error(f"INDIVIDUAL PROCESSING - Error marking as failed: {mark_failed_error}")
            
            return False
            
    except Exception as e:
        logger.error(f"INDIVIDUAL PROCESSING - EXCEPTION in process_individual_solicitation for CAGE {cage_code}: {e}")
        logger.error(f"INDIVIDUAL PROCESSING - CLEANUP: Marking {len(record_ids)} solicitations as failed due to exception")
        
        try:
            mark_solicitations_as_failed(record_ids, created_by_user, f"Processing exception: {str(e)}")
            logger.info(f"INDIVIDUAL PROCESSING - Successfully marked {len(record_ids)} solicitations as FAILED due to exception")
        except Exception as cleanup_error:
            logger.error(f"INDIVIDUAL PROCESSING - CRITICAL: Even cleanup failed for {record_ids}: {cleanup_error}")
        
        return False

def process_solicitations_progressively_individual(original_ids, user_data, mail_data, auto_mode, username, created_by_user):
    """
    ENHANCED: Process solicitations with more frequent stop checking
    """
    try:
        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Starting for user {created_by_user.username}")
        if db_logger:
            db_logger.log_processing_start(original_ids, 'individual')
        
        # IMMEDIATE STOP CHECK AT START
        if check_user_stop_requested(created_by_user):
            logger.info(f"STOP DETECTED IMMEDIATELY at start - user already requested stop")
            return handle_user_stop_gracefully(created_by_user, original_ids, 0, [], len(original_ids))
        
        # Reset any stale processing status first
        reset_stale_processing_status(created_by_user)
        
        # Get initial remaining IDs (excludes sent, but includes failed for retry)
        current_ids, already_sent, failed = get_remaining_solicitation_ids(original_ids, created_by_user)
        
        # STOP CHECK AFTER GETTING INITIAL IDS
        if check_user_stop_requested(created_by_user):
            logger.info(f"STOP DETECTED after getting initial IDs")
            return handle_user_stop_gracefully(created_by_user, current_ids, 0, [], len(original_ids))
        
        if not current_ids:
            logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - No solicitations remaining to process for user {created_by_user.username}")
            return {
                'total_requested': len(original_ids),
                'successfully_sent': len(already_sent),
                'failed': len(failed),
                'remaining': 0,
                'status': 'completed'
            }
        
        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Starting with {len(current_ids)} IDs for user {created_by_user.username}")
        
        # Get user's email interval
        user_email_interval = get_user_email_interval(created_by_user)
        
        # Process in batches until all are done
        total_processed = 0
        total_failed = 0
        processing_rounds = 0
        max_rounds = 10  # Prevent infinite loops
        session_failed_ids = []  # Track IDs that failed in THIS session
        
        while current_ids and processing_rounds < max_rounds:
            processing_rounds += 1
            
            # MANDATORY STOP CHECK AT START OF EACH ROUND
            if check_user_stop_requested(created_by_user):
                logger.info(f"USER STOP DETECTED at round {processing_rounds}")
                return handle_user_stop_gracefully(created_by_user, current_ids, processing_rounds, session_failed_ids, len(original_ids))
            
            logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Round {processing_rounds}")
            logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Processing IDs: {current_ids[:10]}{'...' if len(current_ids) > 10 else ''}")
            
            # Get individual solicitation data (NO grouping by CAGE code)
            individual_groups = get_solicitations_data_individual(current_ids, created_by_user)
            
            # STOP CHECK AFTER GETTING DATA
            if check_user_stop_requested(created_by_user):
                logger.info(f"USER STOP DETECTED after getting solicitation data in round {processing_rounds}")
                return handle_user_stop_gracefully(created_by_user, current_ids, processing_rounds, session_failed_ids, len(original_ids))
            
            if not individual_groups:
                logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - No valid solicitations found for round {processing_rounds}")
                break
            
            # Process each individual solicitation
            round_processed = 0
            round_failed = 0
            
            for idx, (unique_key, records) in enumerate(individual_groups.items()):
                # STOP CHECK BEFORE PROCESSING EACH SOLICITATION (MOST FREQUENT CHECK)
                if check_user_stop_requested(created_by_user):
                    logger.info(f"USER STOP DETECTED during individual processing (item {idx+1}/{len(individual_groups)})")
                    return handle_user_stop_gracefully(created_by_user, current_ids, processing_rounds, session_failed_ids, len(original_ids))
                
                individual_record_ids = [record['id'] for record in records]
                
                try:
                    # Should only have 1 record per group in individual mode
                    cage_code = records[0]['cage']
                    sol_id = records[0]['id']
                    
                    logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Round {processing_rounds}, Processing individual solicitation {sol_id} for CAGE {cage_code} ({idx+1}/{len(individual_groups)})")
                    
                    # Check and lock for sending
                    safe_to_send_ids = check_and_lock_solicitations_for_sending(individual_record_ids, created_by_user)
                    
                    if not safe_to_send_ids:
                        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - No safe IDs for solicitation {sol_id}")
                        continue
                    
                    # Filter records to only include safe ones
                    safe_records = [r for r in records if r['id'] in safe_to_send_ids]
                    
                    # Process the individual solicitation
                    success = process_individual_solicitation(cage_code, safe_records, created_by_user, user_data, mail_data, user_email_interval)
                    
                    if success:
                        round_processed += len(safe_to_send_ids)
                        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Successfully processed solicitation {sol_id} for CAGE {cage_code}")
                        
                        # IMMEDIATE REMOVAL: Remove successful IDs from current_ids
                        current_ids = [cid for cid in current_ids if cid not in safe_to_send_ids]
                        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Removed successful IDs, remaining: {len(current_ids)}")
                        
                    else:
                        round_failed += len(safe_to_send_ids)
                        logger.error(f"INDIVIDUAL PROGRESSIVE PROCESSING - Failed to process solicitation {sol_id} for CAGE {cage_code}")
                        
                        # IMMEDIATE REMOVAL: Remove failed IDs from current session to prevent infinite loops
                        session_failed_ids.extend(safe_to_send_ids)
                        current_ids = [cid for cid in current_ids if cid not in safe_to_send_ids]
                        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Removed failed IDs from current session, remaining: {len(current_ids)}")
                    
                    # STOP CHECK AFTER PROCESSING EACH ITEM
                    if check_user_stop_requested(created_by_user):
                        logger.info(f"USER STOP DETECTED after processing solicitation {sol_id}")
                        return handle_user_stop_gracefully(created_by_user, current_ids, processing_rounds, session_failed_ids, len(original_ids))
                    
                    # Add delay between individual solicitations (with stop check during sleep)
                    if idx < len(individual_groups) - 1:  # Don't sleep after last item
                        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Waiting {user_email_interval} seconds before next solicitation...")
                        
                        # Sleep in small chunks to allow stop detection during sleep
                        sleep_chunks = max(1, user_email_interval // 5)  # Sleep in 5 chunks
                        chunk_size = user_email_interval / sleep_chunks
                        
                        for sleep_chunk in range(int(sleep_chunks)):
                            time.sleep(chunk_size)
                            # Check for stop during sleep
                            if check_user_stop_requested(created_by_user):
                                logger.info(f"USER STOP DETECTED during sleep between solicitations")
                                return handle_user_stop_gracefully(created_by_user, current_ids, processing_rounds, session_failed_ids, len(original_ids))
                        
                except Exception as e:
                    # CRITICAL FIX: Clean up processing status for ANY exception
                    logger.error(f"INDIVIDUAL PROGRESSIVE PROCESSING - EXCEPTION processing {unique_key}: {e}")
                    logger.error(f"INDIVIDUAL PROGRESSIVE PROCESSING - CLEANUP: Marking {len(individual_record_ids)} solicitations as failed due to outer exception")
                    
                    try:
                        mark_solicitations_as_failed(individual_record_ids, created_by_user, f"Outer processing exception: {str(e)}")
                        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Successfully marked {len(individual_record_ids)} as FAILED due to exception")
                    except Exception as cleanup_error:
                        logger.error(f"INDIVIDUAL PROGRESSIVE PROCESSING - CRITICAL: Cleanup failed for {individual_record_ids}: {cleanup_error}")
                    
                    # Remove from current session to prevent infinite loops
                    session_failed_ids.extend(individual_record_ids)
                    current_ids = [cid for cid in current_ids if cid not in individual_record_ids]
                    logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Removed exception IDs from current session, remaining: {len(current_ids)}")
                    continue
            
            total_processed += round_processed
            total_failed += round_failed
            
            logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Round {processing_rounds} complete:")
            logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Processed: {round_processed}, Failed: {round_failed}")
            logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Remaining IDs: {len(current_ids)}")
            logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Total session failures: {len(session_failed_ids)}")
            
            # STOP CHECK AFTER ROUND COMPLETION
            if check_user_stop_requested(created_by_user):
                logger.info(f"USER STOP DETECTED after round {processing_rounds} completion")
                return handle_user_stop_gracefully(created_by_user, current_ids, processing_rounds, session_failed_ids, len(original_ids))
            
            # Update current_ids with fresh data from database (double-check)
            current_ids, newly_sent, newly_failed = get_remaining_solicitation_ids(current_ids, created_by_user)
            
            if newly_sent:
                logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Found additional sent IDs: {newly_sent}")
                total_processed += len(newly_sent)
            
            if not current_ids:
                logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - All IDs processed or failed! Breaking out of loop.")
                break
        
        # Final summary
        final_remaining, final_sent, final_failed = get_remaining_solicitation_ids(original_ids, created_by_user)
        
        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - FINAL SUMMARY:")
        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Total requested: {len(original_ids)}")
        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Successfully sent: {len(final_sent)}")
        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Failed (database): {len(final_failed)}")
        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Failed this session: {len(session_failed_ids)}")
        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Remaining: {len(final_remaining)}")
        logger.info(f"INDIVIDUAL PROGRESSIVE PROCESSING - Processing rounds: {processing_rounds}")
        
        return {
            'total_requested': len(original_ids),
            'successfully_sent': len(final_sent),
            'failed': len(session_failed_ids),  # Report session failures
            'remaining': len(final_remaining),
            'status': 'completed' if len(final_remaining) == 0 else 'partial',
            'rounds': processing_rounds,
            'session_failed_ids': session_failed_ids  # Track what failed this session
        }
        
    except Exception as e:
        # CRITICAL FIX: Global exception handler with stop check
        logger.error(f"INDIVIDUAL PROGRESSIVE PROCESSING - GLOBAL EXCEPTION: {e}")
        
        # Check if this was a stop request that caused the exception
        if check_user_stop_requested(created_by_user):
            logger.info(f"GLOBAL EXCEPTION was likely due to stop request - handling gracefully")
            return handle_user_stop_gracefully(created_by_user, original_ids, processing_rounds, session_failed_ids, len(original_ids))
        
        # Clean up ALL remaining processing records for this user
        try:
            all_processing = SolicitationEmailStatus.objects.filter(
                user=created_by_user,
                email_status='processing'
            )
            
            processing_count = all_processing.count()
            if processing_count > 0:
                all_processing.update(email_status='failed')
                logger.error(f"INDIVIDUAL PROGRESSIVE PROCESSING - GLOBAL CLEANUP: Marked {processing_count} processing records as failed")
            
        except Exception as global_cleanup_error:
            logger.error(f"INDIVIDUAL PROGRESSIVE PROCESSING - CRITICAL: Global cleanup failed: {global_cleanup_error}")
        
        return {
            'total_requested': len(original_ids),
            'successfully_sent': 0,
            'failed': len(original_ids),
            'remaining': len(original_ids),
            'status': 'error',
            'error': str(e)
        }
      
def generate_unique_id(oem, created_by_user):
    """
    Generates a unique ID for an RFQ using user's configurable template.
    Falls back to default format if no template is configured.
    """
    try:
        # Get user's RFQ ID template configuration
        template = RFQIDTemplate.objects.get(user=created_by_user)
        
        # Generate RFQ ID using template
        rfq_unique_id = template.generate_rfq_id(
            user=created_by_user,
            oem_cage_code=oem.cage,
            solicitation_id=oem.id  # Use OEM ID as fallback
        )
        
        logger.info(f"Generated RFQ ID using user template: {rfq_unique_id}")
        return rfq_unique_id
        
    except RFQIDTemplate.DoesNotExist:
        # User has no custom template configured - create default one
        logger.info(f"No RFQ ID template found for user {created_by_user.username}, creating default template")
        
        try:
            # Create default template
            default = RFQIDTemplate.get_default_template()
            template = RFQIDTemplate.objects.create(
                user=created_by_user,
                components=default['components'],
                separator=default['separator'],
                date_format=default['date_format'],
                sequence_padding=default['sequence_padding'],
                sequence_reset_period=default['sequence_reset_period']
            )
            
            # Generate using newly created template
            rfq_unique_id = template.generate_rfq_id(
                user=created_by_user,
                oem_cage_code=oem.cage,
                solicitation_id=oem.id
            )
            
            logger.info(f"Created default template and generated RFQ ID: {rfq_unique_id}")
            return rfq_unique_id
            
        except Exception as e:
            logger.error(f"Failed to create default template: {e}")
            # Fallback to hardcoded format as last resort
            return _generate_rfq_id_fallback(oem, created_by_user)
    
    except Exception as e:
        logger.error(f"Error generating RFQ ID from template: {e}")
        # Fallback to hardcoded format
        return _generate_rfq_id_fallback(oem, created_by_user)


def _generate_rfq_id_fallback(oem, created_by_user):
    """
    Fallback RFQ ID generation using original hardcoded format.
    Used only if template system fails.
    """
    logger.warning("Using fallback hardcoded RFQ ID format")
    
    current_date = now().strftime("%m%d%y")
    
    # Get company initials from CustomUser
    if created_by_user.company_initial and created_by_user.company_initial.strip():
        company_prefix = created_by_user.company_initial.upper()
    else:
        if created_by_user.companyName and len(created_by_user.companyName) >= 3:
            company_prefix = created_by_user.companyName[:3].upper()
        else:
            company_prefix = "COM"
    
    company_prefix_dla = f"{company_prefix}-DLA"
    cage_code = oem.cage.upper()
    
    # Count all existing RFQs for the user
    rfq_count = RFQ.objects.filter(created_by=created_by_user).count()
    sequence_number = rfq_count + 1
    formatted_sequence = f"{sequence_number:06d}"
    
    # Generate fallback unique ID
    unique_id = f"{company_prefix_dla}-{current_date}-{cage_code}-{formatted_sequence}"
    return unique_id

def create_rfq(solicitation, oem, created_by, rfq_unique_id=None):
    """
    Creates an RFQ entry in the database.
    
    UPDATED: Now accepts pre-generated RFQ ID as parameter
    
    Args:
        solicitation: Solicitation object
        oem: OEM object
        created_by: User object
        rfq_unique_id: Pre-generated RFQ ID (optional - for new flow)
    """
    try:
        # If rfq_unique_id provided, use it (new flow)
        # Otherwise generate it (backward compatibility)
        if rfq_unique_id:
            unique_id = rfq_unique_id
            logger.info(f"Using provided unique_id: {unique_id}")
        else:
            unique_id = generate_unique_id(oem, created_by)
            logger.info(f"Generated unique_id: {unique_id}")
 
        # Create the RFQ with the unique ID
        rfq = RFQ.objects.create(
            solicitation=solicitation,
            oem=oem,
            created_by=created_by,
            unique_id=unique_id
        )
        logger.info(f"RFQ created successfully: {rfq}")
        
        if db_logger:
            from solicitations.utils.logging_utils import log_to_database
            log_to_database(
                message=f"Created RFQ {rfq.unique_id} for solicitation {rfq.solicitation.id}",
                level='INFO',
                category='processing',
                user=created_by,
                rfq_id=rfq.id,
                cage_code=rfq.oem.cage,
                solicitation_id=rfq.solicitation.id,
                extra_data={
                    'rfq_unique_id': rfq.unique_id,
                    'oem_name': rfq.oem.name,
                    'nomenclature': rfq.solicitation.nomenclature
                }
            )
        return rfq
    except IntegrityError as e:
        logger.info(f"Failed to create RFQ due to an integrity error: {e}")
        return None
    except Exception as e:
        logger.info(f"An unexpected error occurred: {e}")
        return None
 

def save_oem_data(cage_code, organization_name, street_name, city_name, postal_code, phone, fax, email):
    """Function to save data to OEM Model - Updated to respect manual override with safe field handling"""
    try:
        # Validate email - replace empty emails with a default
        if not email or not email.strip():
            email = "williamdemo01@gmail.com"  # Default email
            logger.info(f"Warning: Empty email detected for {organization_name}, using default email")
            
        # Use `filter` to fetch all matching records and take the first one
        oem_record = OEM.objects.filter(cage=cage_code).first()
        if oem_record:
            # IMPORTANT: Check if this OEM is protected from script updates
            try:
                if hasattr(oem_record, 'is_protected_from_script_updates') and oem_record.is_protected_from_script_updates():
                    logger.info(f"OEM record for CAGE Code {cage_code} is protected from script updates. Skipping update.")
                    data_source = getattr(oem_record, 'data_source', 'unknown')
                    manual_override = getattr(oem_record, 'manual_override', False)
                    logger.info(f"Protection reason: data_source={data_source}, manual_override={manual_override}")
                    return oem_record  # Return existing record without updating
            except AttributeError:
                # Fields don't exist yet, proceed with update
                logger.info(f"Protection fields not found for {cage_code}, proceeding with update")
            
            # Update the existing record only if not protected
            logger.info(f"Updating OEM record for CAGE Code {cage_code} (script-generated data)")
            oem_record.name = organization_name
            oem_record.street = street_name
            oem_record.city = city_name
            oem_record.postal_code = postal_code
            oem_record.phone = phone
            oem_record.fax = fax
            oem_record.email = email
            
            # Only set protection fields if they exist
            if hasattr(oem_record, 'data_source'):
                oem_record.data_source = 'script'
            if hasattr(oem_record, 'manual_override'):
                oem_record.manual_override = False
                
            oem_record.save()
            logger.info(f"OEM record updated for CAGE Code {cage_code}.")
        else:
            # Create a new record if none exists (always script-generated)
            logger.info(f"Creating new OEM record for CAGE Code {cage_code} (script-generated)")
            
            # Prepare creation kwargs
            create_kwargs = {
                'cage': cage_code,
                'name': organization_name,
                'street': street_name,
                'city': city_name,
                'postal_code': postal_code,
                'phone': phone,
                'fax': fax,
                'email': email,
            }
            
            # Add protection fields if the model supports them
            try:
                # Test if the fields exist by checking the model fields
                field_names = [f.name for f in OEM._meta.get_fields()]
                if 'data_source' in field_names:
                    create_kwargs['data_source'] = 'script'
                if 'manual_override' in field_names:
                    create_kwargs['manual_override'] = False
            except:
                pass
            
            oem_record = OEM.objects.create(**create_kwargs)
            logger.info(f"OEM record created for CAGE Code {cage_code}.")

            if 'db_logger' in globals() and db_logger:
                from solicitations.utils.logging_utils import log_to_database
                log_to_database(
                    message=f"Created OEM for CAGE {cage_code}: {organization_name}",
                    level='INFO',
                    category='oem',
                    cage_code=cage_code,
                    extra_data={
                        'oem_name': organization_name,
                        'auto_created': True,
                        'email': email,
                        'city': city_name
                    }
                 )
        
        return oem_record
        
    except Exception as e:
        logger.info(f"Error saving data for CAGE Code {cage_code}: {e}")
        return None

def extract_oem_data(cage_code):
    """Extract OEM data from the Solicitation model for a given CAGE code - Updated with protection logic"""
    try:
        # Check if OEM already exists and is protected
        existing_oem = OEM.objects.filter(cage=cage_code).first()
        if existing_oem:
            try:
                if hasattr(existing_oem, 'is_protected_from_script_updates') and existing_oem.is_protected_from_script_updates():
                    logger.info(f"OEM for CAGE code {cage_code} is protected from script updates. Using existing data.")
                    return {
                        'organization_name': existing_oem.name,
                        'street_name': existing_oem.street,
                        'city': existing_oem.city,
                        'postal_code': existing_oem.postal_code,
                        'phone': existing_oem.phone,
                        'fax': existing_oem.fax,
                        'email': existing_oem.email
                    }
            except AttributeError:
                # Protection fields don't exist, proceed with normal logic
                logger.info(f"Protection fields not available for {cage_code}, proceeding with extraction")
        
        # Get the most recent solicitation for this CAGE code
        solicitation = Solicitation.objects.filter(cage=cage_code).order_by('-scraped_date').first()
        
        if not solicitation:
            logger.info(f"No solicitation found for CAGE code {cage_code}")
            if existing_oem:
                # Return existing OEM data if no solicitation found
                return {
                    'organization_name': existing_oem.name,
                    'street_name': existing_oem.street,
                    'city': existing_oem.city,
                    'postal_code': existing_oem.postal_code,
                    'phone': existing_oem.phone,
                    'fax': existing_oem.fax,
                    'email': existing_oem.email
                }
            return None
            
        logger.info(f"Found solicitation data for CAGE code {cage_code}")
        
        # Save data to the OEM model (this will respect protection)
        oem_record = save_oem_data(
            cage_code=cage_code,
            organization_name=solicitation.organization_name,
            street_name=solicitation.street_name,
            city_name=solicitation.city,
            postal_code=solicitation.postal_code,
            phone=solicitation.phone,
            fax=solicitation.fax,
            email=solicitation.email
        )
        
        if oem_record:
            return {
                'organization_name': oem_record.name,
                'street_name': oem_record.street,
                'city': oem_record.city,
                'postal_code': oem_record.postal_code,
                'phone': oem_record.phone,
                'fax': oem_record.fax,
                'email': oem_record.email
            }
        else:
            return None
            
    except Exception as e:
        logger.info(f"Error extracting data for CAGE Code {cage_code}: {e}")
        return None

def _item_cell_value(attr, item, row_index):
    """Return cell value for one items-table column (used when building table from visible columns)."""
    if attr == 'show_items_col_index':
        return f'{row_index:04d}'
    if attr == 'show_items_col_nsn':
        return item.get('NSN', '')
    if attr == 'show_items_col_nomen':
        return item.get('nomenclature', '')
    if attr == 'show_items_col_part_no':
        return item.get('part_number', '')
    if attr == 'show_items_col_solicitation_no':
        return item.get('solicitation_number', '')
    if attr == 'show_items_col_qty_unit':
        qty = item.get('quantity', '1')
        unit = item.get('unit', 'EA')
        return f'{qty} {unit}'
    if attr == 'show_items_col_unit_price':
        return ''
    if attr == 'show_items_col_total_price':
        return ''
    return ''


def _generate_items_table_script(template_config, items, styles):
    """Generate items table with actual items. Only visible columns in order - e.g. if # is hidden, NSN is first."""
    html_parts = []
    if not template_config.show_items_table or not items:
        return html_parts
    visible = _items_table_visible_columns(template_config)
    if not visible:
        return html_parts
    html_parts.append(f'<table width="100%" cellpadding="{template_config.table_cell_padding}" cellspacing="{template_config.table_cell_spacing}" border="1" style="margin-top: 2px; {styles["table_style"]}">')
    html_parts.append('<tr>')
    for attr, label in visible:
        html_parts.append(f'<th style="{styles["header_cell_style"]}">{label}</th>')
    html_parts.append('</tr>')
    for i, item in enumerate(items, 1):
        html_parts.append('<tr>')
        for attr, _ in visible:
            val = _item_cell_value(attr, item, i)
            html_parts.append(f'<td style="{styles["cell_style"]}">{val}</td>')
        html_parts.append('</tr>')
    html_parts.append('</table>')
    return html_parts


def _replace_items_table_in_html(html_str, new_items_table_str):
    """
    Find the layout's sample items table (the one containing 'Total Price (USD)' or 'Qty/Unit' in header)
    and replace it with the real items table. Works regardless of which columns are visible.
    """
    import re
    # Markers that appear only in the items table header
    markers = ['Total Price (USD)', 'Qty/Unit', 'Unit Price (USD)']
    # Match a full <table>...</table> block (non-greedy inner so we get one table)
    # We find the table that contains one of the markers
    table_pattern = re.compile(
        r'<table\s[^>]*>.*?</table>',
        re.DOTALL
    )
    for m in table_pattern.finditer(html_str):
        block = m.group(0)
        if any(marker in block for marker in markers):
            return html_str[:m.start()] + new_items_table_str + html_str[m.end():]
    return html_str


def generate_email_html_with_config_script(template_config, data, items):
    """
    Generate email HTML using user's template configuration.
    Uses layout functions from views.py, adapted for the script with real items.
    """
    # Get styles using helper function
    styles = _get_template_styles(template_config)
    
    # Start building HTML
    html_parts = []
    html_parts.append(f'<body style="{styles["body_style"]}">')
    html_parts.append(f'<table align="center" cellpadding="0" cellspacing="0" border="0" width="760" style="max-width: 700px;">')
    html_parts.append('<tr><td style="padding: 10px;">')
    
    # Get layout style (default to classic if not set)
    layout_style = getattr(template_config, 'layout_style', 'classic')

    # Header banner layout includes its own top banner and salutation/body block.
    # To avoid duplication, we skip the generic salutation/body wrapper here.
    if layout_style != 'header_banner':
        html_parts.append(f'<div style="background-color: {template_config.background_color}; border-radius: 5px; font-size: {template_config.font_size};">')
        html_parts.append(f'<p style="margin: 0; padding: 0; color: {styles["text_color"]};">{data.get("salutation", "Dear Mr/Ms")},<br>{data.get("body", "I hope this message finds you well...")}</p>')
        html_parts.append('</div><br>')
    
    # Generate layout-specific content
    if layout_style == 'two_column':
        layout_html = generate_layout_two_column(template_config, data, styles)
    elif layout_style == 'card_based':
        layout_html = generate_layout_card_based(template_config, data, styles)
    elif layout_style == 'compact':
        layout_html = generate_layout_compact(template_config, data, styles)
    elif layout_style == 'modern_grid':
        layout_html = generate_layout_modern_grid(template_config, data, styles)
    elif layout_style == 'header_banner':
        layout_html = generate_layout_header_banner(template_config, data, styles)
    else:  # default to classic
        layout_html = generate_layout_classic(template_config, data, styles)
    
    # Replace sample items table with real items table
    layout_html_str = '\n'.join(layout_html)
    items_table_html = _generate_items_table_script(template_config, items, styles)
    items_table_str = '\n'.join(items_table_html)

    if items_table_str and template_config.show_items_table:
        # Find the items table by content (works even when # or other columns are hidden)
        layout_html_str = _replace_items_table_in_html(layout_html_str, items_table_str)

    html_parts.append(layout_html_str)
    
    html_parts.append('</td></tr></table></body>')

    html_str = '\n'.join(html_parts)
    try:
        overrides = EmailTextStyleOverride.objects.filter(template_config=template_config)
        html_str = apply_text_style_overrides_to_html(html_str, overrides)
    except Exception:
        # Never fail email generation due to override issues.
        pass

    return html_str


def send_individual_email_with_cc_spam_safe(oem_emails, items, user_data, oem_info, sent_at=None, user=None):
    """
    Send a single email with individual items to multiple emails (TO + CC)
    UPDATED: In testing mode, send to logged-in user instead of OEM
    """
    if not sent_at:
        sent_at = now()
    due_date = sent_at + timedelta(days=3) 
        
    # Get user's email configuration
    from_email = None
    email_host = None
    email_port = None
    email_username = None
    email_password = None
    use_tls = True
    
    try:
        from solicitations.models import UserEmailConfig
        user_config = UserEmailConfig.objects.filter(user=user, is_active=True).first()
        
        if user_config:
            from_email = user_config.default_from_email or user_config.email_host_user
            email_host = user_config.email_host
            email_port = user_config.email_port
            email_username = user_config.email_host_user
            email_password = user_config.email_host_password
            use_tls = user_config.email_use_tls
            logger.info(f"Using user's configured email settings: {email_host}:{email_port}")
        else:
            logger.error(f"No email configuration found for user {user.username}")
            return False
            
    except Exception as e:
        logger.error(f"Error getting user email config: {e}")
        return False

    # Validate required email settings
    if not all([from_email, email_host, email_port, email_username, email_password]):
        logger.error("Incomplete email configuration - missing required fields")
        return False

    # TESTING MODE LOGIC: Override recipients
    testing_mode = is_testing_mode()
    
    if testing_mode:
        # TESTING MODE: Send to sender email (email_host_user) instead of OEM
        # Use the email address configured for sending emails, not the registration email
        primary_to_email = from_email  # This is already set to user_config.default_from_email or user_config.email_host_user
        cc_emails = []  # No CC in testing mode
        logger.info(f"TESTING MODE: Redirecting email from OEM ({oem_emails}) to sender email ({primary_to_email})")
        logger.info(f"TESTING MODE: Original OEM emails would have been: {oem_emails}")
    else:
        # PRODUCTION MODE: Send to actual OEM emails
        if len(oem_emails) == 1:
            primary_to_email = oem_emails[0]  # Send to actual OEM email
            cc_emails = []
            logger.info(f"PRODUCTION MODE: Sending to OEM {primary_to_email}")
        else:
            primary_to_email = oem_emails[0]  # Send to first OEM email
            cc_emails = oem_emails[1:]  # Rest as CC to other OEM emails
            logger.info(f"PRODUCTION MODE: TO={primary_to_email}, CC={cc_emails}")

    try:
        rfq_unique_id = items[0]['rfq_unique_id'] if items else 'N/A'
        
        # Prepare clean URLs and emails (remove protocols and make them non-clickable)
        clean_email = user_data.get('email', '').replace('mailto:', '')
        clean_website = user_data.get('website', '').replace('http://', '').replace('https://', '')
        
        # For template display, show all OEM emails (even in testing mode, for reference)
        all_oem_emails_display = ', '.join(oem_emails)
        clean_oem_email = all_oem_emails_display.replace('mailto:', '')
        
        # TESTING MODE: Add testing notice to subject and body
        if testing_mode:
            testing_notice = f"\n\n**TESTING MODE NOTICE**\nThis email was redirected from the intended OEM recipient(s): {', '.join(oem_emails)}\nIn production, this would go to the actual OEM email address(es).\n"
        else:
            testing_notice = ""
        
        # Handle mail data
        mail_content = {
            'heading': 'Request for Quotation',
            'body': f'I hope this message finds you well. We are requesting a quotation for the items listed below.{testing_notice}',
            'salutation': 'Dear Supplier'
        }
        if 'mail_data' in globals() and isinstance(mail_data, dict):
            mail_content.update(mail_data)
            # Add testing notice to custom body if in testing mode
            if testing_mode and 'body' in mail_data:
                mail_content['body'] = f"{mail_data['body']}{testing_notice}"
        
        # Process logo URL
        try:
            if user.logo:
                logo_url = user.logo.url
                if not logo_url.startswith(('http://', 'https://')):
                    logo_url = f"{settings.BASE_URL}{logo_url}"
            else:
                logo_url = ''
        except Exception as e:
            logger.info(f"Error getting logo: {e}")
            logo_url = ''
        
        # Check if user has custom template configuration
        try:
            template_config = EmailTemplateConfig.objects.get(user=user)
            logger.info(f"Using custom email template configuration for user {user.username}")
            use_custom_template = True
        except EmailTemplateConfig.DoesNotExist:
            logger.info(f"No custom template config found for user {user.username}, using default template")
            use_custom_template = False
        
        # Prepare data for template
        template_data = {
            'salutation': mail_content['salutation'],
            'body': mail_content['body'],
            # Resale notice row (MailTemplate.heading), merged from mail_data in mail_content
            'heading': (mail_content.get('heading') or '').strip() or DEFAULT_RESALE_NOTICE_TEXT,
            'sent_at': sent_at.strftime('%m/%d/%Y'),
            'due_date': due_date.strftime('%m/%d/%Y'),
            'rfq_unique_id': rfq_unique_id,
            'organization_name': oem_info.get('organization_name', ''),
            'cage': oem_info.get('cage', ''),
            'fax': format_phone_number(oem_info.get('fax', '')),
            'oem_phone': format_phone_number(oem_info.get('phone', '')),
            'oem_email': clean_oem_email,
            'personal_email': user_data.get('personal_email', ''),
            'inspection_point': items[0].get('inspection_point', '-') if items else '-',
            'user_first_name': user_data.get('first_name', ''),
            'user_last_name': user_data.get('last_name', ''),
            'user_title': user_data.get('title', ''),
            'companyName': user_data.get('companyName', ''),
            'address': user_data.get('address', ''),
            'phone': format_phone_number(user_data.get('phone', '')),
            'user_fax': format_phone_number(user_data.get('fax', '')),
            'email': clean_email,
            'company_website': clean_website,
            'logo_url': logo_url,
        }
        
        if use_custom_template:
            # Use custom template configuration
            email_content = generate_email_html_with_config_script(template_config, template_data, items)
        else:
            # Use default email.html template
            with open("email.html", "r") as file:
                email_template = file.read()
            
            # Create table rows for items with serial numbers
            item_rows = []
            logger.info(f"DEBUG: Received {len(items)} items for individual email generation")
            for i, item in enumerate(items, 1):
                logger.info(f"DEBUG: Item {i}: {item.get('nomenclature', 'N/A')} - NSN: {item.get('NSN', 'N/A')}")
                
                # Combine quantity and unit into a single column
                quantity = item.get('quantity', '1')
                unit = item.get('unit', 'EA')
                qty_unit_combined = f"{quantity} {unit}"
                
                solicitation_number = item.get('solicitation_number', '')
                row = f"""            <tr>
                <td>{i:04d}</td>
                <td>{item['NSN']}</td>
                <td>{item['nomenclature']}</td>
                <td>{item['part_number']}</td>
                <td>{solicitation_number}</td>
                <td>{qty_unit_combined}</td>
                <td></td>
                <td></td>
            </tr>"""
                item_rows.append(row)
            
            items_table = "\n".join(item_rows)
            
            # Replace template placeholders
            replacements = {
                "{sent_at}": template_data['sent_at'],
                "{due_date}": template_data['due_date'],
                "{organization_name}": template_data['organization_name'],
                "{cage}": template_data['cage'],
                "{fax}": template_data['fax'],
                "{oem_phone}": template_data['oem_phone'],
                "{oem_email}": template_data['oem_email'],
                "{email}": template_data['email'],
                "{phone}": template_data['phone'],
                "{address}": template_data['address'],
                "{companyName}": template_data['companyName'],
                "{user_fax}": template_data['user_fax'],
                "{personal_email}": template_data['personal_email'],
                "{user_title}": template_data['user_title'],
                "{user_first_name}": template_data['user_first_name'],
                "{user_last_name}": template_data['user_last_name'],
                "{rfq_unique_id}": template_data['rfq_unique_id'],
                "{company_website}": template_data['company_website'],
                "{ITEMS_ROWS}": items_table,
                "{inspection_point}": template_data['inspection_point'],
                "{heading}": mail_content['heading'],
                "{body}": mail_content['body'],
                "{salutation}": mail_content['salutation'],
                "{logo_url}": template_data['logo_url'],
            }

            # Apply all replacements
            email_content = email_template
            for placeholder, value in replacements.items():
                email_content = email_content.replace(placeholder, value)

        # Create email message using MIMEMultipart for better IMAP compatibility
        msg = MIMEMultipart('alternative')
        
        # Update subject for testing mode
        base_subject = f"Request for Quotation - {rfq_unique_id}"
        if testing_mode:
            msg['Subject'] = f"[TESTING MODE] {base_subject}"
        else:
            msg['Subject'] = base_subject
            
        msg['From'] = from_email
        msg['To'] = primary_to_email  # Will be user email in testing mode, OEM email in production
        
        # Add CC recipients if there are multiple emails (only in production mode)
        if cc_emails and not testing_mode:
            cc_emails_str = ', '.join(cc_emails)
            msg['Cc'] = cc_emails_str
            logger.info(f"CC TO: {cc_emails_str}")
        
        msg['Reply-To'] = from_email
        msg['X-Priority'] = '3'
        msg['X-MSMail-Priority'] = 'Normal'
        msg['X-Mailer'] = 'RFQ System'
        msg['Date'] = email.utils.formatdate(localtime=True)
        
        # Add custom headers for better deliverability
        msg['List-Unsubscribe'] = f'<mailto:{from_email}?subject=Unsubscribe>'
        
        # Add testing mode header
        if testing_mode:
            msg['X-Testing-Mode'] = 'True'
            msg['X-Original-Recipients'] = ', '.join(oem_emails)
        
        # Attach HTML content
        html_part = MIMEText(email_content, 'html', 'utf-8')
        msg.attach(html_part)

        # Prepare recipient list for SMTP
        if testing_mode:
            all_recipients = [primary_to_email]  # Just user email in testing
        else:
            all_recipients = [primary_to_email]  # Primary OEM email
            if cc_emails:
                all_recipients.extend(cc_emails)  # Add CC OEM emails

        # Send email using user's SMTP configuration
        smtp_success = False
        try:
            if testing_mode:
                logger.info(f"TESTING MODE: Sending email to logged-in user using {email_host}:{email_port}")
                logger.info(f"FROM: {from_email} TO: {primary_to_email} (User)")
                logger.info(f"Original OEM recipients would have been: {oem_emails}")
            else:
                logger.info(f"PRODUCTION MODE: Sending email to OEM using {email_host}:{email_port}")
                logger.info(f"FROM: {from_email} TO: {primary_to_email}")
                if cc_emails:
                    logger.info(f"CC: {cc_emails}")
            
            with smtplib.SMTP(email_host, email_port) as server:
                if use_tls:
                    server.starttls()
                
                # Login with user's credentials
                server.login(email_username, email_password)
                server.sendmail(from_email, all_recipients, msg.as_string())
                
                if testing_mode:
                        from solicitations.utils.logging_utils import log_to_database
                        log_to_database(
                            message=f"Email sent successfully to {primary_to_email} for CAGE {oem_info.get('cage')}",
                            level='INFO',
                            category='email',
                            user=user,
                            email_recipient=primary_to_email,
                            email_subject=msg['Subject'],
                            cage_code=oem_info.get('cage'),
                            email_status='sent',
                            extra_data={
                                'testing_mode': False,
                                'item_count': len(items),
                                'rfq_unique_id': items[0]['rfq_unique_id'] if items else 'N/A'
                           }
                        )
                else:
                    logger.info(f"PRODUCTION: RFQ email sent successfully to OEM ({len(all_recipients)} recipients)")
                    if db_logger:
                        from solicitations.utils.logging_utils import log_to_database
                        log_to_database(
                            message=f"Email sent successfully to {primary_to_email} for CAGE {oem_info.get('cage')}",
                            level='INFO',
                            category='email',
                            user=user,
                            email_recipient=primary_to_email,
                            email_subject=msg['Subject'],
                            cage_code=oem_info.get('cage'),
                            email_status='sent',
                            extra_data={
                                'testing_mode': False,
                                'item_count': len(items),
                                'rfq_unique_id': items[0]['rfq_unique_id'] if items else 'N/A'
                           }

                        )
                smtp_success = True
                
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP Authentication failed: {e}")
            if db_logger:
                db_logger.log_email_failed(
                recipient=primary_to_email,
                subject=msg['Subject'],
                error_msg=f"SMTP Authentication failed: {str(e)}",
                cage_code=oem_info.get('cage')
            )
            logger.error("Please check username and password in user email configuration")
            return False
        except smtplib.SMTPConnectError as e:
            logger.error(f"SMTP Connection failed: {e}")
            logger.error("Please check email host and port in user email configuration")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP Error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending email: {e}")
            return False
        
        # Save to sent folder if configured (works in both modes)
        if smtp_success and user_config.save_to_sent_folder:
            if testing_mode:
                logger.info("TESTING: Attempting to save email copy to email client sent folder...")
            else:
                logger.info("PRODUCTION: Attempting to save email copy to email client sent folder...")
            
            # Create a copy of the message for the sent folder
            sent_msg = MIMEMultipart('alternative')
            sent_msg['Subject'] = msg['Subject']
            sent_msg['From'] = from_email
            sent_msg['To'] = primary_to_email
            if cc_emails and not testing_mode:
                sent_msg['Cc'] = ', '.join(cc_emails)
            sent_msg['Reply-To'] = msg['Reply-To']
            sent_msg['X-Priority'] = msg['X-Priority']
            sent_msg['X-MSMail-Priority'] = msg['X-MSMail-Priority']
            sent_msg['X-Mailer'] = msg['X-Mailer']
            sent_msg['Date'] = msg['Date']
            sent_msg['List-Unsubscribe'] = msg['List-Unsubscribe']
            
            if testing_mode:
                sent_msg['X-Testing-Mode'] = 'True'
                sent_msg['X-Original-Recipients'] = ', '.join(oem_emails)
            
            # Attach the same content
            sent_html_part = MIMEText(email_content, 'html', 'utf-8')
            sent_msg.attach(sent_html_part)
            
            # Save to sent folder
            sent_saved = save_to_sent_folder(sent_msg, user_config)
            
            if sent_saved:
                logger.info(f"SUCCESS! Email copy saved to email client sent folder")
            else:
                logger.warning(f"Could not save email copy to sent folder (email still sent successfully)")
        elif smtp_success:
            mode_text = "TESTING" if testing_mode else "PRODUCTION"
            logger.info(f"{mode_text}: Email sent successfully (sent folder saving is disabled)")
        
        return smtp_success
            
    except FileNotFoundError:
        logger.error("Error: 'email.html' template not found")
        return False
    except Exception as e:
        logger.error(f"Email preparation failed: {e}")
        return False

def get_user_email_interval(user):
    """Get user's configured email interval in seconds"""
    try:
        from solicitations.models import UserEmailConfig
        user_config = UserEmailConfig.objects.filter(user=user, is_active=True).first()
        
        if user_config:
            interval = user_config.email_interval_seconds
            logger.info(f"User {user.username} has configured email interval: {interval} seconds")
            return interval
        else:
            logger.info(f"No email config found for user {user.username}, using default 10 seconds")
            return 10  # Default fallback
            
    except Exception as e:
        logger.error(f"Error getting user email interval: {e}")
        return 10  # Default fallback

# Load data using the existing function
data, user_data, solicitation_ids, mail_data, auto_mode, username, created_by_user = load_data_from_input()
# Setup database logging
db_logger, task_id, script_session_id = setup_database_logging(created_by_user, auto_mode)

# Log lock verification at start
lock_type = "automated" if auto_mode else "manual"
logger.info(f"SCRIPT START - Mode: {lock_type}, User: {created_by_user.username} (ID: {created_by_user.id})")

# Test mark_solicitations_as_sent function
#logger.info("Running test of mark_solicitations_as_sent function...")
#test_result = test_mark_solicitations_as_sent(created_by_user)
#logger.info(f"Test result: {'PASSED' if test_result else 'FAILED'}")
logger.info("Skipping test function in production mode")

# Use the individual progressive processing function (no consolidation)
result = process_solicitations_progressively_individual(
    solicitation_ids, 
    user_data, 
    mail_data, 
    auto_mode, 
    username, 
    created_by_user
)

# ===== After processing is done =====
completed_time = now()

# ===== Generate task_id =====
try:
    task_id = f"{username}-{uuid4().hex[:8]}"
except Exception as e:
    logger.error(f"Error generating task ID: {e}")
    task_id = f"rfq-{uuid4().hex[:8]}"

# ===== Save Summary to DB =====
try:
    summary = RFQTaskSummary.objects.create(
        task_id=task_id,
        user=created_by_user,
        requested_solicitations=result['total_requested'],
        total_successful_sent=result['successfully_sent'],
        total_failed=result['failed'],
        date=start_time.date(),
        start_time=start_time,
        completed_time=completed_time,
        processing_mode='automated' if auto_mode else 'manual'
    )
    logger.info(f"RFQTaskSummary saved for task {task_id}.")
except Exception as e:
    logger.error(f"Failed to save RFQTaskSummary: {e}")
    summary = None

# ===== Send Email Summary to Sender =====
def send_rfq_summary_email(summary):
    """
    Send RFQ summary email using inline hardcoded configuration
    This completely bypasses Django email settings to avoid conflicts
    """
    # CONFIGURE YOUR EMAIL HERE:
    SENDER_EMAIL = "info@gilgaltech.com"    
    SENDER_PASSWORD = "info@0213"     
    SENDER_NAME = "RFQ System"                  # Change this to your preferred sender name
    SMTP_HOST = "gilgaltech.com"               
    SMTP_PORT = 587                             # Change this if needed (587 for most providers)
    
    subject = f"[RFQ Summary] {summary.date} - {summary.status_display}"
    message = (
        f"Hi {summary.user.first_name},\n\n"
        f"Your RFQ task has completed.\n\n"
        f"Summary:\n"
        f"- Total Requested: {summary.requested_solicitations}\n"
        f"- Successfully Sent: {summary.total_successful_sent}\n"
        f"- Failed: {summary.total_failed}\n"
        f"- Duration: {summary.duration_formatted}\n"
        f"- Status: {summary.status_display}\n\n"
        f"Best regards,\n"
        f"{SENDER_NAME}\n"
    )

    try:
        import smtplib
        from email.mime.text import MIMEText
        
        # Create email message
        msg = MIMEText(message)
        msg['Subject'] = subject
        msg['From'] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg['To'] = summary.user.email
        msg['Reply-To'] = SENDER_EMAIL
        
        # Send email using hardcoded SMTP settings
        logger.info(f"Sending summary email from {SENDER_EMAIL} to {summary.user.email}")
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()  # Enable TLS encryption
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, [summary.user.email], msg.as_string())
        
        # Mark as sent in database
        summary.summary_email_sent = True
        summary.summary_email_sent_at = now()
        summary.save()
        
        logger.info(f"Summary email sent successfully to {summary.user.email}")
        logger.info(f"Sent from hardcoded email: {SENDER_EMAIL}")
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP Authentication failed: {e}")
        if db_logger:
            db_logger.log_email_failed(
            recipient=primary_to_email,
            subject=msg['Subject'],
            error_msg=f"Unexpected error: {str(e)}",
            cage_code=oem_info.get('cage')
        )
        logger.error(f"Check your email ({SENDER_EMAIL}) and password")
        logger.error(f"For Gmail, you need an App Password, not your regular password")
    except smtplib.SMTPConnectError as e:
        logger.error(f"SMTP Connection failed: {e}")
        logger.error(f"Check SMTP host ({SMTP_HOST}) and port ({SMTP_PORT})")
    except Exception as e:
        logger.error(f"Failed to send summary email: {e}")
        logger.error(f"Target: {summary.user.email}")
        logger.error(f"SMTP: {SMTP_HOST}:{SMTP_PORT}")

# ===== Call Email Function =====
if summary:
    send_rfq_summary_email(summary)
else:
    logger.warning("Skipping email: summary not saved.")

# Enhanced final results logging
logger.info("=== INDIVIDUAL PROGRESSIVE PROCESSING COMPLETE ===")
logger.info(f"MODE: {lock_type.upper()}")
logger.info(f"USER: {created_by_user.username} (ID: {created_by_user.id})")
logger.info(f"Total requested: {result['total_requested']}")
logger.info(f"Successfully sent: {result['successfully_sent']}")
logger.info(f"Failed: {result['failed']}")
logger.info(f"Remaining: {result['remaining']}")
logger.info(f"Status: {result['status']}")
logger.info(f"Processing rounds: {result.get('rounds', 'N/A')}")

# Log important notes
if result['status'] == 'error':
    logger.error(f"Processing failed with error: {result.get('error', 'Unknown error')}")
    logger.error("Django task should handle lock release on failure")
elif result['remaining'] > 0:
    logger.warning(f"Processing incomplete: {result['remaining']} IDs remaining")
    logger.info("Django task will handle lock release")
else:
    logger.info("All solicitations processed individually successfully!")
    logger.info("Django task will handle lock release")

if db_logger:
    db_logger.log_processing_summary(result)

# Session completion logging
if script_session_id and db_logger:
    try:
        from solicitations.models import RFQScriptSession
        from solicitations.utils.logging_utils import log_to_database
        
        session = RFQScriptSession.objects.get(session_id=script_session_id)
        session.total_solicitations_requested = result['total_requested']
        session.total_emails_sent = result['successfully_sent']
        session.total_failures = result['failed']
        session.update_statistics()

        if result['status'] == 'error':
            session.mark_failed(result.get('error', 'Unknown error'))
        else:
            session.mark_completed()
        
        # Log session completion
        log_to_database(
            message=f"Session {script_session_id} completed with status: {session.status}",
            level='INFO',
            category='summary',
            user=created_by_user,
            session_id=script_session_id,
            task_id=task_id,
            processing_duration=session.duration,
            items_processed=session.total_solicitations_requested,
            items_successful=session.total_emails_sent,
            items_failed=session.total_failures,
            extra_data={
                'session_duration': session.duration_formatted,
                'processing_rounds': result.get('rounds', 'N/A'),
                'final_status': session.status,
                'warnings': session.total_warnings,
                'errors': session.total_errors
            }
        )
        
        logger.info(f"Database session {script_session_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Failed to update database session: {e}")

# Exit with appropriate code
sys.exit(1 if result['status'] == 'error' else 0)