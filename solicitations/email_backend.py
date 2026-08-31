from django.core.mail.backends.smtp import EmailBackend
from django.conf import settings
from .models import UserEmailConfig
import logging

logger = logging.getLogger(__name__)

class UserConfigurableEmailBackend(EmailBackend):
    def __init__(self, user=None, fail_silently=False, **kwargs):
        # Don't call super().__init__() yet - we need to configure first
        self.user = user
        self._configure_for_user()
        
        # Only call super if we have valid configuration
        if self.host and self.port:
            super().__init__(
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                use_tls=self.use_tls,
                fail_silently=fail_silently,
                **kwargs
            )
        else:
            # If no valid config, we'll handle this in the send methods
            self.fail_silently = fail_silently

    def _configure_for_user(self):
        if self.user:
            try:
                config = UserEmailConfig.objects.get(user=self.user, is_active=True)
                self.host = config.email_host
                self.port = config.email_port
                self.username = config.email_host_user
                self.password = config.email_host_password
                self.use_tls = config.email_use_tls
                self.from_email = config.default_from_email or config.email_host_user
                logger.info(f"Using user email config: {self.host}:{self.port} for user {self.user.username}")
                return True
                
            except UserEmailConfig.DoesNotExist:
                logger.error(f"No email configuration found for user {self.user.username if self.user else 'None'}")
                # Try to fall back to system defaults if they exist
                self.host = getattr(settings, 'EMAIL_HOST', None)
                self.port = getattr(settings, 'EMAIL_PORT', None)
                self.username = getattr(settings, 'EMAIL_HOST_USER', None)
                self.password = getattr(settings, 'EMAIL_HOST_PASSWORD', None)
                self.use_tls = getattr(settings, 'EMAIL_USE_TLS', True)
                self.from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
                
                if not all([self.host, self.port, self.username, self.password]):
                    logger.error("No valid email configuration available (neither user config nor system defaults)")
                    return False
                    
                logger.info(f"Using system default settings for user {self.user.username if self.user else 'None'}")
                return True
                
        else:
            # No user provided, try system defaults
            self.host = getattr(settings, 'EMAIL_HOST', None)
            self.port = getattr(settings, 'EMAIL_PORT', None)
            self.username = getattr(settings, 'EMAIL_HOST_USER', None)
            self.password = getattr(settings, 'EMAIL_HOST_PASSWORD', None)
            self.use_tls = getattr(settings, 'EMAIL_USE_TLS', True)
            self.from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
            
            if not all([self.host, self.port, self.username, self.password]):
                logger.error("No valid system email configuration available")
                return False
                
            logger.info("Using system default email settings")
            return True

    def send_messages(self, email_messages):
        """
        Override to handle cases where no valid configuration exists
        """
        if not hasattr(self, 'host') or not self.host:
            logger.error("Cannot send emails: No valid email configuration")
            if not self.fail_silently:
                raise Exception("No valid email configuration available")
            return 0
            
        return super().send_messages(email_messages)