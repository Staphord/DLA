from django import forms
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm
from accounts.models import CustomUser
from solicitations.models import RFQReply, GitHubWorkflow

class UserRegistrationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'phone', 'companyName', 'address', 'email', 
                  'password1', 'password2', 'user_type', 'logo']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'companyName': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'password1': forms.PasswordInput(attrs={'class': 'form-control'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control'}),
            'user_type': forms.Select(attrs={'class': 'form-control'}),
            'logo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

class RFQReplyForm(forms.ModelForm):
    class Meta:
        model = RFQReply
        fields = ['price', 'delivery_mode', 'short_note', 'document']
        widgets = {
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'delivery_mode': forms.Select(attrs={'class': 'form-control'}),
            'short_note': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Add an optional note',
            }),
            'document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

class LogoUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['logo']
        widgets = {
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


class GitHubWorkflowForm(forms.ModelForm):
    class Meta:
        model = GitHubWorkflow
        fields = ["cron_schedule"]
