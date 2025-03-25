from django import forms
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm
from accounts.models import CustomUser
from solicitations.models import EmailSettings, RFQItemReply, RFQReply, GitHubWorkflow,UserOEMCustomization

class UserRegistrationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'phone', 'companyName', 'address', 'email', 'website','cage','fax',
                  'password1', 'password2', 'user_type', 'logo']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'companyName': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'website': forms.TextInput(attrs={'class': 'form-control'}),
            'cage': forms.TextInput(attrs={'class': 'form-control'}),
            'fax': forms.TextInput(attrs={'class': 'form-control'}),
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

class UserOEMCustomizationForm(forms.ModelForm):
    class Meta:
        model = UserOEMCustomization
        fields = ['custom_name', 'custom_email', 'custom_phone', 'custom_fax', 
                  'custom_city', 'custom_street', 'custom_postal_code']
        labels = {
            'custom_name': 'Name',
            'custom_email': 'Email',
            'custom_phone': 'Phone',
            'custom_fax': 'Fax',
            'custom_city': 'City',
            'custom_street': 'Street',
            'custom_postal_code': 'Postal Code',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add Bootstrap form-control class to all form fields
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'
            # Make all fields optional
            field.required = False
            
            # Add placeholders
            if field_name == 'custom_name':
                field.widget.attrs['placeholder'] = 'Enter custom name'
            elif field_name == 'custom_email':
                field.widget.attrs['placeholder'] = 'Enter custom email'
            elif field_name == 'custom_phone':
                field.widget.attrs['placeholder'] = 'Enter custom phone number'
            elif field_name == 'custom_fax':
                field.widget.attrs['placeholder'] = 'Enter custom fax number'
            elif field_name == 'custom_city':
                field.widget.attrs['placeholder'] = 'Enter custom city'
            elif field_name == 'custom_street':
                field.widget.attrs['placeholder'] = 'Enter custom street'
            elif field_name == 'custom_postal_code':
                field.widget.attrs['placeholder'] = 'Enter custom postal code'

class EmailSettingsForm(forms.ModelForm):
    class Meta:
        model = EmailSettings
        fields = ['auto_send', 'send_day', 'send_time']
        widgets = {
            'auto_send': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'role': 'switch'
            }),
            'send_day': forms.Select(attrs={
                'class': 'form-select'
            }),
            'send_time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time'
            }),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add helpful text to the fields
        self.fields['send_day'].help_text = "Select 'Every day' to send emails daily, or choose a specific day of the week."

class RFQItemReplyForm(forms.ModelForm):
    class Meta:
        model = RFQItemReply
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