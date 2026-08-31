from django import forms
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth import get_user_model
from django.core.mail import send_mail, get_connection
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site 

User = get_user_model()

class UserRegistrationForm(UserCreationForm):

    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'phone','personal_email', 'address','companyName','title','company_initial', 'email','cage','fax','website','password1', 'password2']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Title'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address'}),
            'cage': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'cage'}),
            'fax': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Fax'}),
            'website': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Website'}),
            'companyName': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company Name'}),
            'company_initial': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company Initial'}),
            'personal_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Personal Email'}),
            'password1': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'}),
        }

        def save(self, commit=True):
            user = super().save(commit=False)
            user.user_type = 'client'
            if commit:
                user.save()
            return user

class CustomPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="Personal Email",
        max_length=254,
        widget=forms.EmailInput(attrs={
            'autocomplete': 'email',
            'placeholder': 'Enter your personal email address'
        })
    )

    def get_users(self, email):
        """
        Override to look up users by personal_email instead of email field
        """
        active_users = User._default_manager.filter(
            personal_email__iexact=email,
            is_active=True
        )
        return (
            u for u in active_users
            if u.has_usable_password() and
            self._verify_user_email(u, email)
        )

    def _verify_user_email(self, user, email):
        """
        Verify that the user's personal_email matches the provided email
        """
        return user.personal_email and user.personal_email.lower() == email.lower()

    def clean_email(self):
        """
        Validate that a user with this personal email exists
        """
        email = self.cleaned_data['email']
        if not User.objects.filter(personal_email__iexact=email, is_active=True).exists():
            raise forms.ValidationError("No active user found with this personal email address.")
        return email

    def save(self, domain_override=None,
             subject_template_name='registration/password_reset_subject.txt',
             email_template_name='registration/password_reset_email.html',
             use_https=False, token_generator=default_token_generator,
             from_email=None, request=None, html_email_template_name=None,
             extra_email_context=None):
        """
        Generate a one-use only link for resetting password and send it to the user.
        """
        email = self.cleaned_data["email"]
        if not domain_override:
            current_site = get_current_site(request)
            site_name = current_site.name
            domain = current_site.domain
        else:
            site_name = domain = domain_override
        
        # Use personal_email instead of the default email field
        email_field_name = 'personal_email'
        for user in self.get_users(email):
            user_email = getattr(user, email_field_name)
            context = {
                'email': user_email,
                'domain': domain,
                'site_name': site_name,
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'user': user,
                'token': token_generator.make_token(user),
                'protocol': 'https' if use_https else 'http',
                **(extra_email_context or {}),
            }
            
            # Create custom email connection
            connection = get_connection(
                backend='django.core.mail.backends.smtp.EmailBackend',
                host='gilgaltech.com',
                port=587,
                username='info@gilgaltech.com',
                password='info@0213',
                use_tls=True,
            )
            
            # Render email content
            subject = render_to_string(subject_template_name, context)
            subject = ''.join(subject.splitlines())  # Remove newlines
            body = render_to_string(email_template_name, context)
            
            # Send email with custom connection
            send_mail(
                subject,
                body,
                from_email or 'info@gilgaltech.com',
                [user_email],
                connection=connection,
                fail_silently=False,
            )