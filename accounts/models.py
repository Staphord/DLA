from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid
from datetime import timedelta, datetime
from django.utils import timezone
from django.core.validators import MaxValueValidator

# Create your models here.
# Custom User model for authentication
class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
        ('client', 'Client'),
        ('admin', 'Admin')
    )
    AGREEMENT_TYPE_CHOICES = (
        ('NAP', 'NAP'),
        ('FSS', 'FSS'),
        ('BOA', 'BOA'),
        ('BPA', 'BPA'),
    )
    companyName = models.CharField(max_length=50)
    phone = models.CharField(max_length=13)
    email = models.EmailField(unique=True)
    address = models.CharField(max_length=255)
    is_email_verified = models.BooleanField(default=False)
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='client')
    logo = models.ImageField(upload_to='logos/', blank=True, null=True)
    fax = models.CharField(max_length=20, blank=True, null=True)
    cage = models.CharField(max_length=10, blank=True, null=True)
    website = models.CharField(max_length=100, blank=True, null=True)
    company_initial = models.CharField(max_length=3, blank=True, null=True)
    title = models.CharField(max_length=100, blank=True, null=True)
    personal_email = models.EmailField(unique=True, blank=True, null=True)
    added_days = models.IntegerField(default=0, blank=True, help_text="Days added to company delivery days on bid assessments")

    # Tenant / company profile fields required for DIBBS-style compliance
    legal_name = models.CharField(max_length=255, blank=True, null=True)
    uei = models.CharField(max_length=20, blank=True, null=True)
    naics_code = models.CharField(max_length=50, blank=True, null=True)
    business_size = models.CharField(max_length=50, blank=True, null=True)

    is_wosb = models.BooleanField(default=False)
    is_edwosb = models.BooleanField(default=False)
    is_hubzone = models.BooleanField(default=False)
    is_8a = models.BooleanField(default=False)
    is_sdvosb = models.BooleanField(default=False)

    is_iso_9001_certified = models.BooleanField(default=False)
    iso_9001_expiry = models.DateField(blank=True, null=True)
    is_as9100_certified = models.BooleanField(default=False)
    as9100_expiry = models.DateField(blank=True, null=True)
    is_as9003_certified = models.BooleanField(default=False)
    as9003_expiry = models.DateField(blank=True, null=True)
    is_jcp_certified = models.BooleanField(default=False)
    jcp_expiry = models.DateField(blank=True, null=True)
    is_qsl_certified = models.BooleanField(default=False)
    qsl_expiry = models.DateField(blank=True, null=True)
    is_qpl_certified = models.BooleanField(default=False)
    qpl_expiry = models.DateField(blank=True, null=True)
    is_qml_certified = models.BooleanField(default=False)
    qml_expiry = models.DateField(blank=True, null=True)

    agreement_type = models.CharField(
        max_length=50,
        choices=AGREEMENT_TYPE_CHOICES,
        blank=True,
        null=True,
    )
    contract_number = models.CharField(max_length=100, blank=True, null=True)
    agreement_expiry = models.DateField(blank=True, null=True)

    default_fob = models.CharField(max_length=50, blank=True, null=True)
    default_origin_country = models.CharField(max_length=50, blank=True, null=True)
    default_moq = models.CharField(max_length=50, blank=True, null=True)
    default_lead_time_days = models.PositiveIntegerField(default=0)
    immediate_shipment_allowed = models.BooleanField(default=False)

    JOINT_VENTURE_CHOICES = (
        ('JV', 'JV - Joint venture complying with 13 CFR 121.103(h) and 125'),
        ('JN', 'JN - Not a joint venture complying with 13 CFR 121.103(h) and 125'),
    )
    AFFIRMATIVE_ACTION_CHOICES = (
        ('Y6', 'Y6 - Developed and on File'),
        ('N6', 'N6 - Not Developed and Not on File'),
        ('NH', 'NH - No Previous Contracts Subject to Requirements'),
        ('NA', 'NA - Not Applicable'),
    )
    PREVIOUS_CONTRACTS_CHOICES = (
        ('Y4', 'Y4 - Participated and Filed'),
        ('Y5', 'Y5 - Participated and Not Filed'),
        ('N4', 'N4 - Not Participated'),
        ('NA', 'NA - Not Applicable'),
    )
    ALTERNATE_DISPUTES_CHOICES = (
        ('A', 'A - Agree To Use Alternate Disputes Resolution'),
        ('B', 'B - Do Not Agree To Use Alternate Disputes Resolution'),
    )
    PROMPT_PAYMENT_CHOICES = (
        ('1', '1 - Net 30'),
        ('10', '10 - 2% 10 Days'),
        ('3', '3 - 1/2% 20 Days'),
        ('6', '6 - 1/2% 10 Days'),
        ('8', '8 - 1/4% 20 Days'),
    )
    SMALL_BUSINESS_REPRESENTATION_CHOICES = (
        ('A', 'A - Large Business/Other Business'),
        ('B', 'B - Small Business'),
        ('C', 'C - Nonprofit Institution'),
        ('E', 'E - Educational Institution (other than HBCU or Minority)'),
        ('F', 'F - Historically Black College or University (HBCU)'),
        ('G', 'G - JWOD Participating Nonprofit Agency'),
        ('M', 'M - Small Disadvantaged Business'),
        ('P', 'P - Minority Institution (other than HBCU)'),
        ('X', 'X - Intragovernmental'),
    )
    MEETS_PACKAGING_CHOICES = (
        ('Y', 'Y - Yes'),
        ('N', 'N - No'),
    )
    MATERIAL_REQUIREMENTS_CHOICES = (
        ('0', '0 - No (Not Other Than New, Reconditioned, Remanufactured or Unused Former Government Surplus)'),
        ('1', '1 - Yes - Other Than New (Used)'),
        ('2', '2 - Yes - Reconditioned'),
        ('3', '3 - Yes - Remanufactured'),
        ('4', '4 - Yes - Unused Former Government Surplus'),
    )
    CHILD_LABOR_CHOICES = (
        ('N', 'N - No'),
        ('U', 'U - May Supply, but not aware of any such use of child labor based on good faith effort'),
        ('Y', 'Y - Yes'),
    )

    joint_venture_code = models.CharField(max_length=2, choices=JOINT_VENTURE_CHOICES, blank=True, default='')
    joint_venture_remarks = models.CharField(max_length=255, blank=True, default='')
    affirmative_action_code = models.CharField(max_length=2, choices=AFFIRMATIVE_ACTION_CHOICES, blank=True, default='')
    previous_contracts_code = models.CharField(max_length=2, choices=PREVIOUS_CONTRACTS_CHOICES, blank=True, default='')
    alternate_disputes_resolution = models.CharField(max_length=1, choices=ALTERNATE_DISPUTES_CHOICES, blank=True, default='')
    prompt_payment_terms_code = models.CharField(max_length=2, choices=PROMPT_PAYMENT_CHOICES, blank=True, default='')
    child_labor_certification_code = models.CharField(max_length=1, choices=CHILD_LABOR_CHOICES, blank=True, default='')
    inspection_packaging_cage = models.CharField(max_length=5, blank=True, default='')
    inspection_supplies_cage = models.CharField(max_length=5, blank=True, default='')

    small_business_representation_code = models.CharField(
        max_length=1, choices=SMALL_BUSINESS_REPRESENTATION_CHOICES, blank=True, default='')
    default_quote_valid_days = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(999)],
        help_text="Default days quote is valid (export position 027); supplier must confirm per quote")
    default_meets_packaging = models.CharField(
        max_length=1, choices=MEETS_PACKAGING_CHOICES, blank=True, default='',
        help_text="Default packaging-acceptance answer (export position 028)")
    default_material_requirements = models.CharField(
        max_length=1, choices=MATERIAL_REQUIREMENTS_CHOICES, blank=True, default='',
        help_text="Default new-material policy (export position 067)")
    default_quantity_variance_plus = models.CharField(
        max_length=2, blank=True, default='', help_text="Default plus quantity variance % (export position 096)")
    default_quantity_variance_minus = models.CharField(
        max_length=2, blank=True, default='', help_text="Default minus quantity variance % (export position 097)")

    verification_status = models.CharField(max_length=30, default='pending', blank=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    verified_by = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='verified_customers')

    def __str__(self):
        return self.username
    
class VerificationToken(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)  # Use CustomUser
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

### Model to store Invitation data
class Invitation(models.Model):
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    
    def __str__(self):
        return self.email
    
    def save(self, *args, **kwargs):
        if not self.expires_at:
            # Set expiry to 7 days from creation by default
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)
    
    @property
    def is_valid(self):
        return not self.used and timezone.now() < self.expires_at
