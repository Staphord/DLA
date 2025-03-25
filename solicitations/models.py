import datetime
from django.db import models
from django.conf import settings
from accounts.models import CustomUser


### This model store solicitations data
class Solicitation(models.Model):
    cage = models.CharField(max_length=5)
    nomenclature = models.CharField(max_length=50)
    status = models.CharField(max_length=10, blank=True, null=True)
    part_number = models.CharField(max_length=25, blank=True, null=True)
    pr = models.CharField(max_length=15, blank=True, null=True)
    unit = models.CharField(max_length=15, blank=True, null=True)
    quantity = models.CharField(max_length=20)
    NSN = models.CharField(max_length=20,default='1')
    issued_date = models.CharField(max_length=20)
    return_by_date = models.CharField(max_length=20)
    organization_name = models.CharField(max_length=20,blank=True)
    street_name = models.CharField(max_length=20,blank=True)
    city = models.CharField(max_length=20,blank=True)
    fax = models.CharField(max_length=20,blank=True)
    phone = models.CharField(max_length=20,blank=True)
    postal_code = models.CharField(max_length=20,blank=True)
    email = models.EmailField(blank=True)

    def __str__(self):
        return f"Solicitation-{self.cage} ({self.nomenclature})"
    
def get_default_send_time():
    return datetime.time(0, 0) 

### This model stores OEM data
class OEM(models.Model):
    name = models.CharField(max_length=50)
    cage = models.CharField(max_length=5)
    email = models.EmailField()
    phone = models.CharField(max_length=14)
    fax = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=50)
    street = models.CharField(max_length=50)
    postal_code = models.CharField(max_length=50)

    # Many-to-Many relationship with CustomUser through OEMUser
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, through='OEMUser', related_name='oems')

    def __str__(self):
        return f"{self.name} ({self.cage})"

### This model ensure oem belongs to a user depending on the sent emails
class OEMUser(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    oem = models.ForeignKey(OEM, on_delete=models.CASCADE)
    is_disabled = models.BooleanField(default=False)
    reason = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        unique_together = ('user', 'oem')

    def __str__(self):
        return f"{self.user.username} - {self.oem.name} (Disabled: {self.is_disabled})"

## Model for send RFQ
class RFQ(models.Model):
    solicitation = models.ForeignKey(Solicitation, on_delete=models.SET_NULL,null=True,blank=True, related_name='rfqs')
    oem = models.ForeignKey(OEM, on_delete=models.CASCADE, related_name='rfqs')
    unique_id = models.CharField(max_length=5, unique=True, editable=False)  # Unique 5-character ID
    sent_at = models.DateField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_rfqs')

    def __str__(self):
        return f"RFQ-{self.unique_id} for {self.solicitation.nomenclature}"

## This model is for replied RFQS
class RFQReply(models.Model):
    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name='replies')
    price = models.DecimalField(max_digits=10, decimal_places=2)  # Price quoted
    delivery_mode = models.CharField(
        max_length=5,
        choices=[('Free', 'Free'), ('Paid', 'Paid')]
    )
    created_at = models.DateField(auto_now_add=True)
    short_note = models.TextField(max_length=1000, blank=True, null=True)
    document = models.FileField(upload_to='replies/documents/', blank=True, null=True)
    rfq_creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='rfq_replies',
        editable=False
    )  # Tracks the user who created the RFQ

    is_viewed = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Automatically associate the reply with the RFQ creator
        if not self.rfq_creator:
            self.rfq_creator = self.rfq.created_by
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Reply for RFQ-{self.rfq.unique_id} (Sent by {self.rfq_creator.username})"

## This model is for Email template
class MailTemplate(models.Model):
    body = models.TextField(default="I hope this message finds you well. We are currently looking for the following item. Kindly provide your lowest possible price.")
    salutation = models.CharField(max_length=20, default='Dear Mr/Ms')
    heading = models.CharField(max_length=50,default="REQUEST FOR QUOTATION")
    userMail = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

## This model is for Github Workflow actions (setting of cron job)
class GitHubWorkflow(models.Model):
    name = models.CharField(max_length=255, default="Extract Data Every 10 Minutes")
    cron_schedule = models.CharField(max_length=50, default="0 1 * * *")  # Default: 1 AM daily
    last_updated = models.DateTimeField(auto_now=True)

## This model ensure edits belong to user who made changes on the respective oem
class UserOEMCustomization(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    oem = models.ForeignKey('OEM', on_delete=models.CASCADE)
    custom_name = models.CharField(max_length=50, blank=True, null=True)
    custom_email = models.EmailField(blank=True, null=True)
    custom_phone = models.CharField(max_length=14, blank=True, null=True)
    custom_fax = models.CharField(max_length=20, blank=True, null=True)
    custom_city = models.CharField(max_length=50, blank=True, null=True)
    custom_street = models.CharField(max_length=50, blank=True, null=True)
    custom_postal_code = models.CharField(max_length=50, blank=True, null=True)
    
    class Meta:
        unique_together = ('user', 'oem')
        
    def __str__(self):
        return f"{self.user.username}'s customization of {self.oem.name}"
    
def get_default_send_time():
    # Return time in 24-hour format, e.g., 00:00 for midnight
    return datetime.time(0, 0)  # Default to midnight (00:00)


### This model is for auto email configurations
class EmailSettings(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='email_settings')
    auto_send = models.BooleanField(default=False, help_text="Toggle automatic email sending")
    
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
    
    send_day = models.CharField(max_length=20, choices=DAY_CHOICES, default=DAILY)
    send_time = models.TimeField(default=get_default_send_time)  # Default in 24-hour format
    
    def __str__(self):
        # Ensure send_time is displayed in 24-hour format
        formatted_time = self.send_time.strftime('%H:%M')  # 24-hour format (HH:mm)
        if self.send_day == self.DAILY:
            return f"{self.user.username}'s Email Settings (Daily at {formatted_time})"
        return f"{self.user.username}'s Email Settings ({self.get_send_day_display()} at {formatted_time})"
    
## This model track the stattus of the email
class SolicitationEmailStatus(models.Model):
    solicitation = models.ForeignKey('Solicitation', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('sent', 'Sent'),
        ('failed', 'Failed')
    ], default='pending')
    processing_attempts = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ('solicitation', 'user')
        verbose_name_plural = 'Solicitation Email Statuses'
    
    def __str__(self):
        return f"{self.user.username} - {self.solicitation.cage} - {self.email_status}"
    
## This model link RFQ with multiple solicitations (having the same cage code)
class RFQItem(models.Model):
    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name='items')
    solicitation = models.ForeignKey(Solicitation, on_delete=models.CASCADE, related_name='rfq_items')
    
    def __str__(self):
        return f"Item in {self.rfq.unique_id}: {self.solicitation.nomenclature}"