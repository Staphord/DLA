from django import forms
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser

class UserRegistrationForm(UserCreationForm):

    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'phone', 'address','companyName', 'email','cage','fax','website','password1', 'password2']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address'}),
            'cage': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'cage'}),
            'fax': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Fax'}),
            'website': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Website'}),
            'companyName': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company Name'}),
            'password1': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'}),
        }

        def save(self, commit=True):
            user = super().save(commit=False)
            user.user_type = 'client'
            if commit:
                user.save()
            return user