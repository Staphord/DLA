import datetime
from django.db import models
from django.conf import settings
from accounts.models import CustomUser
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
import json
import uuid
from django.forms.models import model_to_dict
from collections import OrderedDict


# This model store solicitations data
class Solicitation(models.Model):
    cage = models.CharField(max_length=5)
    nomenclature = models.CharField(max_length=50)
    solicitation = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    part_number = models.CharField(max_length=500, blank=True, null=True)
    pr = models.CharField(max_length=255, blank=True, null=True)
    unit = models.CharField(max_length=15, blank=True, null=True)
    quantity = models.CharField(max_length=20)
    NSN = models.CharField(max_length=30, default='1')
    issued_date = models.CharField(max_length=20)
    return_by_date = models.CharField(max_length=20)
    organization_name = models.CharField(max_length=255, blank=True)
    street_name = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255, blank=True)
    fax = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    scraped_date = models.DateField(auto_now_add=True)
    inspection_point = models.CharField(max_length=255, blank=True)
    acceptance_point = models.CharField(max_length=255, blank=True)
    deliver_fob = models.CharField(max_length=255, blank=True)
    deliver_days = models.CharField(max_length=255, blank=True)
    buyer_info = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            # Single field indexes
            models.Index(fields=['scraped_date']),  # For date filtering
            models.Index(fields=['-id']),           # For ordering
            models.Index(fields=['cage']),          # For OEM lookups
            models.Index(fields=['email']),         # For email filtering
            # For organization filtering
            models.Index(fields=['organization_name']),
            models.Index(fields=['return_by_date']),     # For date validation

            # Compound indexes (most important for your queries)
            models.Index(fields=['scraped_date', '-id']),  # Date + ordering
            # OEM + date queries
            models.Index(fields=['cage', 'scraped_date']),
            # Multi-field filtering
            models.Index(fields=['scraped_date', 'cage', 'email']),
        ]

    def __str__(self):
        return f"Solicitation-{self.cage} ({self.nomenclature})"


def get_default_send_time():
    return datetime.time(0, 0)

# This model stores OEM data


class OEM(models.Model):
    name = models.CharField(max_length=500)
    cage = models.CharField(max_length=10)
    email = models.EmailField()
    phone = models.CharField(max_length=500)
    fax = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=500)
    street = models.CharField(max_length=500)
    postal_code = models.CharField(max_length=500)
    poc = models.CharField(max_length=500, null=True, blank=True)

    # NEW FIELDS TO ADD
    data_source = models.CharField(
        max_length=20,
        choices=[
            ('manual', 'Manual Entry'),
            ('import', 'File Import'),
            ('script', 'Script Generated')
        ],
        default='script'
    )
    manual_override = models.BooleanField(
        default=False,
        help_text="If True, this OEM data will not be updated by scripts"
    )
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    # Many-to-Many relationship with CustomUser through OEMUser
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through='OEMUser', related_name='oems')

    class Meta:
        indexes = [
            models.Index(fields=['cage']),  # CAGE code lookup
        ]

    def __str__(self):
        return f"{self.name} ({self.cage})"

    def is_protected_from_script_updates(self):
        """Check if this OEM should be protected from script updates"""
        return self.manual_override or self.data_source in ['manual', 'import']

# This model ensure oem belongs to a user depending on the sent emails


