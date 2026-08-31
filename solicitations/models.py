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
    prep_for_delivery = models.TextField(blank=True)
    solicitation_line_number = models.CharField(max_length=255, blank=True)
    purchase_request_number = models.CharField(max_length=255, blank=True)
    is_set_aside = models.BooleanField(default=True)
    procurement_history = models.JSONField(
        default=list, blank=True, help_text="List of procurement history records with CAGE, Contract Number, Quantity, Unit Cost, AWD Date, and Surplus Material")

    HIGHER_LEVEL_QUALITY_INDICATOR_CHOICES = [
        ('', '-- Not Set --'),
        ('N', 'N - Not Applicable'),
        ('8', '8 - SAE AS9100'),
        ('7', '7 - ISO 9001:2015'),
        ('6', '6 - SAE AS9003 or ISO 9001 tailored to meet SAE AS9003'),
    ]
    higher_level_quality_indicator = models.CharField(
        max_length=1,
        blank=True,
        default='',
        choices=HIGHER_LEVEL_QUALITY_INDICATOR_CHOICES,
        help_text="Higher-Level Quality Indicator (DLA export field 117)",
    )

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

            # Compound indexes
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


# Shown when MailTemplate.heading is empty in configurable RFQ email layouts (resale notice row).
DEFAULT_RESALE_NOTICE_TEXT = "ITEMS ARE FOR RESALE TO THE US GOVERNMENT"


class MailTemplate(models.Model):
    body = models.TextField(
        default="I hope this message finds you well. We are currently looking for the following item. Kindly provide your lowest possible price.")
    salutation = models.CharField(max_length=20, default='Dear Mr/Ms')
    heading = models.CharField(max_length=200, default="REQUEST FOR QUOTATION")
    userMail = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)


class EmailTemplateConfig(models.Model):
    """
    User-specific email template configuration for RFQ emails.
    Stores styling preferences and field visibility settings.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='email_template_config'
    )
    
    # Styling Configuration (stored as JSON for flexibility)
    # Colors
    primary_text_color = models.CharField(max_length=7, default='#000000', help_text="Main text color (hex)")
    secondary_text_color = models.CharField(max_length=7, default='#333333', help_text="Secondary text color (hex)") 
    background_color = models.CharField(max_length=7, default='#ffffff', help_text="Background color (hex)")
    border_color = models.CharField(max_length=7, default='#000000', help_text="Border color (hex)")
    link_color = models.CharField(max_length=7, default='#333333', help_text="Link color (hex)")
    header_bg_color = models.CharField(max_length=7, default='#f8f9fa', help_text="Table header background (hex)")
    header_text_color = models.CharField(max_length=7, default='#000000', help_text="Table header text color (hex)")
    banner_bg_color = models.CharField(max_length=7, default='#1e3a8a', help_text="Header banner background (hex)")
    
    # Fonts
    font_family = models.CharField(max_length=100, default='Arial, sans-serif', help_text="Font family")
    font_size = models.CharField(max_length=10, default='13px', help_text="Base font size")
    font_weight_normal = models.CharField(max_length=20, default='normal', help_text="Normal font weight")
    font_weight_bold = models.CharField(max_length=20, default='bold', help_text="Bold font weight")
    
    # Spacing
    padding = models.CharField(max_length=20, default='10px', help_text="General padding")
    margin = models.CharField(max_length=20, default='0', help_text="General margin")
    table_cell_padding = models.CharField(max_length=20, default='3px', help_text="Table cell padding")
    table_cell_spacing = models.CharField(max_length=20, default='0', help_text="Table cell spacing")
    
    # Table Styling
    table_border_width = models.CharField(max_length=10, default='1px', help_text="Table border width")
    table_border_style = models.CharField(max_length=20, default='solid', help_text="Table border style")
    table_width = models.CharField(max_length=20, default='100%', help_text="Table width")
    
    # Layout Style
    LAYOUT_CHOICES = [
        ('classic', 'Classic - Traditional table layout'),
        ('two_column', 'Two Column - Side by side fields'),
        ('card_based', 'Card Based - Each section in cards'),
        ('compact', 'Compact - Single column condensed'),
        ('modern_grid', 'Modern Grid - Grid-based sections'),
        ('header_banner', 'Header Banner - Branded top banner'),
    ]
    layout_style = models.CharField(
        max_length=20, 
        choices=LAYOUT_CHOICES, 
        default='classic',
        help_text="Email template layout design"
    )
    
    # Field Visibility (Boolean flags for each field)
    show_date = models.BooleanField(default=True, help_text="Show Date (Field 1)")
    show_our_ref = models.BooleanField(default=True, help_text="Show Our Reference (Field 2)")
    show_to_company = models.BooleanField(default=True, help_text="Show To/Company Name (Field 3)")
    show_cage_code = models.BooleanField(default=True, help_text="Show CAGE Code (Field 4)")
    show_phone = models.BooleanField(default=True, help_text="Show Phone (Field 5)")
    show_fax = models.BooleanField(default=True, help_text="Show Fax (Field 6)")
    show_oem_email = models.BooleanField(default=True, help_text="Show OEM Email (Field 7)")
    show_items_table = models.BooleanField(default=True, help_text="Show Items Table")
    # Items table column visibility (when show_items_table is True)
    show_items_col_index = models.BooleanField(default=True, help_text="Show # column in items table")
    show_items_col_nsn = models.BooleanField(default=True, help_text="Show NSN column")
    show_items_col_nomen = models.BooleanField(default=True, help_text="Show Nomen column")
    show_items_col_part_no = models.BooleanField(default=True, help_text="Show Part# column")
    show_items_col_solicitation_no = models.BooleanField(default=True, help_text="Show Solicitation# column")
    show_items_col_qty_unit = models.BooleanField(default=True, help_text="Show Qty/Unit column")
    show_items_col_unit_price = models.BooleanField(default=True, help_text="Show Unit Price (USD) column")
    show_items_col_total_price = models.BooleanField(default=True, help_text="Show Total Price (USD) column")
    show_technical_drawing = models.BooleanField(default=True, help_text="Show Technical Drawing Requirements (Field 8)")
    show_moq = models.BooleanField(default=True, help_text="Show MOQ (Field 9)")
    show_quote_valid_days = models.BooleanField(default=True, help_text="Show Quote Valid Days (Field 10)")
    show_inspection_point = models.BooleanField(default=True, help_text="Show Inspection Point (Field 11)")
    show_shipping_cost = models.BooleanField(default=True, help_text="Show Shipping Cost (Field 12)")
    show_terms = models.BooleanField(default=True, help_text="Show Terms (Field 13)")
    show_shipping_dimensions = models.BooleanField(default=True, help_text="Show Shipping Dimensions (Field 14)")
    show_delivery_days = models.BooleanField(default=True, help_text="Show Delivery Days (Field 15)")
    show_country_of_origin = models.BooleanField(default=True, help_text="Show Country of Origin (Field 16)")
    show_iso_certification = models.BooleanField(default=True, help_text="Show ISO Certification (Field 17)")
    show_quoted_by = models.BooleanField(default=True, help_text="Show Quoted By (Field 18)")
    show_quote_date = models.BooleanField(default=True, help_text="Show Quote Date (Field 19)")
    show_return_by_date_note = models.BooleanField(default=True, help_text="Show Return By Date Note")
    show_signature_section = models.BooleanField(default=True, help_text="Show Signature/Footer Section")
    show_logo = models.BooleanField(default=True, help_text="Show Company Logo")
    logo_width = models.PositiveIntegerField(default=120, help_text="Logo width in pixels (display size in email)")
    show_resale_notice = models.BooleanField(default=True, help_text="Show 'ITEMS ARE FOR RESALE TO THE US GOVERNMENT' notice")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Email Template Configuration"
        verbose_name_plural = "Email Template Configurations"
    
    def __str__(self):
        return f"Email Template Config for {self.user.username}"


class EmailTextStyleOverride(models.Model):
    """
    Persisted per-user text overrides for email HTML generation.

    Matching rule: exact text match in the generated HTML (including all occurrences).
    When matched, the generator wraps all occurrences with a <span> using the stored
    font family / size / color.
    """
    template_config = models.ForeignKey(
        EmailTemplateConfig,
        on_delete=models.CASCADE,
        related_name='text_style_overrides',
    )

    selected_text = models.CharField(
        max_length=500,
        help_text="Exact text to match (as plain text as shown in preview).",
    )

    # Styling for matched text
    font_family = models.CharField(max_length=100, default='Arial, sans-serif')
    font_size = models.CharField(max_length=10, default='13px')
    color = models.CharField(max_length=7, default='#000000', help_text="Hex color (e.g. #000000)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Email Text Style Override"
        verbose_name_plural = "Email Text Style Overrides"
        constraints = [
            models.UniqueConstraint(
                fields=['template_config', 'selected_text'],
                name='unique_text_style_override_per_config',
            )
        ]

    def __str__(self):
        return f"Override({self.template_config.user.username}): {self.selected_text}"


class EmailTemplateHistory(models.Model):
    """Undo/redo snapshots for email template configuration (per user)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='email_template_histories',
    )
    snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Email Template History"
        verbose_name_plural = "Email Template Histories"
        indexes = [
            # Keep index name stable because another migration renames it.
            models.Index(fields=['user'], name='solicitatio_user_id_31fd40_idx'),
        ]

    def __str__(self):
        return f"Template history for {self.user.username} at {self.created_at}"


class OEMImportJob(models.Model):
    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_ERROR = 'error'

    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_ERROR, 'Error'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='oem_import_jobs',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)

    original_filename = models.CharField(max_length=255, blank=True, default='')
    file_path = models.TextField(blank=True, default='')
    failed_download_url = models.TextField(blank=True, default='')
    error_message = models.TextField(blank=True, default='')

    processed = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    added_active = models.PositiveIntegerField(default=0)
    updated_active = models.PositiveIntegerField(default=0)
    disabled = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'status', 'created_at']),
        ]

    def __str__(self):
        return f"OEMImportJob({self.user.username}) #{self.id} {self.status}"

# This model is for Github Workflow actions (setting of cron job)


class GitHubWorkflow(models.Model):
    name = models.CharField(
        max_length=255, default="Extract Data Every 10 Minutes")
    cron_schedule = models.CharField(
        max_length=50, default="0 1 * * *")  # Default: 1 AM daily
    last_updated = models.DateTimeField(auto_now=True)


class ScrapingSchedule(models.Model):
    """Model to store automatic scraping schedule configuration"""
    enabled = models.BooleanField(
        default=False,
        help_text="Enable or disable automatic scraping"
    )

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

    scrape_day = models.CharField(
        max_length=20,
        choices=DAY_CHOICES,
        default=DAILY,
        help_text="Day of the week to run scraping"
    )
    scrape_time = models.TimeField(
        default=datetime.time(1, 0),  # Default: 1:00 AM
        help_text="Time to run scraping (24-hour format)"
    )
    second_scrape_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Time to run second scraping phase (optional, 24-hour format)"
    )
    last_updated = models.DateTimeField(auto_now=True)
    last_run = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time automatic scraping was executed"
    )
    last_run_status = models.CharField(
        max_length=20,
        choices=[
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('skipped', 'Skipped'),
            ('running', 'Running'),
            ('stopped', 'Stopped'),
        ],
        null=True,
        blank=True,
        help_text="Status of the last automatic scraping run"
    )

    class Meta:
        verbose_name = "Scraping Schedule"
        verbose_name_plural = "Scraping Schedules"

    def get_cron_schedule(self):
        """Convert day and time to cron expression"""
        # Get hour and minute from time
        hour = self.scrape_time.hour
        minute = self.scrape_time.minute
        
        # Map day to cron day-of-week (0=Sunday, 1=Monday, ..., 6=Saturday)
        day_mapping = {
            self.DAILY: '*',
            self.SUNDAY: '0',
            self.MONDAY: '1',
            self.TUESDAY: '2',
            self.WEDNESDAY: '3',
            self.THURSDAY: '4',
            self.FRIDAY: '5',
            self.SATURDAY: '6',
        }
        
        day_of_week = day_mapping.get(self.scrape_day, '*')
        
        # Cron format: minute hour day month day-of-week
        return f"{minute} {hour} * * {day_of_week}"

    def __str__(self):
        status = "Enabled" if self.enabled else "Disabled"
        day_display = dict(self.DAY_CHOICES).get(self.scrape_day, self.scrape_day)
        time_display = self.scrape_time.strftime("%I:%M %p")
        if self.second_scrape_time:
            second_time_display = self.second_scrape_time.strftime("%I:%M %p")
            return f"Auto-Scraping Schedule ({status}) - {day_display} at {time_display} (second phase at {second_time_display})"
        return f"Auto-Scraping Schedule ({status}) - {day_display} at {time_display}"


