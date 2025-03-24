from django.db import models
from django.contrib.auth.models import AbstractUser

# Create your models here.
# Custom User model for authentication
class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
        ('client', 'Client'),
        ('admin', 'Admin')
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

    def __str__(self):
        return self.username
    
class VerificationToken(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)  # Use CustomUser
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