class OEMUser(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE)
    oem = models.ForeignKey(OEM, on_delete=models.CASCADE)
    is_disabled = models.BooleanField(default=False)
    reason = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        unique_together = ('user', 'oem')
        indexes = [
            models.Index(fields=['user', 'is_disabled']
                         ),           # User OEM status
            # Full lookup
            models.Index(fields=['oem', 'user', 'is_disabled']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.oem.name} (Disabled: {self.is_disabled})"

# Model for send RFQ


class RFQ(models.Model):
    solicitation = models.ForeignKey(
        Solicitation, on_delete=models.SET_NULL, null=True, blank=True, related_name='rfqs')
    oem = models.ForeignKey(OEM, on_delete=models.CASCADE, related_name='rfqs')
    unique_id = models.CharField(
        max_length=50, unique=True, editable=False)  # Unique 5-character ID
    sent_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_rfqs')

    def __str__(self):
        return f"RFQ-{self.unique_id} for {self.solicitation.nomenclature}"

# This model is for Email template


class MailTemplate(models.Model):
    body = models.TextField(
        default="I hope this message finds you well. We are currently looking for the following item. Kindly provide your lowest possible price.")
    salutation = models.CharField(max_length=20, default='Dear Mr/Ms')
    heading = models.CharField(max_length=50, default="REQUEST FOR QUOTATION")
    userMail = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

# This model is for Github Workflow actions (setting of cron job)


class GitHubWorkflow(models.Model):
    name = models.CharField(
        max_length=255, default="Extract Data Every 10 Minutes")
    cron_schedule = models.CharField(
        max_length=50, default="0 1 * * *")  # Default: 1 AM daily
    last_updated = models.DateTimeField(auto_now=True)

# This model ensure edits belong to user who made changes on the respective oem


class UserOEMCustomization(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE)
    oem = models.ForeignKey('OEM', on_delete=models.CASCADE)
    custom_name = models.CharField(max_length=500, blank=True, null=True)
    custom_email = models.CharField(
        max_length=500, blank=True, null=True)  # Accepts multiple emails
    custom_phone = models.CharField(max_length=500, blank=True, null=True)
    custom_fax = models.CharField(max_length=500, blank=True, null=True)
    custom_city = models.CharField(max_length=500, blank=True, null=True)
    custom_street = models.CharField(max_length=500, blank=True, null=True)
    custom_postal_code = models.CharField(
        max_length=500, blank=True, null=True)
    custom_poc = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        unique_together = ('user', 'oem')

    def __str__(self):
        return f"{self.user.username}'s customization of {self.oem.name}"


def get_default_send_time():
    # Return time in 24-hour format, e.g., 00:00 for midnight
    return datetime.time(0, 0)  # Default to midnight (00:00)


# This model is for auto email configurations
class EmailSettings(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='email_settings')
    auto_send = models.BooleanField(
        default=False, help_text="Toggle automatic email sending")

    DAILY = 'daily'
    MONDAY = 'monday'
    TUESDAY = 'tuesday'
    WEDNESDAY = 'wednesday'
    THURSDAY = 'thursday'
    FRIDAY = 'friday'
    SATURDAY = 'saturday'
    SUNDAY = 'sunday'

    DAY_CHOICES = [
        (DAILY, 'Every day'),
        (MONDAY, 'Monday'),
        (TUESDAY, 'Tuesday'),
        (WEDNESDAY, 'Wednesday'),
        (THURSDAY, 'Thursday'),
        (FRIDAY, 'Friday'),
        (SATURDAY, 'Saturday'),
        (SUNDAY, 'Sunday'),
    ]

    send_day = models.CharField(
        max_length=20, choices=DAY_CHOICES, default=DAILY)
    # Default in 24-hour format
    send_time = models.TimeField(default=get_default_send_time)
    last_processed = models.DateTimeField(
        null=True, blank=True, help_text="When emails were last processed for this user")

    # NEW FIELDS FOR MULTIPLE TIME INTERVALS
    # First time interval (morning)
    send_time_1 = models.TimeField(
        default=datetime.time(9, 0),  # 9:00 AM
        help_text="First time interval for sending RFQs"
    )
    enable_time_1 = models.BooleanField(
        default=True,
        help_text="Enable first time interval"
    )

    # Second time interval (afternoon)
    send_time_2 = models.TimeField(
        default=datetime.time(14, 0),  # 2:00 PM
        help_text="Second time interval for sending RFQs",
        null=True,
        blank=True
    )
    enable_time_2 = models.BooleanField(
        default=False,
        help_text="Enable second time interval"
    )

    # Third time interval (evening)
    send_time_3 = models.TimeField(
        default=datetime.time(18, 0),  # 6:00 PM
        help_text="Third time interval for sending RFQs",
        null=True,
        blank=True
    )
    enable_time_3 = models.BooleanField(
        default=False,
        help_text="Enable third time interval"
    )

    # NEW FIELD FOR SOLICITATION SCOPE
    SEND_ALL = 'all'
    SEND_TODAY = 'today'

    SCOPE_CHOICES = [
        (SEND_ALL, 'Send all pending solicitations'),
        (SEND_TODAY, 'Send only today\'s solicitations'),
    ]

    send_scope = models.CharField(
        max_length=10,
        choices=SCOPE_CHOICES,
        default=SEND_ALL,
        help_text="Choose which solicitations to send automatically"
    )

    def __str__(self):
        # Enhanced string representation to show multiple times
        enabled_times = []
        if self.enable_time_1:
            enabled_times.append(self.send_time_1.strftime('%H:%M'))
        if self.enable_time_2:
            enabled_times.append(self.send_time_2.strftime('%H:%M'))
        if self.enable_time_3:
            enabled_times.append(self.send_time_3.strftime('%H:%M'))

        times_str = ', '.join(
            enabled_times) if enabled_times else 'No times enabled'
        scope_display = self.get_send_scope_display()

        if self.send_day == self.DAILY:
            return f"{self.user.username}'s Email Settings (Daily at {times_str}, {scope_display})"
        return f"{self.user.username}'s Email Settings ({self.get_send_day_display()} at {times_str}, {scope_display})"

    def get_enabled_times(self):
        """Return list of enabled time intervals"""
        enabled_times = []
        if self.enable_time_1:
            enabled_times.append(self.send_time_1)
        if self.enable_time_2:
            enabled_times.append(self.send_time_2)
        if self.enable_time_3:
            enabled_times.append(self.send_time_3)
        return enabled_times

    def is_time_to_send(self, current_time):
        """Check if any enabled time interval matches current time (with 2-minute buffer)"""
        enabled_times = self.get_enabled_times()
        if not enabled_times:
            return False

        # Create 2-minute buffer window
        two_min_ago = (datetime.datetime.combine(
            datetime.date.today(), current_time) - datetime.timedelta(minutes=2)).time()
        two_min_ahead = (datetime.datetime.combine(
            datetime.date.today(), current_time) + datetime.timedelta(minutes=2)).time()

        for send_time in enabled_times:
            if two_min_ahead < two_min_ago:  # Midnight boundary case
                if send_time <= two_min_ahead or send_time >= two_min_ago:
                    return True
            else:  # Normal case
                if two_min_ago <= send_time <= two_min_ahead:
                    return True
        return False

# This model track the stattus of the email


class SolicitationEmailStatus(models.Model):
    solicitation = models.ForeignKey('Solicitation', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE)
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('sent', 'Sent'),
        ('failed', 'Failed')
    ], default='pending')
    processing_attempts = models.IntegerField(default=0)
    rfq_created = models.BooleanField(default=False)
    rfq = models.ForeignKey('RFQ', null=True, blank=True,
                            on_delete=models.SET_NULL)

    class Meta:
        unique_together = ('solicitation', 'user')
        verbose_name_plural = 'Solicitation Email Statuses'
        indexes = [
            models.Index(fields=['user', 'email_sent']
                         ),           # User email status
            models.Index(fields=['solicitation', 'user']
                         ),        # Solicitation lookup
            models.Index(fields=['user', 'solicitation',
                         'email_sent']),  # Compound
        ]

    def __str__(self):
        return f"{self.user.username} - {self.solicitation.cage} - {self.email_status}"