class QClusterMonitorConfig(models.Model):
    """
    Singleton configuration for Django-Q health monitoring and auto-recovery.
    Only one row should exist; use get_solo() to access it.
    """
    SINGLETON_PK = 1

    notification_emails = models.TextField(
        blank=True,
        default='',
        help_text="Comma-separated email addresses for health check alerts",
    )
    check_interval_minutes = models.PositiveSmallIntegerField(
        default=5,
        help_text="How often the cron health check should run (informational; update crontab manually)",
    )
    stall_threshold_minutes = models.PositiveSmallIntegerField(
        default=30,
        help_text="Minutes since last completed Django-Q task before the cluster is considered stalled",
    )
    alert_debounce_minutes = models.PositiveSmallIntegerField(
        default=0,
        help_text="Minimum minutes between failure alert emails. Use 0 while testing to email on every failure.",
    )
    is_monitoring_enabled = models.BooleanField(
        default=False,
        help_text="Enable automatic health checks and recovery",
    )
    last_alert_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time a failure alert email was sent (debounce repeat alerts)",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='qcluster_monitor_config_updates',
    )

    class Meta:
        verbose_name = "Django-Q Monitor Configuration"
        verbose_name_plural = "Django-Q Monitor Configuration"

    def __str__(self):
        status = "enabled" if self.is_monitoring_enabled else "disabled"
        return f"Django-Q Monitor ({status}, stall threshold {self.stall_threshold_minutes} min)"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(
            pk=cls.SINGLETON_PK,
            defaults={
                'check_interval_minutes': 5,
                'stall_threshold_minutes': 30,
                'alert_debounce_minutes': 0,
                'is_monitoring_enabled': False,
            },
        )
        return obj

    def get_notification_email_list(self):
        if not self.notification_emails:
            return []
        return [
            email.strip()
            for email in self.notification_emails.split(',')
            if email.strip()
        ]


class ScrapeNSNStatus(models.Model):
    """
    Per-date, per-NSN scraping status log.

    Used to coordinate first and second scraping phases:
    - phase 1: initial full scrape for a date
    - phase 2: retry failed NSNs and scrape NSNs added after phase 1
    """
    PHASE_FIRST = 1
    PHASE_SECOND = 2

    PHASE_CHOICES = (
        (PHASE_FIRST, "First"),
        (PHASE_SECOND, "Second"),
    )

    scrape_date = models.DateField(
        help_text="RFQ issue date this NSN status applies to",
    )
    nsn = models.CharField(max_length=100, db_index=True)
    phase = models.PositiveSmallIntegerField(
        choices=PHASE_CHOICES,
        help_text="Scraping phase (1 = first pass, 2 = second pass)",
    )
    status = models.CharField(
        max_length=20,
        choices=(
            ("success", "Success"),
            ("failed", "Failed"),
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Scrape NSN Status"
        verbose_name_plural = "Scrape NSN Statuses"
        indexes = [
            models.Index(fields=["scrape_date", "phase", "nsn"]),
        ]
        unique_together = ("scrape_date", "phase", "nsn")

    def __str__(self):
        return f"{self.scrape_date} | {self.nsn} | phase={self.phase} | {self.status}"


class AutoScrapeQueueItem(models.Model):
    """
    FIFO queue for deferred automatic solicitation scrapes when
    extractSolicitations.py is already running. Processed in created_at order.
    The same phase is not enqueued twice while a row for that phase exists.
    """

    PHASE_FIRST = "first"
    PHASE_SECOND = "second"
    PHASE_CHOICES = (
        (PHASE_FIRST, "First"),
        (PHASE_SECOND, "Second"),
    )

    phase = models.CharField(max_length=10, choices=PHASE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Auto scrape queue item"
        verbose_name_plural = "Auto scrape queue items"
        indexes = [
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.phase} @ {self.created_at}"


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


class RfqAutoFetchSettings(models.Model):
    """
    Separate configuration for automatic RFQ reply fetching from email.
    This is intentionally independent from EmailSettings.auto_send.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='rfq_auto_fetch_settings'
    )
    enabled = models.BooleanField(
        default=False,
        help_text="Enable automatic RFQ reply fetching from email",
    )

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

    day = models.CharField(
        max_length=20,
        choices=DAY_CHOICES,
        default=DAILY,
        help_text="Which day(s) to run auto-fetch",
    )
    fetch_time = models.TimeField(
        default=datetime.time(2, 0),  # 2:00 AM by default
        help_text="Time of day to run auto-fetch (server timezone)",
    )
    days_back = models.PositiveSmallIntegerField(
        default=2,
        help_text="How many days back to search for RFQ replies each run",
    )
    last_fetched = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When RFQ replies were last fetched for this user (prevents duplicate fetches)",
    )

    def __str__(self):
        status = "enabled" if self.enabled else "disabled"
        day_label = dict(self.DAY_CHOICES).get(self.day, self.day)
        return f"{self.user.username}'s RFQ Auto-Fetch [{status}] ({day_label} at {self.fetch_time}, last {self.days_back} day(s))"


class RfqAutoFetchStatus(models.Model):
    """
    Per-user status for RFQ auto-fetching.
    One row per user, updated on each auto-fetch run (global or by-date).
    """

    STATUS_NOT_STARTED = "not_started"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_NOT_STARTED, "Not started"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rfq_auto_fetch_status",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NOT_STARTED,
        help_text="Current status of the last auto-fetch run for this user",
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the last auto-fetch run started for this user",
    )
    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the last auto-fetch run finished for this user",
    )
    emails_scanned = models.PositiveIntegerField(
        default=0,
        help_text="How many email messages were scanned in the last run",
    )
    rfqs_created = models.PositiveIntegerField(
        default=0,
        help_text="How many RFQ replies were created in the last run",
    )
    errors_count = models.PositiveIntegerField(
        default=0,
        help_text="How many errors occurred in the last run",
    )
    message = models.CharField(
        max_length=255,
        blank=True,
        help_text="Short human-readable summary of the last run status",
    )

    class Meta:
        verbose_name = "RFQ Auto-Fetch Status"
        verbose_name_plural = "RFQ Auto-Fetch Statuses"

    def __str__(self):
        return f"{self.user.username} auto-fetch status: {self.status}"


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
    - Price, Total Price, Final Price
    - OEM Name, Replied Email
    """

    # Core relationship
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='rfq_replies',
        help_text="User who sent the RFQ and received this reply"
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
    part_number = models.CharField(
        max_length=255,
        blank=True,
        help_text="Part number extracted from email"
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
    # OEM Pricing fields
    minimum_order_qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    other_oem_charges = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total_shipping_weight = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    shipping_cost_to_company = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Shipping cost from OEM to company")
    payment_term = models.CharField(max_length=20, blank=True, default='')
    package_and_pres_mtd = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    oem_validity_days = models.IntegerField(null=True, blank=True, default=30)
    oem_delivery_days = models.IntegerField(null=True, blank=True)

    # Additional costs and fees (other_oem_charges is auto-computed as their sum)
    tax = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Tax amount (Sales Tax, VAT, GST, etc.)"
    )
    packaging_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Packaging cost"
    )
    handling_fee = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Handling fee"
    )
    insurance_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Insurance cost for shipment"
    )
    customs_duty = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Customs/Duty fees (for international shipments)"
    )
    setup_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Setup/Tooling/Molding cost (one-time manufacturing costs)"
    )
    minimum_order_charge = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Minimum order charge (if order is below minimum)"
    )
    rush_delivery_fee = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Rush/Expedited delivery fee"
    )
    environmental_fee = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Environmental/Disposal fee (for hazardous materials)"
    )
    certification_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Certification/Testing cost (quality certifications)"
    )
    documentation_fee = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Documentation/Processing fee"
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
        help_text="Email Message-ID to prevent duplicates (unique per user)"
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

    # Export / Archiving
    is_exported = models.BooleanField(
        default=False,
        help_text="Whether this RFQ reply has been exported to file"
    )
    exported_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this RFQ reply was last exported"
    )
    is_archived = models.BooleanField(
        default=False,
        help_text="Whether this RFQ reply has been archived (hidden from main list)"
    )
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this RFQ reply was archived"
    )

    class Meta:
        verbose_name = "RFQ Reply"
        verbose_name_plural = "RFQ Replies"
        ordering = ['-received_date', '-created_at']
        # Prevent duplicate emails per user
        unique_together = [('user', 'email_message_id')]
        indexes = [
            models.Index(fields=['user', '-received_date']),
            models.Index(fields=['solicitation_number']),
            models.Index(fields=['rfq_unique_id']),
            models.Index(fields=['email_message_id']),
            # Index for unique_together lookup
            models.Index(fields=['user', 'email_message_id']),
            models.Index(fields=['oem_name']),
            models.Index(fields=['nsn']),
        ]

    def __str__(self):
        ref = self.rfq_unique_id or self.solicitation_number or 'No Ref'
        return f"Reply from {self.oem_name or 'Unknown'} - {ref}"

    def match_rfq_from_extracted_data(self):
        """
        Match this reply to a user-owned RFQ.

        Uses the extracted RFQ ID first. If that is missing, uses a scored match
        against RFQs created by the same user. Ambiguous or weak matches are left
        unmatched to avoid attaching a reply to the wrong RFQ.
        """
        if self.rfq or not self.user_id:
            return

        if self.rfq_unique_id:
            try:
                matched_rfq = RFQ.objects.filter(
                    unique_id=str(self.rfq_unique_id).strip(),
                    created_by=self.user
                ).first()
                if matched_rfq:
                    self.rfq = matched_rfq
                    return
            except Exception:
                pass

        def clean_text(value):
            return str(value or '').strip().upper()

        def clean_code(value):
            return ''.join(ch for ch in clean_text(value) if ch.isalnum())

        def clean_quantity(value):
            import re
            text = str(value or '').strip().replace(',', '')
            match = re.match(r'^(\d+\.?\d*)', text)
            if not match:
                return ''
            number = match.group(1)
            return number.rstrip('0').rstrip('.') if '.' in number else number

        def clean_email(value):
            from email.utils import parseaddr
            return parseaddr(str(value or '').strip())[1].lower()

        reply_solicitation = clean_code(self.solicitation_number)
        reply_nsn = clean_code(self.nsn)
        reply_part = clean_code(self.part_number)
        reply_qty = clean_quantity(self.quantity)
        reply_nomenclature = clean_text(self.nomenclature)
        reply_email = clean_email(self.replied_email)
        reply_oem_name = clean_text(self.oem_name)

        candidates = (
            RFQ.objects
            .filter(created_by=self.user, solicitation__isnull=False)
            .select_related('solicitation', 'oem')
        )

        scored = []
        for candidate in candidates:
            solicitation = candidate.solicitation
            oem = candidate.oem
            score = 0

            if reply_solicitation and reply_solicitation == clean_code(solicitation.solicitation):
                score += 100
            if reply_nsn and reply_nsn == clean_code(solicitation.NSN):
                score += 40
            if reply_qty and reply_qty == clean_quantity(solicitation.quantity):
                score += 25
            if reply_part and reply_part == clean_code(solicitation.part_number):
                score += 35

            solicitation_nomenclature = clean_text(solicitation.nomenclature)
            if reply_nomenclature and solicitation_nomenclature:
                if reply_nomenclature == solicitation_nomenclature:
                    score += 15
                elif reply_nomenclature in solicitation_nomenclature or solicitation_nomenclature in reply_nomenclature:
                    score += 8

            if reply_email and reply_email == clean_email(oem.email):
                score += 30
            if reply_oem_name and reply_oem_name == clean_text(oem.name):
                score += 15

            if score:
                scored.append((score, candidate))

        if not scored:
            return

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_rfq = scored[0]
        if best_score < 60:
            return
        if len(scored) > 1 and scored[1][0] == best_score:
            return

        self.rfq = best_rfq
        self.rfq_unique_id = best_rfq.unique_id

    def save(self, *args, **kwargs):
        """Try to match RFQ by rfq_unique_id if not already linked, and calculate total_price if missing"""
        self.match_rfq_from_extracted_data()

        # Calculate total_price if missing but unit_price and quantity are available
        if (self.total_price is None or self.total_price == 0) and self.unit_price:
            # Try to get quantity from multiple sources in priority order
            quantity_to_use = None

            # Priority 1: Try RfqReply's quantity field (extracted from email - most specific to this reply)
            if self.quantity:
                quantity_to_use = self.quantity
            # Priority 2: Try to get from linked solicitation (direct relationship)
            elif self.rfq and self.rfq.solicitation and self.rfq.solicitation.quantity:
                quantity_to_use = self.rfq.solicitation.quantity
            # Priority 3: Try to find matching solicitation by searching
            else:
                try:
                    matching_solicitation = self.find_matching_solicitation()
                    if matching_solicitation and matching_solicitation.quantity:
                        quantity_to_use = matching_solicitation.quantity
                except Exception:
                    pass

            # Calculate total_price if we have quantity
            if quantity_to_use:
                try:
                    # Parse quantity string to number (handle commas, spaces, etc.)
                    quantity_str = str(quantity_to_use).strip().replace(
                        ',', '').replace(' ', '')
                    # Try to extract just the numeric part (in case there's text like "100 EA")
                    import re
                    # Match numbers (including decimals) at the start of the string
                    match = re.match(r'^(\d+\.?\d*)', quantity_str)
                    if match:
                        quantity_value = float(match.group(1))
                        # Calculate total_price = unit_price * quantity
                        from decimal import Decimal
                        self.total_price = Decimal(
                            str(self.unit_price)) * Decimal(str(quantity_value))
                except (ValueError, TypeError, AttributeError) as e:
                    # If parsing fails, leave total_price as is
                    pass

        # Compute other_oem_charges as the sum of all individual additional cost fields
        from decimal import Decimal as _Dec
        _fee_total = sum(
            (_Dec(str(f)) if not isinstance(f, _Dec) else f)
            for f in [
                self.tax, self.packaging_cost, self.handling_fee,
                self.insurance_cost, self.customs_duty, self.setup_cost,
                self.minimum_order_charge, self.rush_delivery_fee,
                self.environmental_fee, self.certification_cost,
                self.documentation_fee,
            ] if f is not None
        )
        self.other_oem_charges = _fee_total if _fee_total else None

        super().save(*args, **kwargs)

    @property
    def calculated_total_price(self):
        """Calculate total_price from unit_price * quantity if total_price is missing"""
        if self.total_price is not None and self.total_price > 0:
            return self.total_price

        # Calculate if unit_price is available
        if self.unit_price:
            # Try to get quantity from multiple sources in priority order
            quantity_to_use = None

            # Priority 1: Try RfqReply's quantity field (extracted from email - most specific to this reply)
            if self.quantity:
                quantity_to_use = self.quantity
            # Priority 2: Try to get from linked solicitation (direct relationship)
            elif self.rfq and self.rfq.solicitation and self.rfq.solicitation.quantity:
                quantity_to_use = self.rfq.solicitation.quantity
            # Priority 3: Try to find matching solicitation by searching
            else:
                try:
                    matching_solicitation = self.find_matching_solicitation()
                    if matching_solicitation and matching_solicitation.quantity:
                        quantity_to_use = matching_solicitation.quantity
                except Exception:
                    pass

            # Calculate if we have quantity
            if quantity_to_use:
                try:
                    # Parse quantity string to number
                    quantity_str = str(quantity_to_use).strip().replace(
                        ',', '').replace(' ', '')
                    import re
                    match = re.match(r'^(\d+\.?\d*)', quantity_str)
                    if match:
                        quantity_value = float(match.group(1))
                        from decimal import Decimal
                        return Decimal(str(self.unit_price)) * Decimal(str(quantity_value))
                except (ValueError, TypeError, AttributeError):
                    pass

        return None

    @property
    def has_pricing(self):
        """Check if pricing information was extracted"""
        return (self.unit_price is not None and self.unit_price > 0) or \
               (self.total_price is not None and self.total_price > 0) or \
               (self.calculated_total_price is not None and self.calculated_total_price > 0)

    @property
    def total_cost_with_fees(self):
        """
        Calculate total cost including all additional fees and costs.
        Returns None if base pricing is not available.
        """
        from decimal import Decimal

        base_price = self.total_price
        if base_price is None:
            return None

        # Convert base_price to Decimal if it's not already
        if not isinstance(base_price, Decimal):
            total = Decimal(str(base_price))
        else:
            total = base_price

        if self.other_oem_charges is not None:
            charge = self.other_oem_charges
            total += charge if isinstance(charge, Decimal) else Decimal(str(charge))

        return total

    @property
    def is_assessed(self):
        return self.assessments.filter(assessed=True).exists()

    @property
    def additional_costs_summary(self):
        """Return a dict of individual additional costs that have values."""
        costs = {}
        if self.tax:
            costs['Tax'] = self.tax
        if self.packaging_cost:
            costs['Packaging'] = self.packaging_cost
        if self.handling_fee:
            costs['Handling'] = self.handling_fee
        if self.insurance_cost:
            costs['Insurance'] = self.insurance_cost
        if self.customs_duty:
            costs['Customs/Duty'] = self.customs_duty
        if self.setup_cost:
            costs['Setup/Tooling'] = self.setup_cost
        if self.minimum_order_charge:
            costs['Minimum Order Charge'] = self.minimum_order_charge
        if self.rush_delivery_fee:
            costs['Rush Delivery'] = self.rush_delivery_fee
        if self.environmental_fee:
            costs['Environmental'] = self.environmental_fee
        if self.certification_cost:
            costs['Certification'] = self.certification_cost
        if self.documentation_fee:
            costs['Documentation'] = self.documentation_fee
        return costs

    @property
    def response_time_days(self):
        """Calculate response time if RFQ is matched"""
        if self.received_date and self.rfq and self.rfq.sent_at:
            delta = self.received_date - self.rfq.sent_at
            return delta.days
        return None

    def find_matching_solicitation(self):
        """
        Find matching Solicitation using multiple criteria in priority order.

        Returns:
            Solicitation object or None if no match found
        """
        # Import here to avoid circular import
        from django.db.models import Q
        # Solicitation is in the same module, so we can reference it directly

        # Method 1: Get from matched RFQ (highest priority)
        if self.rfq and self.rfq.solicitation:
            return self.rfq.solicitation

        # Method 2: Look up by solicitation number
        if self.solicitation_number:
            try:
                solicitation = Solicitation.objects.filter(
                    solicitation=self.solicitation_number
                ).first()
                if solicitation:
                    return solicitation
            except Exception:
                pass

        # Method 3: Look up by NSN AND quantity (both must match if available)
        if self.nsn and self.quantity:
            try:
                # Exact match on both NSN and quantity
                solicitation = Solicitation.objects.filter(
                    NSN=self.nsn,
                    quantity=self.quantity
                ).first()
                if solicitation:
                    return solicitation

                # If no exact match, try case-insensitive / trimmed quantity
                nsn_clean = self.nsn.strip() if self.nsn else None
                qty_clean = self.quantity.strip() if self.quantity else None
                if nsn_clean and qty_clean:
                    solicitation = Solicitation.objects.filter(
                        NSN__iexact=nsn_clean,
                        quantity__iexact=qty_clean
                    ).first()
                    if solicitation:
                        return solicitation
            except Exception:
                pass

        # Method 4: Look up by NSN alone
        if self.nsn:
            try:
                solicitation = Solicitation.objects.filter(
                    NSN=self.nsn
                ).first()
                if solicitation:
                    return solicitation
            except Exception:
                pass

        # Method 5: Look up by part_number AND quantity (both must match for accuracy)
        if self.part_number and self.quantity:
            try:
                # Try exact match first
                solicitation = Solicitation.objects.filter(
                    part_number=self.part_number,
                    quantity=self.quantity
                ).first()
                if solicitation:
                    return solicitation

                # If no exact match, try case-insensitive and trimmed match
                part_num_clean = self.part_number.strip() if self.part_number else None
                qty_clean = self.quantity.strip() if self.quantity else None

                if part_num_clean and qty_clean:
                    solicitation = Solicitation.objects.filter(
                        part_number__iexact=part_num_clean,
                        quantity__iexact=qty_clean
                    ).first()
                    if solicitation:
                        return solicitation
            except Exception:
                pass

        # Method 6: Look up by part_number alone (if quantity doesn't match or is missing)
        if self.part_number:
            try:
                # Try exact match first
                solicitation = Solicitation.objects.filter(
                    part_number=self.part_number
                ).first()
                if solicitation:
                    return solicitation

                # If no exact match, try case-insensitive match
                part_num_clean = self.part_number.strip() if self.part_number else None
                if part_num_clean:
                    solicitation = Solicitation.objects.filter(
                        part_number__iexact=part_num_clean
                    ).first()
                    if solicitation:
                        return solicitation
            except Exception:
                pass

        return None

    @property
    def has_matching_solicitation(self):
        """
        Convenience flag for templates/views: True if any Solicitation can be
        found using the same multi-step matching logic as the detail page.
        Uses cached value if available (set by view for performance).
        """
        # Check if view has pre-computed this value (performance optimization)
        if hasattr(self, '_cached_has_matching_solicitation'):
            return self._cached_has_matching_solicitation
        # Fallback to original method if not cached
        return self.find_matching_solicitation() is not None


