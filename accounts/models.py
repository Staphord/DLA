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
    email = models.EmailField()
    address = models.CharField(max_length=255)  
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='client')
    logo = models.ImageField(upload_to='logos/', blank=True, null=True)

    def __str__(self):
        return self.username
