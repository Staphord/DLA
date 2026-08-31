# solicitations/utils/logging_utils.py

import logging
import traceback
import inspect
from uuid import uuid4
from django.utils import timezone

# Import your CustomUser model directly
from accounts.models import CustomUser

# Make sure to create __init__.py in the utils directory
# Create: solicitations/utils/__init__.py (empty file) 


def log_to_database(
    message, 
    level='INFO', 
    category='processing', 
    user=None, 
    task_id=None, 
    session_id=None,
    solicitation_id=None,
    cage_code=None,
    rfq_id=None,
    oem_id=None,
    email_recipient=None,
    email_subject=None,
    email_status=None,
    error_code=None,
    error_details=None,
    stack_trace=None,
    items_processed=None,
    items_successful=None,
    items_failed=None,
    extra_data=None,
    processing_mode=None,
    is_testing_mode=False,
    source_function=None
):
    """
    Helper function to create log entries from your script
    
    Usage in your script:
    from solicitations.utils.logging_utils import log_to_database
    
    log_to_database(
        message="Processing started for CAGE ABC123",
        level='INFO',
        category='processing',
        user=created_by_user,
        cage_code="ABC123",
        solicitation_id=12345
    )
    """
    try:
        from solicitations.models import RFQScriptLog
        
        log_entry = RFQScriptLog.objects.create(
            message=message,
            level=level,
            category=category,
            user=user,
            task_id=task_id,
            session_id=session_id,
            solicitation_id=solicitation_id,
            cage_code=cage_code,
            rfq_id=rfq_id,
            oem_id=oem_id,
            email_recipient=email_recipient,
            email_subject=email_subject,
            email_status=email_status,
            error_code=error_code,
            error_details=error_details,
            stack_trace=stack_trace,
            items_processed=items_processed,
            items_successful=items_successful,
            items_failed=items_failed,
            extra_data=extra_data or {},
            processing_mode=processing_mode,
            is_testing_mode=is_testing_mode,
            source_function=source_function
        )
        return log_entry
    except Exception as e:
        # Fallback to regular logging if database logging fails
        logger = logging.getLogger('rfq')
        logger.error(f"Failed to log to database: {e}")
        logger.info(f"Original message: {message}")
        return None


def create_script_session(user, task_id=None, processing_mode=None, auto_mode=False, is_testing_mode=False):
    """
    Create a new script session
    
    Usage:
    from solicitations.utils.logging_utils import create_script_session
    
    session = create_script_session(
        user=created_by_user,
        task_id=task_id,
        processing_mode='individual',
        auto_mode=auto_mode,
        is_testing_mode=is_testing_mode()
    )
    """
    from solicitations.models import RFQScriptSession
    
    session_id = f"{user.username}-{uuid4().hex[:8]}"
    
    session = RFQScriptSession.objects.create(
        session_id=session_id,
        user=user,
        task_id=task_id,
        processing_mode=processing_mode,
        auto_mode=auto_mode,
        is_testing_mode=is_testing_mode
    )
    
    # Log session start
    log_to_database(
        message=f"Script session started: {session_id}",
        level='INFO',
        category='processing',
        user=user,
        task_id=task_id,
        session_id=session_id,
        processing_mode=processing_mode,
        is_testing_mode=is_testing_mode,
        extra_data={
            'auto_mode': auto_mode,
            'session_start': True
        }
    )
    
    return session