# Embedded field definitions - all 121 DLA export fields
# This eliminates the need for management commands
# Field types and definitions extracted from index.html
EXPORT_FIELD_DEFINITIONS = {
    1: {'column_name': 'Solicitation Number', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 13, 'definition': ''},
    2: {'column_name': 'Solicitation Type Indicator', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    3: {'column_name': 'Small Business Set Aside Indicator', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    4: {'column_name': 'Additional Clause Fill-Ins Indicator', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    5: {'column_name': 'Return By Date', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 10, 'definition': ''},
    6: {'column_name': 'Quoter CAGE Code', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 5, 'definition': ''},
    7: {'column_name': 'Quote for CAGE Code', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 5, 'definition': ''},
    8: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    9: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    10: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    11: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    12: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    13: {'column_name': 'Small Business and Other Contractor Representations Code', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    14: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    15: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    16: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    17: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    18: {'column_name': 'Joint Venture', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 2, 'definition': ''},
    19: {'column_name': 'Joint Venture Remarks', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 255, 'definition': ''},
    20: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    21: {'column_name': 'Affirmative Action Compliance Code', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 2, 'definition': ''},
    22: {'column_name': 'Previous Contracts and Compliance Reports Code', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 2, 'definition': ''},
    23: {'column_name': 'Alternate Disputes Resolution', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    24: {'column_name': 'Bid Type Code', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 2, 'definition': ''},
    25: {'column_name': 'Prompt Payment Discount Terms Code', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 2, 'definition': ''},
    26: {'column_name': 'Vendor Quote Number', 'field_type': 'optional', 'quote_level': 'header', 'max_length': 15, 'definition': ''},
    27: {'column_name': 'Days Quote Valid', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 3, 'definition': '', 'default_value': '90'},
    28: {'column_name': 'Meets Packaging Requirement', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    29: {'column_name': 'Basic Ordering Agreement (BOA)/ Federal Supply Schedule (FSS)/Blanket Purchase Agreement (BPA).', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 3, 'definition': ''},
    30: {'column_name': 'BOA/FSS/BPA Contract Number', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 17, 'definition': ''},
    31: {'column_name': 'BOA/FSS/BPA Contract Expiration Date', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 10, 'definition': ''},
    32: {'column_name': 'FOB Point', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    33: {'column_name': 'FOB City', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 30, 'definition': ''},
    34: {'column_name': 'FOB State/Province', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 2, 'definition': ''},
    35: {'column_name': 'FOB Country', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 2, 'definition': ''},
    36: {'column_name': 'Inspection Point Code', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    37: {'column_name': 'Place of Government Inspection - Packaging CAGE code', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 5, 'definition': ''},
    38: {'column_name': 'Place of Government Inspection - Supplies CAGE code', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 5, 'definition': ''},
    39: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    40: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    41: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    42: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    43: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    44: {'column_name': 'Solicitation Line Number', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 4, 'definition': ''},
    45: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    46: {'column_name': 'Purchase Request Number', 'field_type': 'mandatory', 'quote_level': 'line', 'max_length': 10, 'definition': ''},
    47: {'column_name': 'National Stock Number / Part Number', 'field_type': 'mandatory', 'quote_level': 'line', 'max_length': 45, 'definition': ''},
    48: {'column_name': 'Unit of Issue', 'field_type': 'mandatory', 'quote_level': 'line', 'max_length': 2, 'definition': ''},
    49: {'column_name': 'Quantity', 'field_type': 'conditional', 'quote_level': 'line', 'max_length': 10, 'definition': ''},
    50: {'column_name': 'Unit Price', 'field_type': 'conditional', 'quote_level': 'line', 'max_length': 13, 'definition': ''},
    51: {'column_name': 'Delivery Days', 'field_type': 'conditional', 'quote_level': 'line', 'max_length': 4, 'definition': ''},
    52: {'column_name': 'GuaranteedMinimum', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 7, 'definition': ''},
    53: {'column_name': 'DO Minimum', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 8, 'definition': ''},
    54: {'column_name': 'Contract Maximum', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 12, 'definition': ''},
    55: {'column_name': 'Annual Frequency of Buys (AFB)', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 4, 'definition': ''},
    56: {'column_name': 'No DO Minimum Quantity?', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    57: {'column_name': 'HUBZone Preference Indicator', 'field_type': 'mandatory', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    58: {'column_name': 'Waiver of HUBZone Preference', 'field_type': 'conditional', 'quote_level': 'header', 'max_length': 1, 'definition': ''},
    59: {'column_name': 'Immediate Shipment Price', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 13, 'definition': ''},
    60: {'column_name': 'Immediate Shipment Delivery Days', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 4, 'definition': ''},
    61: {'column_name': 'RESERVED', 'field_type': 'reserved', 'quote_level': '', 'max_length': 0, 'definition': ''},
    62: {'column_name': 'Trade Agreements Indicator', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    63: {'column_name': 'Source of Supply CAGE Code', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 5, 'definition': ''},
    64: {'column_name': 'First Article Waiver Code', 'field_type': 'conditional', 'quote_level': 'line', 'max_length': 1, 'definition': ''},
    65: {'column_name': 'Hazardous Material Identification and Material Safety Data', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    66: {'column_name': 'Hazardous Warning Labels', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    67: {'column_name': 'Material Requirements', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    68: {'column_name': 'Buy American Indicator', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    69: {'column_name': 'Free Trade Agreements Indicator', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    70: {'column_name': 'Buy American/Free Trade/Trade Agreements End Product', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 2, 'definition': ''},
    71: {'column_name': 'Buy American/ Free Trade Agreements/Trade Agreements Country of Origin Code', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 2, 'definition': ''},
    72: {'column_name': 'Buy American / Free Trade / Trade Agreements Country Code', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 2, 'definition': ''},
    73: {'column_name': 'Duty Free Entry Requested', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    74: {'column_name': 'Duty Free Entry Requested/Foreign Supplies in US Code', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    75: {'column_name': 'Duty Free Entry Requested/Duty Paid Code', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    76: {'column_name': 'Duty Free Entry Requested/Duty Paid Amount', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 15, 'definition': ''},
    77: {'column_name': 'Price Breaks Solicited Indicator', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    78: {'column_name': 'Quantity Price Breaks - Range 1 Lower Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    79: {'column_name': 'Quantity Price Breaks - Range 1 Upper Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    80: {'column_name': 'Quantity Price Breaks - Range 1 Unit Price', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 13, 'definition': ''},
    81: {'column_name': 'Quantity Price Breaks - Range 2 Lower Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    82: {'column_name': 'Quantity Price Breaks - Range 2 Upper Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    83: {'column_name': 'Quantity Price Breaks - Range 2 Unit Price', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 13, 'definition': ''},
    84: {'column_name': 'Quantity Price Breaks - Range 3 Lower Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    85: {'column_name': 'Quantity Price Breaks - Range 3 Upper Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    86: {'column_name': 'Quantity Price Breaks - Range 3 Unit Price', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 13, 'definition': ''},
    87: {'column_name': 'Quantity Price Breaks - Range 4 Lower Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    88: {'column_name': 'Quantity Price Breaks - Range 4 Upper Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    89: {'column_name': 'Quantity Price Breaks - Range 4 Unit Price', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 13, 'definition': ''},
    90: {'column_name': 'Quantity Price Breaks - Range 5 Lower Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    91: {'column_name': 'Quantity Price Breaks - Range 5 Upper Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    92: {'column_name': 'Quantity Price Breaks - Range 5 Unit Price', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 13, 'definition': ''},
    93: {'column_name': 'Quantity Price Breaks - Range 6 Lower Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    94: {'column_name': 'Quantity Price Breaks - Range 6 Upper Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    95: {'column_name': 'Quantity Price Breaks - Range 6 Unit Price', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 13, 'definition': ''},
    96: {'column_name': 'Quantity Variance Plus', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 2, 'definition': ''},
    97: {'column_name': 'Quantity Variance Minus', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 2, 'definition': ''},
    98: {'column_name': 'Minimum Order Quantity Code', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    99: {'column_name': 'Minimum Order Maximum Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    100: {'column_name': 'Immediate Shipment Available', 'field_type': 'optional', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    101: {'column_name': 'Immediate Shipment Quantity', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 10, 'definition': ''},
    102: {'column_name': 'Manufacturer/Dealer', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 2, 'definition': ''},
    103: {'column_name': 'Actual Manufacturing/Production Source CAGE code', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 5, 'definition': ''},
    104: {'column_name': 'Actual Manufacturing/Production Source Name and Address', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 255, 'definition': ''},
    105: {'column_name': 'Item Description Indicator', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    106: {'column_name': 'Part Number Offered Code', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    107: {'column_name': 'Part Number Offered CAGE code', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 5, 'definition': ''},
    108: {'column_name': 'Part Number Offered - Part Number', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 40, 'definition': ''},
    109: {'column_name': 'Part Number Offered Remarks', 'field_type': 'optional', 'quote_level': 'product', 'max_length': 255, 'definition': ''},
    110: {'column_name': 'Supplies Offered', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    111: {'column_name': 'Supplies Offered Remarks', 'field_type': 'optional', 'quote_level': 'product', 'max_length': 255, 'definition': ''},
    112: {'column_name': 'Qualification Requirements MFG CAGE', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 5, 'definition': ''},
    113: {'column_name': 'Qualification Requirements Source CAGE', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 5, 'definition': ''},
    114: {'column_name': 'Qualification Requirements Item Name', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 50, 'definition': ''},
    115: {'column_name': 'Qualification Requirements Service Identification', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 50, 'definition': ''},
    116: {'column_name': 'Qualification Requirements Test Number', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 50, 'definition': ''},
    117: {'column_name': 'Higher-Level Quality Indicator', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    118: {'column_name': 'Higher-Level Quality Code', 'field_type': 'conditional', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    119: {'column_name': 'Higher-Level Quality Remarks', 'field_type': 'optional', 'quote_level': 'product', 'max_length': 255, 'definition': ''},
    120: {'column_name': 'Child Labor Certification Code', 'field_type': 'mandatory', 'quote_level': 'product', 'max_length': 1, 'definition': ''},
    121: {'column_name': 'Quote Remarks', 'field_type': 'optional', 'quote_level': 'header', 'max_length': 255, 'definition': ''},
}

# Predefined choices for dropdown fields
EXPORT_FIELD_CHOICES = {
    2: [  # Solicitation Type Indicator
        {'value': '', 'label': '-- Select --'},
        {'value': 'F', 'label': 'F - Fast Auto Evaluation'},
        {'value': 'I',
            'label': 'I - Automated Indefinite Delivery Contract (AIDC)'},
        {'value': 'P', 'label': 'P - Auto Evaluation'},
    ],
    3: [  # Small Business Set Aside Indicator
        {'value': '', 'label': '-- Select --'},
        {'value': 'Y', 'label': 'Y - Small Business Set-Aside'},
        {'value': 'H', 'label': 'H - HUBZone Set-Aside'},
        {'value': 'R',
            'label': 'R - Service Disabled Veteran-Owned Small Business (SDVOSB) Set-Aside'},
        {'value': 'L',
            'label': 'L - Woman Owned Small Business (WOSB) Set-Aside'},
        {'value': 'A', 'label': 'A - 8a Set-Aside'},
        {'value': 'E',
            'label': 'E - Economically Disadvantaged Woman Owned Small Business (EDWOSB) Set-Aside'},
        {'value': 'N', 'label': 'N - Unrestricted/Not Set-Aside'},
    ],
    4: [  # Additional Clause Fill-Ins Indicator
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - No'},
        {'value': 'Y', 'label': 'Y - Yes'},
    ],
    13: [  # Small Business and Other Contractor Representations Code
        {'value': '', 'label': '-- Select --'},
        {'value': 'A', 'label': 'A - Large Business/Other Business'},
        {'value': 'B', 'label': 'B - Small Business'},
        {'value': 'C', 'label': 'C - Nonprofit Institution'},
        {'value': 'E',
            'label': 'E - Educational Institution (other than HBCU or Minority)'},
        {'value': 'F',
            'label': 'F - Historically Black College or University (HBCU)'},
        {'value': 'G', 'label': 'G - JWOD Participating Nonprofit Agency'},
        {'value': 'M', 'label': 'M - Small Disadvantaged Business'},
        {'value': 'P', 'label': 'P - Minority Institution (other than HBCU)'},
        {'value': 'X', 'label': 'X - Intragovernmental'},
    ],
    18: [  # Joint Venture
        {'value': '', 'label': '-- Select --'},
        {'value': 'JV',
            'label': 'JV - Is a Joint Venture that complies with 13 CFR Part 121.103(h) and 13 CFR Part 125'},
        {'value': 'JN',
            'label': 'JN - Is not a Joint Venture that complies with 13 CFR Part 121.103(h) and 13 CFR Part 125'},
    ],
    21: [  # Affirmative Action Compliance Code
        {'value': '', 'label': '-- Select --'},
        {'value': 'Y6', 'label': 'Y6 - Developed and on File'},
        {'value': 'N6', 'label': 'N6 - Not Developed and Not on File'},
        {'value': 'NH', 'label': 'NH - No Previous Contracts Subject to Requirements'},
        {'value': 'NA', 'label': 'NA - Not Applicable'},
    ],
    22: [  # Previous Contracts and Compliance Reports Code
        {'value': '', 'label': '-- Select --'},
        {'value': 'Y4', 'label': 'Y4 - Participated and Filed'},
        {'value': 'Y5', 'label': 'Y5 - Participated and Not Filed'},
        {'value': 'N4', 'label': 'N4 - Not Participated'},
        {'value': 'NA', 'label': 'NA - Not Applicable'},
    ],
    23: [  # Alternate Disputes Resolution
        {'value': '', 'label': '-- Select --'},
        {'value': 'A', 'label': 'A - Agree To Use Alternate Disputes Resolution'},
        {'value': 'B', 'label': 'B - Do Not Agree To Use Alternate Disputes Resolution'},
    ],
    24: [  # Bid Type Code
        {'value': '', 'label': '-- Select --'},
        {'value': 'BI', 'label': 'BI - Bid without Exception'},
        {'value': 'BW', 'label': 'BW - Bid With Exception'},
        {'value': 'AB', 'label': 'AB - Alternate Bid'},
        {'value': 'DQ', 'label': 'DQ - No Bid'},
    ],
    25: [  # Prompt Payment Discount Terms Code
        {'value': '', 'label': '-- Select --'},
        {'value': '1', 'label': '1 - Net 30'},
        {'value': '10', 'label': '10 - 2% 10 Days'},
        {'value': '3', 'label': '3 - 1/2% 20 Days'},
        {'value': '6', 'label': '6 - 1/2% 10 Days'},
        {'value': '8', 'label': '8 - 1/4% 20 Days'},
    ],
    28: [  # Meets Packaging Requirement
        {'value': '', 'label': '-- Select --'},
        {'value': 'Y', 'label': 'Y - Yes'},
        {'value': 'N', 'label': 'N - No'},
    ],
    29: [  # Basic Ordering Agreement (BOA)/ Federal Supply Schedule (FSS)/Blanket Purchase Agreement (BPA)
        {'value': '', 'label': '-- Select --'},
        {'value': 'NAP', 'label': 'NAP - Not Applicable'},
        {'value': 'FSS', 'label': 'FSS - Federal Supply Schedule'},
        {'value': 'BOA', 'label': 'BOA - Blanket Ordering Agreement'},
        {'value': 'BPA', 'label': 'BPA - Blanket Purchase Agreement'},
    ],
    56: [  # No DO Minimum Quantity
        {'value': '', 'label': '-- Select --'},
        {'value': 'Y', 'label': 'Y - Yes'},
        {'value': 'N', 'label': 'N - No'},
    ],
    57: [  # HUBZone Preference Indicator
        {'value': '', 'label': '-- Select --'},
        {'value': 'Y', 'label': 'Y - Yes'},
        {'value': 'N', 'label': 'N - No'},
    ],
    58: [  # Waiver of HUBZone Preference
        {'value': '', 'label': '-- Select --'},
        {'value': 'Y', 'label': 'Y - Yes, request waiver'},
        {'value': 'N', 'label': 'N - No waiver requested'},
        {'value': 'A', 'label': 'A - Not Applicable'},
    ],
    62: [  # Trade Agreements Indicator
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - Not Applicable'},
        {'value': 'Y', 'label': 'Y - Trade Agreements'},
        {'value': 'I', 'label': 'I - Information Only (Overseas Shipment)'},
    ],
    64: [  # First Article Waiver Code
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - No Waiver Requested'},
        {'value': 'Y', 'label': 'Y - Yes. Request Waiver'},
    ],
    65: [  # Hazardous Material Identification and Material Safety Data
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - No'},
        {'value': 'Y', 'label': 'Y - Yes'},
    ],
    66: [  # Hazardous Warning Labels
        {'value': '', 'label': '-- Select --'},
        {'value': '1', 'label': '1 - Hazardous Communication Standard'},
        {'value': '2', 'label': '2 - Federal Insecticide, Fungicide and Rodenicide Act'},
        {'value': '3', 'label': '3 - Federal Food, Drug, and Cosmetic Act'},
        {'value': '4', 'label': '4 - Consumer Product Safety Act'},
        {'value': '5', 'label': '5 - Federal Hazardous Substance Act'},
        {'value': '6', 'label': '6 - Federal Alcohol Administration Act'},
        {'value': '7', 'label': '7 - Not Applicable'},
    ],
    67: [  # Material Requirements
        {'value': '', 'label': '-- Select --'},
        {'value': '0', 'label': '0 - No (Not Other Than New, Reconditioned, Remanufactured or Unused Former Government Surplus)'},
        {'value': '1', 'label': '1 - Yes - Other Than New (Used)'},
        {'value': '2', 'label': '2 - Yes - Reconditioned'},
        {'value': '3', 'label': '3 - Yes - Remanufactured'},
        {'value': '4', 'label': '4 - Yes - Unused Former Government Surplus'},
    ],
    68: [  # Buy American Indicator
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - Not Applicable'},
        {'value': 'Y', 'label': 'Y - Applicable'},
        {'value': 'I', 'label': 'I - Informational Only (Overseas Shipment)'},
    ],
    69: [  # Free Trade Agreements Indicator
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - Not Applicable'},
        {'value': 'Y', 'label': 'Y - Free Trade Agreements'},
        {'value': 'A', 'label': 'A - Free Trade Agreements (formerly ALT I)'},
        {'value': 'B', 'label': 'B - Free Trade Agreements ALT IV'},
    ],
    70: [  # Buy American/Free Trade/Trade Agreements End Product
        {'value': '', 'label': '-- Select --'},
        {'value': 'D', 'label': 'D - Domestic End Products'},
        {'value': 'Q', 'label': 'Q - Qualifying Country End Products'},
        {'value': 'NQ', 'label': 'NQ - Non-Qualifying Country End Products'},
        {'value': 'N', 'label': 'N - Free Trade Agreement Country End Products'},
        {'value': 'QA', 'label': 'QA - Qualifying Country End Products'},
        {'value': 'O', 'label': 'O - Other Foreign End Products'},
        {'value': 'C', 'label': 'C - Canadian End Products'},
        {'value': 'QE', 'label': 'QE - Qualifying Country End Products'},
        {'value': 'ND', 'label': 'ND - Non-Domestic End Products'},
        {'value': 'US', 'label': 'US - United States'},
    ],
    72: [  # Buy American / Free Trade / Trade Agreements Country Code
        {'value': '', 'label': '-- Select --'},
        {'value': 'AU', 'label': 'AU - Australia'},
        {'value': 'AT', 'label': 'AT - Austria'},
        {'value': 'BE', 'label': 'BE - Belgium'},
        {'value': 'CA', 'label': 'CA - Canada'},
        {'value': 'CZ', 'label': 'CZ - Czechia'},
        {'value': 'DK', 'label': 'DK - Denmark'},
        {'value': 'EG', 'label': 'EG - Egypt'},
        {'value': 'EE', 'label': 'EE - Estonia'},
        {'value': 'FI', 'label': 'FI - Finland'},
        {'value': 'FR', 'label': 'FR - France'},
        {'value': 'DE', 'label': 'DE - Germany'},
        {'value': 'GR', 'label': 'GR - Greece'},
        {'value': 'IL', 'label': 'IL - Israel'},
        {'value': 'IT', 'label': 'IT - Italy'},
        {'value': 'JP', 'label': 'JP - Japan'},
        {'value': 'LV', 'label': 'LV - Latvia'},
        {'value': 'LT', 'label': 'LT - Lithuania'},
        {'value': 'LU', 'label': 'LU - Luxembourg'},
        {'value': 'NL', 'label': 'NL - Netherlands'},
        {'value': 'NO', 'label': 'NO - Norway'},
        {'value': 'PL', 'label': 'PL - Poland'},
        {'value': 'PT', 'label': 'PT - Portugal'},
        {'value': 'SI', 'label': 'SI - Slovenia'},
        {'value': 'SK', 'label': 'SK - Slovakia'},
        {'value': 'ES', 'label': 'ES - Spain'},
        {'value': 'SE', 'label': 'SE - Sweden'},
        {'value': 'CH', 'label': 'CH - Switzerland'},
        {'value': 'TR', 'label': 'TR - Turkey'},
        {'value': 'GB', 'label': 'GB - United Kingdom'},
    ],
    73: [  # Duty Free Entry Requested
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - No'},
        {'value': 'Y', 'label': 'Y - Yes'},
    ],
    74: [  # Duty Free Entry Requested/Foreign Supplies in US Code
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - No'},
        {'value': 'Y', 'label': 'Y - Yes'},
    ],
    75: [  # Duty Free Entry Requested/Duty Paid Code
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - No'},
        {'value': 'Y', 'label': 'Y - Yes'},
    ],
    77: [  # Price Breaks Solicited Indicator
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - Price Breaks Do Not Apply'},
        {'value': 'Y', 'label': 'Y - Request Price Breaks'},
    ],
    98: [  # Minimum Order Quantity Code
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - No'},
        {'value': 'Y', 'label': 'Y - Yes'},
    ],
    100: [  # Immediate Shipment Available
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - No'},
        {'value': 'Y', 'label': 'Y - Yes'},
    ],
    102: [  # Manufacturer/Dealer
        {'value': '', 'label': '-- Select --'},
        {'value': 'DD', 'label': 'DD - Dealer'},
        {'value': 'MM', 'label': 'MM - Manufacturer'},
        {'value': 'QD', 'label': 'QD - Qualified Supplier List Dealer'},
        {'value': 'QM', 'label': 'QM - Qualified Supplier List Manufacturer'},
    ],
    105: [  # Item Description Indicator
        {'value': '', 'label': '-- Select --'},
        {'value': 'B', 'label': 'B - Source Controlled Item'},
        {'value': 'D', 'label': 'D - Specification/Standard/Drawing Item'},
        {'value': 'N', 'label': 'N - Non-NSN Item'},
        {'value': 'P', 'label': 'P - Approved Source Item'},
        {'value': 'Q', 'label': 'Q - Qualified Products List (QPL) Item'},
        {'value': 'S', 'label': 'S - Service Material Item'},
    ],
    106: [  # Part Number Offered Code
        {'value': '', 'label': '-- Select --'},
        {'value': '1', 'label': '1 - Exact Product'},
        {'value': '2', 'label': '2 - Alternate Product'},
        {'value': '3', 'label': '3 - Superseding PN - Administrative Change Only'},
        {'value': '4', 'label': '4 - Superseding PN - Minor Change'},
        {'value': '5', 'label': '5 - Previously-Approved Product'},
        {'value': '6', 'label': '6 - CAGE/PN Correction - CAGE In Error/Same Corp'},
        {'value': '7', 'label': '7 - CAGE/PN Correction - CAGE In Error/Different Corp'},
        {'value': '8', 'label': '8 - CAGE/PN Correction - Part Number Not Recognized'},
        {'value': '9', 'label': '9 - CAGE and PN Correction - Obsolete Part Number'},
        {'value': 'A', 'label': 'A - CAGE and PN Correction - Other'},
    ],
    110: [  # Supplies Offered
        {'value': '', 'label': '-- Select --'},
        {'value': '1', 'label': '1 - In Accordance With All SPEC/STD/DWGS'},
        {'value': '2', 'label': '2 - Different Revision'},
        {'value': '3', 'label': '3 - Changes To SPEC/STD/DWGS'},
        {'value': '4', 'label': '4 - Other Technical Data / Item Description In Error'},
    ],
    117: [  # Higher-Level Quality Indicator
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - Not Applicable'},
        {'value': '8', 'label': '8 - SAE AS9100'},
        {'value': '7', 'label': '7 - ISO 9001:2015'},
        {'value': '6', 'label': '6 - SAE AS9003 or ISO 9001 tailored to meet SAE AS9003'},
    ],
    118: [  # Higher-Level Quality Code
        {'value': '', 'label': '-- Select --'},
        {'value': '8', 'label': '8 - SAE AS9100'},
        {'value': '7', 'label': '7 - ISO 9001:2015'},
        {'value': '6', 'label': '6 - SAE AS9003 or ISO 9001 tailored to meet SAE AS9003'},
        {'value': '2', 'label': '2 - Other Equivalent'},
        {'value': '1', 'label': '1 - None'},
    ],
    120: [  # Child Labor Certification Code
        {'value': '', 'label': '-- Select --'},
        {'value': 'N', 'label': 'N - No'},
        {'value': 'U', 'label': 'U - May Supply, but not aware of any such use of child labor based on good faith effort'},
        {'value': 'Y', 'label': 'Y - Yes'},
    ],
    # Position 103 is Actual Manufacturing/Production Source CAGE code - no predefined choices (CAGE codes are user-entered)
}


class ExportFieldDefinition(models.Model):
    """
    Defines the 121 fields for DLA export file format.
    Each field has a position (1-121), name, type, and validation rules.
    Field definitions are embedded in EXPORT_FIELD_DEFINITIONS constant above.
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
            # Single field indexes
            # For ordering and position lookups
            models.Index(fields=['position']),
            models.Index(fields=['field_type']),  # For filtering by field type
            # For admin filtering by quote level
            models.Index(fields=['quote_level']),
            models.Index(fields=['column_name']),  # For admin search

            # Compound indexes
            # For mandatory/conditional queries with ordering
            models.Index(fields=['field_type', 'position']),
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

    @property
    def has_predefined_choices(self):
        """Check if this field has predefined choices for dropdown."""
        return bool(self.predefined_choices and self.predefined_choices.strip())

    @classmethod
    def ensure_all_fields_exist(cls):
        """
        Ensure all 121 ExportFieldDefinition records exist and are up-to-date.
        Uses embedded EXPORT_FIELD_DEFINITIONS data.
        This eliminates the need for management commands.
        Updates existing records to ensure field_type and other properties are correct.
        """
        import json
        import logging
        logger = logging.getLogger(__name__)
        created_count = 0
        updated_count = 0

        for position, field_data in EXPORT_FIELD_DEFINITIONS.items():
            # Get predefined choices if available
            predefined_choices_json = ''
            if position in EXPORT_FIELD_CHOICES:
                predefined_choices_json = json.dumps(
                    EXPORT_FIELD_CHOICES[position])

            # Use update_or_create to update existing records with correct field types
            field_def, created = cls.objects.update_or_create(
                position=position,
                defaults={
                    'column_name': field_data['column_name'],
                    # This will update existing records with correct field types
                    'field_type': field_data['field_type'],
                    'quote_level': field_data['quote_level'],
                    'max_length': field_data.get('max_length', 0),
                    'definition': field_data.get('definition', ''),
                    'validation_rules': field_data.get('validation_rules', ''),
                    'default_value': field_data.get('default_value', ''),
                    'may_affect_bid_type': field_data.get('may_affect_bid_type', False),
                    'predefined_choices': predefined_choices_json,
                }
            )

            if created:
                created_count += 1
            else:
                # Record was updated (update_or_create updates existing records)
                updated_count += 1

        if created_count > 0:
            logger.info(
                f"Created {created_count} missing ExportFieldDefinition records.")
        if updated_count > 0:
            logger.info(
                f"Updated {updated_count} existing ExportFieldDefinition records with correct field types.")

        return cls.objects.count() == 121


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
            # Single field indexes
            # For filtering enabled/disabled configs
            models.Index(fields=['is_enabled']),
            models.Index(fields=['source_field']),  # For admin search
            models.Index(fields=['updated_at']),  # For tracking recent changes

            # Compound indexes (most important for your queries)
            # For user+field lookups
            models.Index(fields=['user', 'field_definition']),
            # For enabled-only queries filtered by user
            models.Index(fields=['user', 'is_enabled']),
        ]

    def __str__(self):
        return f"{self.user.username} - Field {self.field_definition.position}"

    def get_value(self, obj=None):
        """
        Get the value for this field from an object (Solicitation or RfqReply).
        Returns custom_value if set, otherwise gets from source_field.
        For RfqReply objects, intelligently tries to get data from related RFQ/Solicitation models.
        Returns empty string if field is disabled or no value found.

        Args:
            obj: Solicitation or RfqReply object (optional)
        """
        if not self.is_enabled:
            return ""

        # SPECIAL HANDLING: Field position 32 - FOB Point
        # This should ALWAYS come from the solicitation's deliver_fob field (overrides custom_value)
        # Convert: "destination" or contains "destination" to "D", "origin" or contains "origin" to "O"
        field_position = getattr(self.field_definition, "position", None)
        if field_position == 32 and obj:
            try:
                # Check if obj is an RfqReply instance
                is_rfq_reply = obj.__class__.__name__ == 'RfqReply'

                if is_rfq_reply:
                    # Try to get deliver_fob from related Solicitation
                    solicitation = None

                    # Method 1: Get from matched RFQ -> Solicitation
                    if hasattr(obj, 'rfq') and obj.rfq and hasattr(obj.rfq, 'solicitation') and obj.rfq.solicitation:
                        solicitation = obj.rfq.solicitation

                    # Method 2: Find matching solicitation using RfqReply's find_matching_solicitation method
                    if not solicitation:
                        solicitation = obj.find_matching_solicitation()

                    # If we found a solicitation, get its deliver_fob value
                    if solicitation and hasattr(solicitation, 'deliver_fob') and solicitation.deliver_fob:
                        fob_value = str(
                            solicitation.deliver_fob).strip().lower()
                        if 'destination' in fob_value:
                            return "D"
                        elif 'origin' in fob_value:
                            return "O"
                        # If already "D" or "O", return as is
                        if fob_value in ['d', 'o']:
                            return fob_value.upper()
                else:
                    # For Solicitation objects, directly get the deliver_fob value
                    if hasattr(obj, 'deliver_fob') and obj.deliver_fob:
                        fob_value = str(obj.deliver_fob).strip().lower()
                        if 'destination' in fob_value:
                            return "D"
                        elif 'origin' in fob_value:
                            return "O"
                        # If already "D" or "O", return as is
                        if fob_value in ['d', 'o']:
                            return fob_value.upper()
            except Exception:
                # If any error occurs, fall through to normal source_field logic
                pass

        # SPECIAL HANDLING: Field position 36 - Inspection Point Code
        # This should ALWAYS come from the solicitation's inspection_point field (overrides custom_value)
        # Convert: "destination" or contains "destination" to "D", "origin" or contains "origin" to "O"
        if field_position == 36 and obj:
            try:
                # Check if obj is an RfqReply instance
                is_rfq_reply = obj.__class__.__name__ == 'RfqReply'

                if is_rfq_reply:
                    # Try to get inspection_point from related Solicitation
                    solicitation = None

                    # Method 1: Get from matched RFQ -> Solicitation
                    if hasattr(obj, 'rfq') and obj.rfq and hasattr(obj.rfq, 'solicitation') and obj.rfq.solicitation:
                        solicitation = obj.rfq.solicitation

                    # Method 2: Find matching solicitation using RfqReply's find_matching_solicitation method
                    if not solicitation:
                        solicitation = obj.find_matching_solicitation()

                    # If we found a solicitation, get its inspection_point value
                    if solicitation and hasattr(solicitation, 'inspection_point') and solicitation.inspection_point:
                        inspection_value = str(
                            solicitation.inspection_point).strip().lower()
                        if 'destination' in inspection_value:
                            return "D"
                        elif 'origin' in inspection_value:
                            return "O"
                        # If already "D" or "O", return as is
                        if inspection_value in ['d', 'o']:
                            return inspection_value.upper()
                else:
                    # For Solicitation objects, directly get the inspection_point value
                    if hasattr(obj, 'inspection_point') and obj.inspection_point:
                        inspection_value = str(
                            obj.inspection_point).strip().lower()
                        if 'destination' in inspection_value:
                            return "D"
                        elif 'origin' in inspection_value:
                            return "O"
                        # If already "D" or "O", return as is
                        if inspection_value in ['d', 'o']:
                            return inspection_value.upper()
            except Exception:
                # If any error occurs, fall through to normal source_field logic
                pass

        # SPECIAL HANDLING: Field position 49 - Quantity
        # This should ALWAYS come from the matched solicitation quantity.
        if field_position == 49 and obj:
            try:
                is_rfq_reply = obj.__class__.__name__ == 'RfqReply'
                if is_rfq_reply:
                    solicitation = None
                    if hasattr(obj, 'rfq') and obj.rfq and hasattr(obj.rfq, 'solicitation') and obj.rfq.solicitation:
                        solicitation = obj.rfq.solicitation
                    if not solicitation and hasattr(obj, 'find_matching_solicitation'):
                        solicitation = obj.find_matching_solicitation()
                    if solicitation and hasattr(solicitation, 'quantity') and solicitation.quantity:
                        return str(solicitation.quantity).strip()
                    if hasattr(obj, 'quantity') and obj.quantity:
                        return str(obj.quantity).strip()
                else:
                    if hasattr(obj, 'quantity') and obj.quantity:
                        return str(obj.quantity).strip()
            except Exception:
                # If any error occurs, fall through to normal source_field logic
                pass

        # SPECIAL HANDLING: Field position 3 - Small Business Set Aside Indicator
        # This should ALWAYS come from the solicitation's is_set_aside field (overrides custom_value)
        if field_position == 3 and obj:
            try:
                # Check if obj is an RfqReply instance
                is_rfq_reply = obj.__class__.__name__ == 'RfqReply'

                if is_rfq_reply:
                    # Try to get is_set_aside from related Solicitation
                    solicitation = None

                    # Method 1: Get from matched RFQ -> Solicitation
                    if hasattr(obj, 'rfq') and obj.rfq and hasattr(obj.rfq, 'solicitation') and obj.rfq.solicitation:
                        solicitation = obj.rfq.solicitation

                    # Method 2: Find matching solicitation using RfqReply's find_matching_solicitation method
                    if not solicitation:
                        solicitation = obj.find_matching_solicitation()

                    # If we found a solicitation, get its is_set_aside value
                    if solicitation and hasattr(solicitation, 'is_set_aside'):
                        is_set_aside = solicitation.is_set_aside
                        # True to "A" (8a Set-Aside), False to "N" (Unrestricted/Not Set-Aside)
                        if is_set_aside is True:
                            return "A"
                        elif is_set_aside is False:
                            return "N"
                        # If None or not set, fall through to normal logic
                else:
                    # For Solicitation objects, directly get the is_set_aside value
                    if hasattr(obj, 'is_set_aside'):
                        is_set_aside = obj.is_set_aside
                        # True to "A" (8a Set-Aside), False to "N" (Unrestricted/Not Set-Aside)
                        if is_set_aside is True:
                            return "A"
                        elif is_set_aside is False:
                            return "N"
                        # If None or not set, fall through to normal logic
            except Exception:
                # If any error occurs, fall through to normal source_field logic
                pass

        # SPECIAL HANDLING: Field position 103 - Actual Manufacturing/Production Source CAGE code
        # This should ALWAYS come from the solicitation's OEM CAGE code (overrides custom_value)
        if field_position == 103 and obj:
            try:
                # Check if obj is an RfqReply instance
                is_rfq_reply = obj.__class__.__name__ == 'RfqReply'

                if is_rfq_reply:
                    # Try to get CAGE code from related Solicitation
                    solicitation = None

                    # Method 1: Get from matched RFQ -> Solicitation
                    if hasattr(obj, 'rfq') and obj.rfq and hasattr(obj.rfq, 'solicitation') and obj.rfq.solicitation:
                        solicitation = obj.rfq.solicitation

                    # Method 2: Find matching solicitation using RfqReply's find_matching_solicitation method
                    if not solicitation:
                        solicitation = obj.find_matching_solicitation()

                    # If we found a solicitation, get its CAGE code
                    if solicitation and hasattr(solicitation, 'cage') and solicitation.cage:
                        cage_value = str(solicitation.cage).strip()
                        if cage_value:
                            return cage_value
                else:
                    # For Solicitation objects, directly get the CAGE code
                    if hasattr(obj, 'cage') and obj.cage:
                        cage_value = str(obj.cage).strip()
                        if cage_value:
                            return cage_value
            except Exception:
                # If any error occurs, fall through to normal source_field logic
                pass

        # SPECIAL HANDLING: Field position 44 - Solicitation Line Number
        # Always comes from the linked solicitation's solicitation_line_number field.
        if field_position == 44 and obj:
            try:
                is_rfq_reply = obj.__class__.__name__ == 'RfqReply'
                if is_rfq_reply:
                    solicitation = None
                    if hasattr(obj, 'rfq') and obj.rfq and hasattr(obj.rfq, 'solicitation') and obj.rfq.solicitation:
                        solicitation = obj.rfq.solicitation
                    if not solicitation:
                        solicitation = obj.find_matching_solicitation()
                    if solicitation:
                        val = getattr(solicitation, 'solicitation_line_number', None)
                        if val:
                            return str(val).strip()
                else:
                    val = getattr(obj, 'solicitation_line_number', None)
                    if val:
                        return str(val).strip()
            except Exception:
                pass

        # SPECIAL HANDLING: Field position 46 - Purchase Request Number
        # Always comes from the linked solicitation's purchase_request_number (or pr) field.
        if field_position == 46 and obj:
            try:
                is_rfq_reply = obj.__class__.__name__ == 'RfqReply'
                if is_rfq_reply:
                    solicitation = None
                    if hasattr(obj, 'rfq') and obj.rfq and hasattr(obj.rfq, 'solicitation') and obj.rfq.solicitation:
                        solicitation = obj.rfq.solicitation
                    if not solicitation:
                        solicitation = obj.find_matching_solicitation()
                    if solicitation:
                        val = (getattr(solicitation, 'purchase_request_number', None)
                               or getattr(solicitation, 'pr', None))
                        if val:
                            return str(val).strip()
                else:
                    val = (getattr(obj, 'purchase_request_number', None)
                           or getattr(obj, 'pr', None))
                    if val:
                        return str(val).strip()
            except Exception:
                pass

        # SPECIAL HANDLING: Field position 50 - Unit Price
        # For RFQ replies, use company_calculated_rate from the assessed BidAssessment when available.
        # Falls through to normal source_field logic if company_calculated_rate is not set.
        if field_position == 50 and obj:
            try:
                if obj.__class__.__name__ == 'RfqReply':
                    active_assessment = obj.assessments.filter(assessed=True).first()
                    if active_assessment is not None and active_assessment.company_calculated_rate is not None:
                        return str(active_assessment.company_calculated_rate)
            except Exception:
                pass

        # SPECIAL HANDLING: Field position 51 - Delivery Days
        # For RFQ replies, use company_delivery_days from the assessed BidAssessment when available.
        if field_position == 51 and obj:
            try:
                if obj.__class__.__name__ == 'RfqReply':
                    active_assessment = obj.assessments.filter(assessed=True).first()
                    if active_assessment is not None and active_assessment.company_delivery_days is not None:
                        return str(active_assessment.company_delivery_days)
                    if getattr(obj, 'oem_delivery_days', None) is not None:
                        return str(obj.oem_delivery_days)
            except Exception:
                pass

        # SPECIAL HANDLING: Field position 117 - Higher-Level Quality Indicator
        # This should ALWAYS come from the linked/matching solicitation's
        # higher_level_quality_indicator field (overrides custom_value).
        if field_position == 117 and obj:
            try:
                is_rfq_reply = obj.__class__.__name__ == 'RfqReply'
                if is_rfq_reply:
                    solicitation = None
                    if hasattr(obj, 'rfq') and obj.rfq and hasattr(obj.rfq, 'solicitation') and obj.rfq.solicitation:
                        solicitation = obj.rfq.solicitation
                    if not solicitation and hasattr(obj, 'find_matching_solicitation'):
                        solicitation = obj.find_matching_solicitation()
                    if solicitation:
                        val = getattr(solicitation, 'higher_level_quality_indicator', None)
                        if val is not None:
                            return str(val).strip().upper()
                else:
                    val = getattr(obj, 'higher_level_quality_indicator', None)
                    if val is not None:
                        return str(val).strip().upper()
            except Exception:
                # If any error occurs, fall through to normal source_field logic
                pass

        # Use custom value if set (non-empty)
        # Empty string means "use source_field", so we check for truthy value
        if self.custom_value and self.custom_value.strip():
            return self.custom_value.strip()

        # Helper to consistently format different value types (dates, decimals, strings)
        def _format_value(value):
            """
            Normalize value for export:
            - Dates to MM/DD/YYYY (e.g. 08/17/2022)
            - Known date strings (e.g. 12-02-2025, 2025-12-02) to MM/DD/YYYY
            - Decimals to plain string
            - Everything else to str(value)
            """
            from datetime import datetime

            if value is None:
                return ""

            # Handle date/datetime objects
            if hasattr(value, "strftime"):
                return value.strftime("%m/%d/%Y")

            # Handle Decimal fields
            if hasattr(value, "quantize"):
                return str(value)

            # Normalize common date string formats to MM/DD/YYYY
            if isinstance(value, str):
                s = value.strip()
                if not s:
                    return ""

                # For solicitation number exports, remove hyphens so
                # e.g. "SPE8E8-26-T-0810" becomes "SPE8E826T0810"
                try:
                    # Detect solicitation number fields (usually position 1)
                    is_solicitation_number_field = (
                        (self.source_field and self.source_field.lower()
                         in ("solicitation", "solicitation_number"))
                        or getattr(self.field_definition, "position", None) == 1
                    )
                except Exception:
                    is_solicitation_number_field = False

                # Detect part number fields by common source/column names
                try:
                    is_part_number_field = False
                    if self.source_field:
                        sf = self.source_field.lower()
                        if sf in ("part_number", "partnumber", "part_no", "part"):
                            is_part_number_field = True
                        elif "part" in sf and "department" not in sf:
                            is_part_number_field = True

                    if not is_part_number_field:
                        col_name = getattr(
                            self.field_definition, "column_name", "")
                        if isinstance(col_name, str) and "part" in col_name.lower():
                            is_part_number_field = True
                except Exception:
                    is_part_number_field = False

                if is_solicitation_number_field or is_part_number_field:
                    s = s.replace("-", "")

                # Try multiple common date formats
                date_formats = (
                    "%m-%d-%Y",  # 12-02-2025
                    "%Y-%m-%d",  # 2025-12-02
                    "%m/%d/%Y",  # 12/02/2025
                    "%Y/%m/%d",  # 2025/12/02
                )
                for fmt in date_formats:
                    try:
                        dt = datetime.strptime(s, fmt)
                        return dt.strftime("%m/%d/%Y")
                    except ValueError:
                        continue

                # Normalize Unit of Issue fields to 2-letter code (e.g., "EA (EACH)" -> "EA")
                is_unit_field = False
                try:
                    if (self.source_field and self.source_field.endswith("unit")) or getattr(self.field_definition, "position", None) == 48:
                        is_unit_field = True
                except Exception:
                    is_unit_field = False

                if is_unit_field:
                    import re

                    # Take the leading alphabetic code before any space or '('
                    m = re.match(r"\s*([A-Za-z]{1,4})", s)
                    if m:
                        code = m.group(1).upper()
                        # Most DLA unit codes are 2 characters; trim longer ones
                        return code[:2]

                return s

            return str(value)

        # Get value from source field
        if self.source_field and obj:
            import logging
            logger = logging.getLogger(__name__)
            try:
                # Check if obj is an RfqReply instance
                is_rfq_reply = obj.__class__.__name__ == 'RfqReply'

                # Handle nested attributes like "user.cage" or "rfq.solicitation.solicitation"
                if '.' in self.source_field:
                    parts = self.source_field.split('.')
                    value = obj
                    for part in parts:
                        value = getattr(value, part, None)
                        if value is None:
                            break
                    if value is not None:
                        return _format_value(value)
                else:
                    # Direct attribute access
                    # For RfqReply, try to get from related Solicitation first if available
                    if is_rfq_reply:
                        # Reverse mapping: RfqReply field -> Solicitation field
                        # This allows us to try getting from Solicitation first when source_field is an RfqReply field
                        rfq_reply_to_solicitation_map = {
                            'solicitation_number': 'solicitation',
                            'nsn': 'NSN',
                            'quantity': 'quantity',
                            'unit': 'unit',
                            'received_date': 'return_by_date',  # Try solicitation return_by_date first
                        }

                        # Mapping of Solicitation field names to RfqReply field names (for when source_field is Solicitation field)
                        solicitation_to_rfq_reply_map = {
                            'solicitation': 'solicitation_number',
                            'NSN': 'nsn',
                            'nsn': 'nsn',
                            'quantity': 'quantity',
                            'unit': 'unit',
                            'return_by_date': 'received_date',  # Use received_date as fallback
                            'cage': None,  # Will try rfq.solicitation.cage, then user.cage
                            'pr': None,  # Purchase Request - only in Solicitation
                        }

                        # First, try to get from related Solicitation if source_field is an RfqReply field
                        if self.source_field in rfq_reply_to_solicitation_map:
                            solicitation_field = rfq_reply_to_solicitation_map[self.source_field]
                            # Try to get from related Solicitation first
                            if hasattr(obj, 'rfq') and obj.rfq and hasattr(obj.rfq, 'solicitation') and obj.rfq.solicitation:
                                solicitation_value = getattr(
                                    obj.rfq.solicitation, solicitation_field, None)
                                if solicitation_value and solicitation_value != "":
                                    return _format_value(solicitation_value)

                            # Fall back to RfqReply direct field if solicitation doesn't have it or RFQ not linked
                            if hasattr(obj, self.source_field):
                                value = getattr(obj, self.source_field, None)
                                if value is not None and value != "":
                                    return _format_value(value)
                            # If we found a value from this mapping, don't continue to other checks
                            # But if we didn't find anything, continue to check other mappings

                        # Check if source_field maps to a Solicitation field
                        if self.source_field in solicitation_to_rfq_reply_map:
                            rfq_reply_field = solicitation_to_rfq_reply_map[self.source_field]
                            # Try to get from related Solicitation first
                            if hasattr(obj, 'rfq') and obj.rfq and hasattr(obj.rfq, 'solicitation') and obj.rfq.solicitation:
                                solicitation_field = self.source_field
                                # Special handling for 'cage' - try solicitation.cage first
                                if self.source_field == 'cage':
                                    solicitation_value = getattr(
                                        obj.rfq.solicitation, 'cage', None)
                                    if solicitation_value:
                                        return str(solicitation_value)
                                    # Fall back to user.cage
                                    user_cage = getattr(obj.user, 'cage', None)
                                    if user_cage:
                                        return str(user_cage)
                                else:
                                    # Try to get from solicitation
                                    solicitation_value = getattr(
                                        obj.rfq.solicitation, solicitation_field, None)
                                    if solicitation_value and solicitation_value != "":
                                        return _format_value(solicitation_value)

                            # Fall back to RfqReply direct field if available
                            if rfq_reply_field and hasattr(obj, rfq_reply_field):
                                value = getattr(obj, rfq_reply_field, None)
                                if value is not None and value != "":
                                    return _format_value(value)

                        # If not in mapping, try direct access on RfqReply
                        if hasattr(obj, self.source_field):
                            value = getattr(obj, self.source_field, None)
                            if value is not None and value != "":
                                return _format_value(value)
                    else:
                        # For Solicitation objects, direct attribute access
                        value = getattr(obj, self.source_field, None)
                        if value is not None:
                            formatted = _format_value(value)
                            return formatted if formatted != "" else ""
            except (AttributeError, TypeError):
                return ""

        # Return default value from field definition
        # If default is "Blank" or placeholder text like "RFQ Requirement", return empty string instead
        default_val = self.field_definition.default_value or ""
        if not default_val:
            return ""

        # Treat placeholder/default text values as empty
        default_upper = default_val.upper().strip()
        placeholder_texts = [
            "BLANK",
            "RFQ REQUIREMENT",
            "RFQ SOLICITATION #",
            "RFQ RETURN BY DATE",
        ]

        if default_upper in placeholder_texts:
            return ""

        return default_val


class RfqReplyExportOverride(models.Model):
    """
    Per-RFQ override of export values (121 fields) for a single RFQ reply.
    Does NOT change the global UserExportConfiguration; only affects that RFQ.
    """
    rfq_reply = models.OneToOneField(
        RfqReply,
        on_delete=models.CASCADE,
        related_name='export_override'
    )
    # Store the 121 values as a JSON array (index 0 == position 1, etc.)
    data = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "RFQ Reply Export Override"
        verbose_name_plural = "RFQ Reply Export Overrides"
        indexes = [
            # Single field indexes
            models.Index(fields=['rfq_reply']),  # For get_or_create lookups
            # For ordering/filtering by last update
            models.Index(fields=['updated_at']),
        ]

    def __str__(self):
        return f"Export override for RFQ Reply {self.rfq_reply_id}"
    
class RFQIDTemplate(models.Model):
    """
    User-configurable RFQ ID generation template.
    Allows users to customize the format of RFQ unique IDs.
    """
    
    COMPONENT_CHOICES = [
        ('company_initial', 'Company Initial'),
        ('dla', 'DLA (fixed)'),
        ('date', 'Date'),
        ('cage_code', 'OEM Cage Code'),
        ('sequence', 'Sequence Number'),
        ('custom_text', 'Custom Text'),
    ]
    
    DATE_FORMAT_CHOICES = [
        ('MMDDYY', 'MMDDYY (010125)'),
        ('DDMMYY', 'DDMMYY (010125)'),
        ('YYMMDD', 'YYMMDD (250101)'),
        ('YYYY-MM-DD', 'YYYY-MM-DD (2025-01-01)'),
        ('YYYYMMDD', 'YYYYMMDD (20250101)'),
        ('MMM-YY', 'MMM-YY (Jan-25)'),
        ('MMMM-YYYY', 'MMMM-YYYY (January-2025)'),
        ('MM/DD', 'MM/DD (01/01)'),
    ]
    
    SEPARATOR_CHOICES = [
        ('-', 'Hyphen (-)'),
        ('_', 'Underscore (_)'),
        ('', 'No separator'),
        ('.', 'Period (.)'),
        ('/', 'Forward slash (/)'),
    ]
    
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='rfq_id_template')
    
    # Components: ordered list of what to include in RFQ ID
    # Stored as JSON: [{'component': 'company_initial'}, {'component': 'dla'}, ...]
    components = models.JSONField(default=list, help_text="Ordered list of RFQ ID components")
    
    # Separator between components
    separator = models.CharField(
        max_length=5,
        choices=SEPARATOR_CHOICES,
        default='-',
        help_text="Character(s) to separate components"
    )
    
    # Date format (only used if 'date' component is included)
    date_format = models.CharField(
        max_length=15,
        choices=DATE_FORMAT_CHOICES,
        default='MMDDYY',
        help_text="Format for date component"
    )
    
    # Custom text (for custom_text component)
    custom_text = models.CharField(
        max_length=50,
        blank=True,
        help_text="Custom text to include if 'custom_text' component is selected"
    )
    
    # Sequence settings
    sequence_padding = models.IntegerField(
        default=6,
        help_text="Number of digits for sequence (e.g., 6 = 000001)"
    )
    
    # Auto-reset sequence yearly/monthly
    RESET_PERIOD_CHOICES = [
        ('never', 'Never reset'),
        ('yearly', 'Reset every year'),
        ('monthly', 'Reset every month'),
        ('daily', 'Reset every day'),
    ]
    
    sequence_reset_period = models.CharField(
        max_length=10,
        choices=RESET_PERIOD_CHOICES,
        default='never',
        help_text="When to reset sequence counter"
    )
    
    last_sequence_number = models.IntegerField(
        default=0,
        help_text="Last used sequence number"
    )
    
    last_sequence_reset_date = models.DateField(
        auto_now_add=True,
        help_text="Date when sequence was last reset"
    )
    
    # UI settings
    preview = models.CharField(
        max_length=100,
        blank=True,
        help_text="Preview of what the RFQ ID will look like"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "RFQ ID Template"
        verbose_name_plural = "RFQ ID Templates"
    
    def __str__(self):
        return f"RFQ ID Template for {self.user.username}"
    
    @classmethod
    def get_default_template(cls):
        """Return the default RFQ ID template"""
        return {
            'components': [
                {'component': 'company_initial'},
                {'component': 'dla'},
                {'component': 'date'},
                {'component': 'cage_code'},
                {'component': 'sequence'},
            ],
            'separator': '-',
            'date_format': 'MMDDYY',
            'custom_text': '',
            'sequence_padding': 6,
            'sequence_reset_period': 'never',
        }
    
    def get_next_sequence(self):
        """Get and increment the next sequence number"""
        # Check if sequence should be reset
        if self.should_reset_sequence():
            self.last_sequence_number = 1
            self.last_sequence_reset_date = timezone.now().date()
        else:
            self.last_sequence_number += 1
        
        self.save(update_fields=['last_sequence_number', 'last_sequence_reset_date'])
        return self.last_sequence_number
    
    def should_reset_sequence(self):
        """Check if sequence should be reset based on reset_period"""
        from datetime import datetime, date
        
        if self.sequence_reset_period == 'never':
            return False
        
        today = date.today()
        last_reset = self.last_sequence_reset_date
        
        if self.sequence_reset_period == 'daily':
            return last_reset < today
        elif self.sequence_reset_period == 'monthly':
            return (last_reset.year < today.year or 
                   (last_reset.year == today.year and last_reset.month < today.month))
        elif self.sequence_reset_period == 'yearly':
            return last_reset.year < today.year
        
        return False
    
    def generate_rfq_id(self, user, oem_cage_code, solicitation_id):
        """
        Generate RFQ ID based on user's template configuration.
        
        Args:
            user: CustomUser object
            oem_cage_code: The OEM's cage code
            solicitation_id: The solicitation ID (for fallback if no cage code)
        
        Returns:
            Generated RFQ ID string
        """
        from datetime import datetime
        
        parts = []
        
        for comp_obj in self.components:
            component = comp_obj.get('component')
            
            if component == 'company_initial':
                if user.company_initial:
                    parts.append(user.company_initial.upper())
            
            elif component == 'dla':
                parts.append('DLA')
            
            elif component == 'date':
                date_str = self._format_date(datetime.now(), self.date_format)
                parts.append(date_str)
            
            elif component == 'cage_code':
                if oem_cage_code:
                    parts.append(oem_cage_code.upper())
                else:
                    parts.append(f"SOL{solicitation_id}")
            
            elif component == 'sequence':
                seq_num = self.get_next_sequence()
                padded_seq = str(seq_num).zfill(self.sequence_padding)
                parts.append(padded_seq)
            
            elif component == 'custom_text':
                if self.custom_text:
                    parts.append(self.custom_text)
        
        return self.separator.join(parts)
    
    @staticmethod
    def _format_date(dt, fmt):
        """Format datetime object according to date_format choice"""
        if fmt == 'MMDDYY':
            return dt.strftime('%m%d%y')
        elif fmt == 'DDMMYY':
            return dt.strftime('%d%m%y')
        elif fmt == 'YYMMDD':
            return dt.strftime('%y%m%d')
        elif fmt == 'YYYY-MM-DD':
            return dt.strftime('%Y-%m-%d')
        elif fmt == 'YYYYMMDD':
            return dt.strftime('%Y%m%d')
        elif fmt == 'MMM-YY':
            return dt.strftime('%b-%y')
        elif fmt == 'MMMM-YYYY':
            return dt.strftime('%B-%Y')
        elif fmt == 'MM/DD':
            return dt.strftime('%m/%d')
        else:
            return dt.strftime('%m%d%y')
    
    def generate_preview(self, user):
        """Generate a preview of what RFQ ID will look like"""
        preview = self.generate_rfq_id(
            user=user,
            oem_cage_code='ABC12',
            solicitation_id=1
        )
        self.preview = preview
        return preview

    def get_next_rfq_id_without_saving(self, user, oem_cage_code, solicitation_id):
        """
        Generate next RFQ ID WITHOUT incrementing sequence yet.
        Only increments when you call finalize_sequence_after_success()

        Returns: {'rfq_id': '...', 'next_sequence': int}
        """
        # Calculate next sequence WITHOUT saving
        next_sequence = self.last_sequence_number + 1

        # Build RFQ ID components
        rfq_parts = []

        for component in self.components:
            comp_type = component.get('component')

            if comp_type == 'company_initial':
                if user.company_initial and user.company_initial.strip():
                    rfq_parts.append(user.company_initial.upper())
                else:
                    if user.companyName and len(user.companyName) >= 3:
                        rfq_parts.append(user.companyName[:3].upper())
                    else:
                        rfq_parts.append("COM")

            elif comp_type == 'dla':
                rfq_parts.append("DLA")

            elif comp_type == 'date':
                from django.utils.timezone import now
                date_format = self.date_format.upper()
                if date_format == 'MMDDYY':
                    rfq_parts.append(now().strftime('%m%d%y'))
                elif date_format == 'DDMMYY':
                    rfq_parts.append(now().strftime('%d%m%y'))
                elif date_format == 'YYYYMMDD':
                    rfq_parts.append(now().strftime('%Y%m%d'))
                else:
                    rfq_parts.append(now().strftime('%m%d%y'))

            elif comp_type == 'cage_code':
                if oem_cage_code:
                    rfq_parts.append(oem_cage_code.upper())
                else:
                    rfq_parts.append(f"SOL{solicitation_id}")

            elif comp_type == 'sequence':
                padding = self.sequence_padding
                rfq_parts.append(f"{next_sequence:0{padding}d}")

            elif comp_type == 'custom_text':
                if self.custom_text:
                    rfq_parts.append(self.custom_text)

        rfq_id = self.separator.join(rfq_parts)

        return {
            'rfq_id': rfq_id,
            'next_sequence': next_sequence,
        }

    def finalize_sequence_after_success(self, next_sequence):
        """
        ONLY call this AFTER email succeeds!
        Persists the sequence number that was used (no reset_sequence helper on this model).

        Args:
            next_sequence: The sequence number that was generated
        """
        self.last_sequence_number = next_sequence
        self.save(update_fields=['last_sequence_number'])


class BidReferenceTemplate(models.Model):
    """
    User-configurable template for BID REF. values used on bid assessments
    and the exported quotes analysis Excel file.
    """

    COMPONENT_CHOICES = [
        ('company_initial', 'Company Initial'),
        ('dla', 'DLA (fixed)'),
        ('date', 'Date'),
        ('solicitation_number', 'Solicitation Number'),
        ('sequence', 'Sequence Number'),
        ('custom_text', 'Custom Text'),
    ]

    DATE_FORMAT_CHOICES = RFQIDTemplate.DATE_FORMAT_CHOICES
    SEPARATOR_CHOICES = RFQIDTemplate.SEPARATOR_CHOICES
    RESET_PERIOD_CHOICES = RFQIDTemplate.RESET_PERIOD_CHOICES

    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='bid_reference_template'
    )
    components = models.JSONField(
        default=list,
        help_text="Ordered list of bid reference components"
    )
    separator = models.CharField(
        max_length=5,
        choices=SEPARATOR_CHOICES,
        default='-',
        help_text="Character(s) to separate components"
    )
    date_format = models.CharField(
        max_length=15,
        choices=DATE_FORMAT_CHOICES,
        default='MMDDYY',
        help_text="Format for date component"
    )
    custom_text = models.CharField(
        max_length=50,
        blank=True,
        help_text="Custom text to include if 'custom_text' component is selected"
    )
    sequence_padding = models.IntegerField(
        default=5,
        help_text="Number of digits for sequence (e.g., 5 = 00001)"
    )
    sequence_reset_period = models.CharField(
        max_length=10,
        choices=RESET_PERIOD_CHOICES,
        default='never',
        help_text="When to reset sequence counter"
    )
    last_sequence_number = models.IntegerField(
        default=0,
        help_text="Last used bid reference sequence number"
    )
    last_sequence_reset_date = models.DateField(
        auto_now_add=True,
        help_text="Date when sequence was last reset"
    )
    preview = models.CharField(
        max_length=100,
        blank=True,
        help_text="Preview of what the bid reference will look like"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bid Reference Template"
        verbose_name_plural = "Bid Reference Templates"

    def __str__(self):
        return f"Bid Reference Template for {self.user.username}"

    @classmethod
    def get_default_template(cls):
        return {
            'components': [
                {'component': 'company_initial'},
                {'component': 'custom_text'},
                {'component': 'sequence'},
            ],
            'separator': '-',
            'date_format': 'MMDDYY',
            'custom_text': 'BID',
            'sequence_padding': 5,
            'sequence_reset_period': 'never',
        }

    def should_reset_sequence(self):
        from datetime import date

        if self.sequence_reset_period == 'never':
            return False

        today = date.today()
        last_reset = self.last_sequence_reset_date

        if self.sequence_reset_period == 'daily':
            return last_reset < today
        if self.sequence_reset_period == 'monthly':
            return (
                last_reset.year < today.year or
                (last_reset.year == today.year and last_reset.month < today.month)
            )
        if self.sequence_reset_period == 'yearly':
            return last_reset.year < today.year

        return False

    def get_next_sequence(self):
        if self.should_reset_sequence():
            self.last_sequence_number = 1
            self.last_sequence_reset_date = timezone.now().date()
        else:
            self.last_sequence_number += 1

        self.save(update_fields=['last_sequence_number', 'last_sequence_reset_date'])
        return self.last_sequence_number


class BidAssessment(models.Model):
    SOURCE_CHOICES = [
        ('email', 'Email'),
        ('fax', 'Fax'),
        ('phone', 'Phone'),
        ('portal', 'Portal'),
        ('mail', 'Mail'),
    ]

    rfq_reply = models.ForeignKey(
        'RfqReply',
        on_delete=models.CASCADE,
        related_name='assessments'
    )

    # Solicitation Info
    bid_reference = models.CharField(max_length=50, null=True, blank=True)
    source_of_quote = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='email')
    date_quote_received = models.DateField(null=True, blank=True)

    # Company Pricing (per-assessment)
    oem_credit_card_charge_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    general_and_admin = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    profit_margin_percent = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    company_validity_days = models.IntegerField(null=True, blank=True)
    estimated_profit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    company_delivery_days = models.IntegerField(null=True, blank=True, default=30)
    company_adjusted_rate = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True)

    # Calculated fields (auto-filled by JS, editable/saveable per assessment)
    oem_subtotal = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    oem_total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    INTEREST_CHOICES = [
        ('cod_cc', 'COD / CC'),
        ('50_50', '50/50'),
        ('cia_prepay', 'CIA / PREPAY'),
    ]
    interest_type = models.CharField(max_length=20, choices=INTEREST_CHOICES, default='cod_cc')
    interest_cod_cc = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    interest_50_50 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    interest_cia_prepay = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    unit_container = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    shipping_boxing = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    shipping_cost_to_buyer = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    supplies_inspection = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    packaging_inspection = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    oem_calculated_rate = models.DecimalField(max_digits=14, decimal_places=5, null=True, blank=True)
    company_calculated_rate = models.DecimalField(max_digits=14, decimal_places=5, null=True, blank=True)
    contract_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    assessed = models.BooleanField(default=False, help_text="Mark this assessment as complete")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Assessment {self.pk} - RFQ {self.rfq_reply_id}"