class UserEmailConfig(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='email_config'
    )
    email_host = models.CharField(max_length=255, default='smtp.sendgrid.net')
    email_port = models.IntegerField(default=587)
    email_use_tls = models.BooleanField(default=True)
    email_host_user = models.CharField(max_length=255, default='apikey')
    email_host_password = models.CharField(max_length=255)
    default_from_email = models.EmailField()

    email_interval_seconds = models.IntegerField(
        default=10,
        validators=[
            MinValueValidator(3, message="Minimum interval is 3 seconds"),
            MaxValueValidator(
                240, message="Maximum interval is 4 minutes (240 seconds)")
        ],
        help_text="Time delay between sending emails to different recipients (3-240 seconds)"
    )

    # NEW FIELDS for sent folder functionality
    save_to_sent_folder = models.BooleanField(
        default=True,
        help_text="Automatically save sent emails to the sent folder"
    )
    custom_imap_host = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Custom IMAP server (leave blank for auto-detection)"
    )
    custom_imap_port = models.IntegerField(
        default=993,
        help_text="IMAP port (default: 993 for SSL)"
    )
    custom_sent_folder = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Custom sent folder name (leave blank for auto-detection)"
    )

    # Optional: Keep the rate limiting fields if you want them
    max_emails_per_hour = models.IntegerField(
        default=20,
        validators=[
            MinValueValidator(
                1, message="Must allow at least 1 email per hour"),
            MaxValueValidator(
                50, message="Maximum 50 emails per hour for safety")
        ],
        help_text="Maximum emails to send per hour (conservative limit to avoid provider restrictions)"
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Email config for {self.user.username}"

    @property
    def email_interval_display(self):
        """Return a human-readable interval description"""
        seconds = self.email_interval_seconds
        if seconds < 60:
            return f"{seconds} seconds"
        else:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            if remaining_seconds == 0:
                return f"{minutes} minute{'s' if minutes != 1 else ''}"
            else:
                return f"{minutes}m {remaining_seconds}s"

    @property
    def theoretical_max_emails_per_hour(self):
        """Calculate theoretical maximum emails per hour based on interval"""
        return min(3600 // self.email_interval_seconds, self.max_emails_per_hour)

    @property
    def is_rate_limit_safe(self):
        """Check if current settings are safe for most email providers"""
        max_per_hour = self.theoretical_max_emails_per_hour
        return max_per_hour <= 25  # Most providers allow 25-50 per hour

    @property
    def safety_status(self):
        """Get safety status description"""
        max_per_hour = self.theoretical_max_emails_per_hour
        if max_per_hour <= 20:
            return "Very Safe"
        elif max_per_hour <= 25:
            return "Safe"
        elif max_per_hour <= 30:
            return "Risky"
        else:
            return "High Risk"

    def clean(self):
        """Validate the configuration"""
        super().clean()
        pass

    def save(self, *args, **kwargs):
        """Override save to run validation"""
        # For new instances, always validate required fields
        if self.pk is None:
            if not self.email_host_password:
                raise ValidationError("Email host password is required")

            if not self.default_from_email:
                raise ValidationError("Default from email is required")

        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "User Email Configuration"
        verbose_name_plural = "User Email Configurations"

###########################
############################


class RFQTaskSummary(models.Model):
    """
    Simple RFQ task summary - tracks essential process information only
    """

    # Core identification
    task_id = models.CharField(max_length=100, unique=True, db_index=True)
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='rfq_task_summaries')

    # Request and results
    requested_solicitations = models.IntegerField(
        help_text="Total solicitations submitted for processing")
    total_successful_sent = models.IntegerField(
        help_text="Number of RFQs successfully sent")
    total_failed = models.IntegerField(
        help_text="Number of solicitations that failed")

    # Timing
    date = models.DateField(help_text="Date when task was executed")
    start_time = models.DateTimeField(help_text="When processing started")
    completed_time = models.DateTimeField(
        help_text="When processing completed")

    # Processing mode
    PROCESSING_MODES = [
        ('manual', 'Manual'),
        ('automated', 'Automated'),
    ]
    processing_mode = models.CharField(max_length=20, choices=PROCESSING_MODES)

    # Summary email tracking
    summary_email_sent = models.BooleanField(default=False)
    summary_email_sent_at = models.DateTimeField(null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_time']
        verbose_name = "RFQ Task Summary"
        verbose_name_plural = "RFQ Task Summaries"
        indexes = [
            models.Index(fields=['user', '-start_time']),
            models.Index(fields=['date', '-start_time']),
            models.Index(fields=['processing_mode', '-start_time']),
        ]

    def __str__(self):
        return f"RFQ Task {self.task_id} - {self.user.username} - {self.date}"

    @property
    def duration(self):
        """Calculate duration between start and completion"""
        if self.completed_time and self.start_time:
            delta = self.completed_time - self.start_time
            return delta
        return None

    @property
    def duration_formatted(self):
        """Human-readable duration"""
        if not self.duration:
            return "N/A"

        total_seconds = int(self.duration.total_seconds())

        if total_seconds < 60:
            return f"{total_seconds} seconds"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}m {seconds}s"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"

    @property
    def success_rate(self):
        """Calculate success percentage"""
        if self.requested_solicitations == 0:
            return 0
        return round((self.total_successful_sent / self.requested_solicitations) * 100, 1)

    @property
    def status(self):
        """Determine overall status"""
        if self.total_successful_sent == self.requested_solicitations:
            return "completed"
        elif self.total_successful_sent == 0:
            return "failed"
        else:
            return "partial"

    @property
    def status_display(self):
        """User-friendly status"""
        status_map = {
            "completed": "All Successful",
            "partial": "Partially Successful",
            "failed": "Failed"
        }
        return status_map.get(self.status, "Unknown")

    @property
    def quick_summary(self):
        """One-line summary"""
        return f"{self.total_successful_sent}/{self.requested_solicitations} RFQs sent ({self.success_rate}%)"

########### for db rfq state ###############


class UserSelectionState(models.Model):
    """Simple model to store user's current RFQ selections - GLOBAL per user"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='selection_state'
    )
    selected_ids = models.JSONField(
        default=list, help_text="List of selected solicitation IDs")
    select_all_mode = models.BooleanField(default=False)
    processing_ids = models.JSONField(
        default=list, help_text="List of currently processing IDs")
    is_submitting = models.BooleanField(default=False)
    last_updated = models.DateTimeField(auto_now=True)
    page_context = models.JSONField(
        default=dict, help_text="Current page context for filters")

    # NEW: Add these fields for better state management
    current_page_url = models.CharField(
        max_length=500, blank=True, help_text="Current page URL")
    filter_criteria = models.JSONField(
        default=dict, help_text="Active filters")
    session_expires_at = models.DateTimeField(
        null=True, blank=True, help_text="When to auto-clear state")

    def __str__(self):
        return f"{self.user.username} - {len(self.selected_ids)} selected"

    @classmethod
    def get_for_user(cls, user):
        """Get or create selection state for user - GLOBAL across all browsers"""
        state, created = cls.objects.get_or_create(user=user)

        # Auto-clear expired state
        if state.session_expires_at and timezone.now() > state.session_expires_at:
            state.clear_selections()
            state.session_expires_at = None
            state.save()

        return state

    def add_selection(self, solicitation_id):
        """Add a solicitation to selections"""
        if solicitation_id not in self.selected_ids:
            self.selected_ids.append(solicitation_id)
            self.select_all_mode = False
            self.extend_session()
            self.save()

    def remove_selection(self, solicitation_id):
        """Remove a solicitation from selections"""
        if solicitation_id in self.selected_ids:
            self.selected_ids.remove(solicitation_id)
            self.select_all_mode = False
            self.extend_session()
            self.save()

    def clear_selections(self):
        """Clear all selections"""
        self.selected_ids = []
        self.select_all_mode = False
        self.processing_ids = []
        self.is_submitting = False
        self.session_expires_at = None
        self.save()

    def set_select_all(self, enabled=True):
        """Set select all mode"""
        self.select_all_mode = enabled
        if enabled:
            self.selected_ids = []  # Clear individual selections when in select all mode
        self.extend_session()
        self.save()

    def add_processing(self, solicitation_id):
        """Add ID to processing list"""
        if solicitation_id not in self.processing_ids:
            self.processing_ids.append(solicitation_id)
            self.extend_session()
            self.save()

    def remove_processing(self, solicitation_id):
        """Remove ID from processing list"""
        if solicitation_id in self.processing_ids:
            self.processing_ids.remove(solicitation_id)
            self.save()

    def set_submitting(self, is_submitting):
        """Set submission state"""
        self.is_submitting = is_submitting
        if is_submitting:
            self.extend_session()
        self.save()

    def extend_session(self):
        """Extend session expiry to 2 hours from now"""
        self.session_expires_at = timezone.now() + timezone.timedelta(hours=2)

    def update_page_context(self, page_url, filter_criteria=None):
        """Update current page context"""
        self.current_page_url = page_url
        if filter_criteria:
            self.filter_criteria = filter_criteria
        self.save()


class RFQScriptLog(models.Model):
    """
    Comprehensive logging model for RFQ script activities.
    Stores all types of logs generated during RFQ processing.
    """

    # Log Categories
    LOG_CATEGORIES = [
        ('processing', 'Processing'),
        ('email', 'Email Operations'),
        ('error', 'Errors'),
        ('database', 'Database Operations'),
        ('oem', 'OEM Operations'),
        ('authentication', 'Authentication'),
        ('config', 'Configuration'),
        ('status', 'Status Updates'),
        ('summary', 'Summary'),
        ('lock', 'Lock Management'),
        ('validation', 'Validation'),
        ('cleanup', 'Cleanup Operations'),
        ('testing', 'Testing Mode'),
        ('debug', 'Debug Information'),
    ]

    # Log Levels (matching Python logging levels)
    LOG_LEVELS = [
        ('DEBUG', 'Debug'),
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical'),
    ]

    # Processing Modes
    PROCESSING_MODES = [
        ('manual', 'Manual'),
        ('automated', 'Automated'),
        ('individual', 'Individual'),
        ('consolidated', 'Consolidated'),
    ]

    # Core Fields
    id = models.AutoField(primary_key=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.CASCADE, null=True, blank=True, db_index=True)

    # Log Details
    level = models.CharField(
        max_length=10, choices=LOG_LEVELS, default='INFO', db_index=True)
    category = models.CharField(
        max_length=20, choices=LOG_CATEGORIES, default='processing', db_index=True)
    message = models.TextField()

    # Context Information
    task_id = models.CharField(
        max_length=100, null=True, blank=True, db_index=True)
    session_id = models.CharField(
        max_length=100, null=True, blank=True, db_index=True)
    processing_mode = models.CharField(
        max_length=20, choices=PROCESSING_MODES, null=True, blank=True)

    # Specific Entity References
    solicitation_id = models.IntegerField(null=True, blank=True, db_index=True)
    cage_code = models.CharField(
        max_length=20, null=True, blank=True, db_index=True)
    rfq_id = models.IntegerField(null=True, blank=True, db_index=True)
    oem_id = models.IntegerField(null=True, blank=True, db_index=True)

    # Email Related Fields
    email_recipient = models.EmailField(null=True, blank=True)
    email_subject = models.CharField(max_length=255, null=True, blank=True)
    email_status = models.CharField(
        max_length=50, null=True, blank=True)  # sent, failed, pending

    # Error Information
    error_code = models.CharField(max_length=50, null=True, blank=True)
    error_details = models.TextField(null=True, blank=True)
    stack_trace = models.TextField(null=True, blank=True)

    # Processing Statistics
    items_processed = models.IntegerField(null=True, blank=True)
    items_successful = models.IntegerField(null=True, blank=True)
    items_failed = models.IntegerField(null=True, blank=True)
    processing_duration = models.DurationField(null=True, blank=True)

    # Additional Data (JSON field for flexible data storage)
    extra_data = models.JSONField(
        default=dict, blank=True, help_text="Additional log data in JSON format")

    # System Information
    script_version = models.CharField(max_length=50, null=True, blank=True)
    source_function = models.CharField(max_length=100, null=True, blank=True)
    source_line = models.IntegerField(null=True, blank=True)

    # Flags
    is_testing_mode = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)  # For error tracking

    class Meta:
        db_table = 'rfq_script_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp', 'user']),
            models.Index(fields=['level', 'category']),
            models.Index(fields=['task_id', 'timestamp']),
            models.Index(fields=['cage_code', 'timestamp']),
            models.Index(fields=['solicitation_id', 'timestamp']),
            models.Index(fields=['email_status', 'timestamp']),
        ]

    def __str__(self):
        ts = self.timestamp.strftime(
            '%Y-%m-%d %H:%M:%S') if self.timestamp else 'NA'
        preview = (self.message or '')[:100]
        return f"{ts} - {self.level} - {self.category} - {preview}"

    @property
    def formatted_timestamp(self):
        """Human-readable timestamp"""
        if not self.timestamp:
            return ''
        return self.timestamp.strftime('%Y-%m-%d %H:%M:%S')

    @property
    def is_error(self):
        """Check if this is an error log"""
        return self.level in ['ERROR', 'CRITICAL']

    @property
    def is_email_related(self):
        """Check if this log is email-related"""
        return self.category == 'email' or self.email_recipient is not None

    def add_extra_data(self, key, value):
        """Add data to extra_data field"""
        if not isinstance(self.extra_data, dict):
            self.extra_data = {}
        self.extra_data[key] = value

    def get_extra_data(self, key, default=None):
        """Get data from extra_data field"""
        if not isinstance(self.extra_data, dict):
            return default
        return self.extra_data.get(key, default)

    def _duration_to_readable(self, value):
        """
        Convert DurationField (timedelta) or bigint (microseconds/seconds) to a readable string and seconds.
        """
        seconds = None
        readable = None

        if isinstance(value, datetime.timedelta):
            seconds = int(value.total_seconds())
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            readable = f"{h}h {m}m {s}s" if h else (
                f"{m}m {s}s" if m else f"{s}s")
        elif isinstance(value, (int, float)) and value is not None:
            if value > 10**10:  # microseconds
                seconds = int(value // 1_000_000)
            else:
                seconds = int(value)
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            readable = f"{h}h {m}m {s}s" if h else (
                f"{m}m {s}s" if m else f"{s}s")

        return readable, seconds

    def to_display_dict(self):
        """
        Return an OrderedDict with ALL fields in a UI-friendly form.
        """
        data = {}

        # Get all field values
        for field in self._meta.fields:
            field_name = field.name
            try:
                field_value = getattr(self, field_name, None)
                data[field_name] = field_value
            except Exception:
                data[field_name] = None

        # Add computed fields
        data['formatted_timestamp'] = self.formatted_timestamp
        data['is_error'] = self.is_error
        data['is_email_related'] = self.is_email_related

        # Add user information
        data['user_id'] = self.user_id
        if self.user_id and hasattr(self, 'user') and self.user:
            data['user_username'] = getattr(self.user, 'username', None)
            data['user_email'] = getattr(self.user, 'email', None)
        else:
            data['user_username'] = None
            data['user_email'] = None

        # Processing duration
        raw_dur = getattr(self, 'processing_duration', None)
        readable, seconds = self._duration_to_readable(raw_dur)
        if readable is not None:
            data['processing_duration_human'] = readable
        if seconds is not None:
            data['processing_duration_seconds'] = seconds

        # JSON pretty-print
        try:
            if isinstance(self.extra_data, (dict, list)) and self.extra_data:
                data['extra_data_pretty'] = json.dumps(
                    self.extra_data, indent=2, ensure_ascii=False)
            else:
                data['extra_data_pretty'] = None
        except Exception:
            data['extra_data_pretty'] = None

        # Order fields
        preferred_order = [
            'id', 'formatted_timestamp', 'timestamp', 'level', 'category', 'message',
            'task_id', 'session_id', 'processing_mode',
            'solicitation_id', 'cage_code', 'rfq_id', 'oem_id',
            'email_status', 'email_subject', 'email_recipient',
            'items_processed', 'items_successful', 'items_failed',
            'processing_duration_human', 'processing_duration_seconds', 'processing_duration',
            'error_code', 'error_details', 'stack_trace',
            'script_version', 'source_function', 'source_line',
            'is_testing_mode', 'is_resolved',
            'user_id', 'user_username', 'user_email',
            'extra_data_pretty', 'extra_data',
            'is_error', 'is_email_related'
        ]

        ordered = OrderedDict()
        for key in preferred_order:
            if key in data:
                ordered[key] = data[key]

        # Add any remaining keys
        for k, v in data.items():
            if k not in ordered:
                ordered[k] = v

        return ordered


class RFQScriptSession(models.Model):
    """
    Track script execution sessions. Groups related logs together.
    """

    SESSION_STATUS = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('interrupted', 'Interrupted'),
    ]

    session_id = models.CharField(
        max_length=100, unique=True, primary_key=True)
    user = models.ForeignKey('accounts.CustomUser',
                             on_delete=models.CASCADE, db_index=True)
    task_id = models.CharField(max_length=100, null=True, blank=True)

    # Session Details
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=SESSION_STATUS, default='running')
    processing_mode = models.CharField(
        max_length=20, choices=RFQScriptLog.PROCESSING_MODES, null=True, blank=True)

    # Summary Statistics
    total_solicitations_requested = models.IntegerField(default=0)
    total_emails_sent = models.IntegerField(default=0)
    total_failures = models.IntegerField(default=0)
    total_warnings = models.IntegerField(default=0)
    total_errors = models.IntegerField(default=0)

    # Configuration
    is_testing_mode = models.BooleanField(default=False)
    auto_mode = models.BooleanField(default=False)

    # Additional session data
    session_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'rfq_script_sessions'
        ordering = ['-start_time']

    def __str__(self):
        return f"Session {self.session_id} - {self.user.username} - {self.status}"

    @property
    def duration(self):
        """Calculate session duration"""
        end = self.end_time or timezone.now()
        return end - self.start_time

    @property
    def duration_formatted(self):
        """Human-readable duration"""
        total_seconds = int(self.duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def mark_completed(self):
        """Mark session as completed"""
        self.status = 'completed'
        self.end_time = timezone.now()
        self.save(update_fields=['status', 'end_time'])

    def mark_failed(self, error_message=None):
        """Mark session as failed"""
        self.status = 'failed'
        self.end_time = timezone.now()
        if error_message:
            self.session_data['final_error'] = error_message
        self.save(update_fields=['status', 'end_time', 'session_data'])

############### MODEL FOR RFQ PROCESSING CONTROL ###################


class UserProcessingControl(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='processing_control')
    stop_requested = models.BooleanField(default=False)
    stop_reason = models.TextField(blank=True)
    stop_requested_at = models.DateTimeField(null=True, blank=True)

    def request_stop(self, reason=""):
        self.stop_requested = True
        self.stop_reason = reason
        self.stop_requested_at = timezone.now()
        self.save()

    def clear_stop(self):
        self.stop_requested = False
        self.stop_reason = ""
        self.stop_requested_at = None
        self.save()

    def __str__(self):
        return f"Processing control for {self.user.username} - Stop: {self.stop_requested}"

############### MODEL FOR RFQ REPLIES FROM OEMs ###################


class RfqReply(models.Model):
    """
    Store OEM replies to RFQs - extracted from email inbox.

    Extracted fields from email:
    - NSN, Nomenclature, Solicitation Number, Qty/Unit
    - Price, Total Price
    - OEM Name, Replied Email
    """

    REPLY_STATUS_CHOICES = [
        ('pending', 'Pending Reply'),
        ('received', 'Reply Received'),
        ('quoted', 'Quote Provided'),
        ('declined', 'Declined to Quote'),
        ('no_response', 'No Response'),
    ]

    # Core relationship
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='rfq_replies',
        help_text="User who sent the RFQ and received this reply"
    )

    # Reply status
    status = models.CharField(
        max_length=20,
        choices=REPLY_STATUS_CHOICES,
        default='received',
        help_text="Current status of the reply"
    )

    # Extracted data from email - Solicitation/RFQ Info
    solicitation_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Solicitation number extracted from email"
    )
    rfq_unique_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="RFQ ID extracted from email (e.g., ABC/MMDDYYYY/CAGE/000001)"
    )
    nsn = models.CharField(
        max_length=50,
        blank=True,
        help_text="NSN extracted from email"
    )
    nomenclature = models.TextField(
        blank=True,
        help_text="Nomenclature/description extracted from email"
    )
    quantity = models.CharField(
        max_length=50,
        blank=True,
        help_text="Quantity extracted from email"
    )
    unit = models.CharField(
        max_length=20,
        blank=True,
        help_text="Unit of measure extracted from email (e.g., EA, BOX)"
    )

    # Extracted pricing information
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Unit price extracted from email"
    )
    total_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total price extracted from email"
    )

    # Extracted OEM information
    oem_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="OEM/Vendor name extracted from email"
    )
    replied_email = models.EmailField(
        blank=True,
        help_text="Email address the reply came from"
    )

    # Email metadata
    email_subject = models.CharField(
        max_length=500,
        blank=True,
        help_text="Email subject line"
    )
    email_body = models.TextField(
        blank=True,
        help_text="Full email body text"
    )
    received_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the email was received"
    )
    email_message_id = models.CharField(
        max_length=500,
        blank=True,
        unique=True,
        help_text="Email Message-ID to prevent duplicates"
    )

    # Attachments
    has_attachments = models.BooleanField(
        default=False,
        help_text="Whether the email had attachments"
    )
    attachment_files = models.JSONField(
        default=list,
        blank=True,
        help_text="List of attachment file paths"
    )

    # Optional: Link to RFQ if match is found
    rfq = models.ForeignKey(
        'RFQ',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='oem_replies',
        help_text="Matched RFQ (if found by rfq_id)"
    )

    # Internal notes
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about this reply"
    )

    # GPT-4 Extraction Metadata
    confidence_score = models.FloatField(
        null=True,
        blank=True,
        help_text="GPT-4 extraction confidence score (0.0 to 1.0)"
    )
    extraction_notes = models.TextField(
        blank=True,
        help_text="GPT-4 extraction notes (missing fields, assumptions, etc.)"
    )

    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this record was created"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "RFQ Reply"
        verbose_name_plural = "RFQ Replies"
        ordering = ['-received_date', '-created_at']
        indexes = [
            models.Index(fields=['user', '-received_date']),
            models.Index(fields=['solicitation_number']),
            models.Index(fields=['rfq_unique_id']),
            models.Index(fields=['status', '-received_date']),
            models.Index(fields=['email_message_id']),
            models.Index(fields=['oem_name']),
            models.Index(fields=['nsn']),
        ]

    def __str__(self):
        ref = self.rfq_unique_id or self.solicitation_number or 'No Ref'
        return f"Reply from {self.oem_name or 'Unknown'} - {ref} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        """Try to match RFQ by rfq_unique_id if not already linked"""
        if not self.rfq and self.rfq_unique_id:
            try:
                # Try to find matching RFQ by unique_id
                matched_rfq = RFQ.objects.filter(
                    unique_id=self.rfq_unique_id,
                    created_by=self.user
                ).first()
                if matched_rfq:
                    self.rfq = matched_rfq
            except Exception:
                pass
        super().save(*args, **kwargs)

    @property
    def has_pricing(self):
        """Check if pricing information was extracted"""
        return (self.unit_price is not None and self.unit_price > 0) or \
               (self.total_price is not None and self.total_price > 0)

    @property
    def response_time_days(self):
        """Calculate response time if RFQ is matched"""
        if self.received_date and self.rfq and self.rfq.sent_at:
            delta = self.received_date - self.rfq.sent_at
            return delta.days
        return None


class ExportFieldDefinition(models.Model):
    """
    Defines the 121 fields for DLA export file format.
    Each field has a position (1-121), name, type, and validation rules.
    """
    FIELD_TYPE_CHOICES = [
        ('mandatory', 'Mandatory'),
        ('conditional', 'Conditional'),
        ('optional', 'Optional'),
        ('reserved', 'Reserved'),
    ]

    QUOTE_LEVEL_CHOICES = [
        ('header', 'Header'),
        ('line', 'Line'),
        ('product', 'Product'),
        ('', 'Not Applicable'),
    ]

    position = models.IntegerField(
        unique=True,
        help_text="Field position in export file (1-121)"
    )
    column_name = models.CharField(
        max_length=255,
        help_text="Name of the field"
    )
    quote_level = models.CharField(
        max_length=20,
        choices=QUOTE_LEVEL_CHOICES,
        blank=True,
        help_text="Quote level: Header, Line, or Product"
    )
    field_type = models.CharField(
        max_length=20,
        choices=FIELD_TYPE_CHOICES,
        help_text="Mandatory, Conditional, Optional, or Reserved"
    )
    max_length = models.IntegerField(
        default=0,
        help_text="Maximum length of the field value"
    )
    definition = models.TextField(
        blank=True,
        help_text="Field definition/description"
    )
    validation_rules = models.TextField(
        blank=True,
        help_text="Validation rules for this field"
    )
    default_value = models.CharField(
        max_length=255,
        blank=True,
        help_text="Default value for this field"
    )
    may_affect_bid_type = models.BooleanField(
        default=False,
        help_text="Whether this field may affect bid type"
    )
    predefined_choices = models.TextField(
        blank=True,
        help_text="JSON array of predefined choices for dropdown. Format: [{\"value\": \"Y\", \"label\": \"Small Business Set-Aside\"}, ...]"
    )

    class Meta:
        verbose_name = 'Export Field Definition'
        verbose_name_plural = 'Export Field Definitions'
        ordering = ['position']
        indexes = [
            models.Index(fields=['position']),
            models.Index(fields=['field_type']),
        ]

    def __str__(self):
        return f"{self.position:03d} - {self.column_name} ({self.field_type})"

    def get_choices(self):
        """
        Parse and return predefined choices as a list of dicts.
        Returns empty list if no choices defined.
        """
        if not self.predefined_choices:
            return []
        try:
            import json
            return json.loads(self.predefined_choices)
        except (json.JSONDecodeError, ValueError):
            return []

    def has_predefined_choices(self):
        """Check if this field has predefined choices for dropdown."""
        return bool(self.predefined_choices and self.predefined_choices.strip())


class UserExportConfiguration(models.Model):
    """
    Per-user configuration for export field mappings.
    Maps solicitation/RFQ data to the 121 export fields.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='export_configurations'
    )
    field_definition = models.ForeignKey(
        ExportFieldDefinition,
        on_delete=models.CASCADE,
        related_name='user_configurations'
    )

    # Mapping configuration
    is_enabled = models.BooleanField(
        default=True,
        help_text="Whether to include this field in export"
    )
    custom_value = models.CharField(
        max_length=255,
        blank=True,
        help_text="Custom static value for this field (overrides mapping)"
    )
    source_field = models.CharField(
        max_length=100,
        blank=True,
        help_text="Source field from Solicitation/RFQ model (e.g., 'solicitation', 'cage', 'NSN')"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Export Configuration'
        verbose_name_plural = 'User Export Configurations'
        unique_together = ('user', 'field_definition')
        ordering = ['field_definition__position']
        indexes = [
            models.Index(fields=['user', 'field_definition']),
            models.Index(fields=['is_enabled']),
        ]

    def __str__(self):
        return f"{self.user.username} - Field {self.field_definition.position}"

    def get_value(self, solicitation_obj):
        """
        Get the value for this field from a solicitation object.
        Returns custom_value if set, otherwise gets from source_field.
        Returns empty string if field is disabled or no value found.
        """
        if not self.is_enabled:
            return ""

        # Use custom value if set
        if self.custom_value:
            return self.custom_value

        # Get value from source field
        if self.source_field and solicitation_obj:
            try:
                value = getattr(solicitation_obj, self.source_field, "")
                return str(value) if value is not None else ""
            except AttributeError:
                return ""

        # Return default value from field definition
        return self.field_definition.default_value or ""