class DatabaseLogger:
    """
    Enhanced logger that writes to both file/console AND database
    Integrates seamlessly with your existing logging
    """
    
    def __init__(self, user=None, task_id=None, session_id=None, processing_mode=None, is_testing_mode=False):
        self.user = user
        self.task_id = task_id
        self.session_id = session_id
        self.processing_mode = processing_mode
        self.is_testing_mode = is_testing_mode
        
        # Keep the original logger for file/console output
        self.original_logger = logging.getLogger('rfq')
        
        # Import here to avoid circular imports
        from solicitations.models import RFQScriptLog
        self.RFQScriptLog = RFQScriptLog
    
    def _log_to_db(self, level, message, category='processing', **kwargs):
        """Internal method to log to database"""
        try:
            # Get caller information
            frame = inspect.currentframe().f_back.f_back
            source_function = frame.f_code.co_name if frame else None
            source_line = frame.f_lineno if frame else None
            
            # Merge default values with provided kwargs
            log_data = {
                'message': str(message),
                'level': level,
                'category': category,
                'user': self.user,
                'task_id': self.task_id,
                'session_id': self.session_id,
                'processing_mode': self.processing_mode,
                'is_testing_mode': self.is_testing_mode,
                'source_function': source_function,
                'source_line': source_line,
            }
            
            # Update with any additional data provided
            log_data.update(kwargs)
            
            # Create database log entry
            self.RFQScriptLog.objects.create(**log_data)
            
        except Exception as e:
            # Fallback to original logger if database fails
            self.original_logger.error(f"Database logging failed: {e}")
    
    def info(self, message, category='processing', **kwargs):
        """Log info level message"""
        self.original_logger.info(message)
        self._log_to_db('INFO', message, category, **kwargs)
    
    def warning(self, message, category='processing', **kwargs):
        """Log warning level message"""
        self.original_logger.warning(message)
        self._log_to_db('WARNING', message, category, **kwargs)
    
    def error(self, message, category='error', **kwargs):
        """Log error level message"""
        self.original_logger.error(message)
        
        # Auto-capture stack trace for errors
        if 'stack_trace' not in kwargs:
            kwargs['stack_trace'] = traceback.format_exc()
        
        self._log_to_db('ERROR', message, category, **kwargs)
    
    def critical(self, message, category='error', **kwargs):
        """Log critical level message"""
        self.original_logger.critical(message)
        
        # Auto-capture stack trace for critical errors
        if 'stack_trace' not in kwargs:
            kwargs['stack_trace'] = traceback.format_exc()
        
        self._log_to_db('CRITICAL', message, category, **kwargs)
    
    def debug(self, message, category='debug', **kwargs):
        """Log debug level message"""
        self.original_logger.debug(message)
        self._log_to_db('DEBUG', message, category, **kwargs)
    
    # Specialized logging methods for your script
    
    def log_processing_start(self, solicitation_ids, mode='individual'):
        """Log processing start"""
        message = f"INDIVIDUAL PROGRESSIVE PROCESSING - Starting for user {self.user.username if self.user else 'Unknown'}"
        self.info(
            message,
            category='processing',
            extra_data={
                'solicitation_ids': solicitation_ids,
                'mode': mode,
                'total_requested': len(solicitation_ids)
            }
        )
    
    def log_email_sent(self, recipient, subject, cage_code=None, rfq_id=None, solicitation_id=None):
        """Log successful email sending"""
        message = f"Email sent successfully to {recipient}"
        if cage_code:
            message += f" for CAGE {cage_code}"
        
        self.info(
            message,
            category='email',
            email_recipient=recipient,
            email_subject=subject,
            email_status='sent',
            cage_code=cage_code,
            rfq_id=rfq_id,
            solicitation_id=solicitation_id
        )
    
    def log_email_failed(self, recipient, subject, error_msg, cage_code=None, rfq_id=None, solicitation_id=None):
        """Log failed email sending"""
        message = f"Email failed to send to {recipient}: {error_msg}"
        
        self.error(
            message,
            category='email',
            email_recipient=recipient,
            email_subject=subject,
            email_status='failed',
            error_details=error_msg,
            cage_code=cage_code,
            rfq_id=rfq_id,
            solicitation_id=solicitation_id
        )
    
    def log_oem_created(self, cage_code, oem_name, auto_created=True):
        """Log OEM creation"""
        message = f"{'Auto-created' if auto_created else 'Created'} OEM for CAGE {cage_code}: {oem_name}"
        self.info(
            message,
            category='oem',
            cage_code=cage_code,
            extra_data={
                'oem_name': oem_name,
                'auto_created': auto_created
            }
        )
    
    def log_rfq_created(self, rfq_id, unique_id, cage_code, solicitation_id):
        """Log RFQ creation"""
        message = f"Created RFQ {unique_id} for solicitation {solicitation_id}"
        self.info(
            message,
            category='processing',
            rfq_id=rfq_id,
            cage_code=cage_code,
            solicitation_id=solicitation_id,
            extra_data={
                'rfq_unique_id': unique_id
            }
        )
    
    def log_status_update(self, solicitation_ids, status, message_prefix=""):
        """Log status updates for solicitations"""
        message = f"{message_prefix}Marked {len(solicitation_ids)} solicitations as {status.upper()}"
        self.info(
            message,
            category='status',
            extra_data={
                'solicitation_ids': solicitation_ids,
                'new_status': status,
                'count': len(solicitation_ids)
            }
        )
    
    def log_lock_operation(self, operation, lock_type, user_id=None, success=True):
        """Log lock operations"""
        message = f"Lock {operation}: {lock_type} for user {user_id or self.user.id if self.user else 'Unknown'}"
        if not success:
            message += " (FAILED)"
        
        level = 'INFO' if success else 'ERROR'
        self._log_to_db(
            level,
            message,
            category='lock',
            extra_data={
                'operation': operation,
                'lock_type': lock_type,
                'user_id': user_id or (self.user.id if self.user else None),
                'success': success
            }
        )
    
    def log_testing_mode(self, original_recipients, actual_recipient):
        """Log testing mode redirections"""
        message = f"TESTING MODE: Redirected email from {original_recipients} to {actual_recipient}"
        self.info(
            message,
            category='testing',
            email_recipient=actual_recipient,
            extra_data={
                'original_recipients': original_recipients,
                'redirected_to': actual_recipient,
                'testing_mode': True
            }
        )
    
    def log_processing_summary(self, result):
        """Log final processing summary"""
        message = f"Processing complete: {result['successfully_sent']}/{result['total_requested']} sent, {result['failed']} failed"
        
        level = 'INFO' if result['status'] != 'error' else 'ERROR'
        category = 'summary' if result['status'] != 'error' else 'error'
        
        self._log_to_db(
            level,
            message,
            category=category,
            items_processed=result['total_requested'],
            items_successful=result['successfully_sent'],
            items_failed=result['failed'],
            extra_data=result
        )

        try:
            from solicitations.models import RFQScriptSession

            final_status = 'failed' if result.get('status') == 'error' else 'completed'
            RFQScriptSession.objects.filter(
                session_id=self.session_id
            ).update(
                status=final_status,
                end_time=timezone.now(),
                total_solicitations_requested=result.get('total_requested', 0) or 0,
                total_emails_sent=result.get('successfully_sent', 0) or 0,
                total_failures=result.get('failed', 0) or 0,
            )
        except Exception as e:
            self.original_logger.error(f"Failed to update script session summary: {e}")


def initialize_database_logging(created_by_user, task_id, auto_mode, session_id=None):
    """
    Initialize database logging for your script
    Call this at the beginning of your script
    """
    try:
        # Create session if not provided
        if not session_id:
            session = create_script_session(
                user=created_by_user,
                task_id=task_id,
                processing_mode='individual',
                auto_mode=auto_mode,
                is_testing_mode=False  # You can modify this based on your is_testing_mode() function
            )
            session_id = session.session_id
        
        # Create enhanced logger
        db_logger = DatabaseLogger(
            user=created_by_user,
            task_id=task_id,
            session_id=session_id,
            processing_mode='individual',
            is_testing_mode=False  # You can modify this based on your is_testing_mode() function
        )
        
        return db_logger, session_id
        
    except Exception as e:
        # Fallback to original logger
        original_logger = logging.getLogger('rfq')
        original_logger.error(f"Failed to initialize database logging: {e}")
        return None, None
