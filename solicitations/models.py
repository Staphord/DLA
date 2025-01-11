from django.db import models
from django.conf import settings

from accounts.models import CustomUser

class Solicitation(models.Model):
    cage = models.CharField(max_length=5)
    item_name = models.CharField(max_length=50)
    quantity = models.CharField(max_length=20)
    part_number = models.CharField(max_length=20,default='2')
    NSN = models.CharField(max_length=20,default='1')

    def __str__(self):
        return f"Solicitation-{self.cage} ({self.item_name})"

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

class OEMUser(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    oem = models.ForeignKey(OEM, on_delete=models.CASCADE)
    is_disabled = models.BooleanField(default=False)
    reason = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        unique_together = ('user', 'oem')

    def __str__(self):
        return f"{self.user.username} - {self.oem.name} (Disabled: {self.is_disabled})"

class RFQ(models.Model):
    solicitation = models.ForeignKey(Solicitation, on_delete=models.CASCADE, related_name='rfqs')
    oem = models.ForeignKey(OEM, on_delete=models.CASCADE, related_name='rfqs')
    unique_id = models.CharField(max_length=5, unique=True, editable=False)  # Unique 5-character ID
    sent_at = models.DateField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_rfqs')

    def __str__(self):
        return f"RFQ-{self.unique_id} for {self.solicitation.item_name}"

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

    def save(self, *args, **kwargs):
        # Automatically associate the reply with the RFQ creator
        if not self.rfq_creator:
            self.rfq_creator = self.rfq.created_by
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Reply for RFQ-{self.rfq.unique_id} (Sent by {self.rfq_creator.username})"
    
class MailTemplate(models.Model):
    body = models.TextField(default="I hope this message finds you well. We are currently looking for the following item. Kindly provide your lowest possible price.")
    salutation = models.CharField(max_length=20, default='Dear Mr/Ms')
    heading = models.CharField(max_length=50,default="REQUEST FOR QUOTATION")
    userMail = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

