from django import forms
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm
from accounts.models import CustomUser
from solicitations.models import EmailSettings, GitHubWorkflow, UserOEMCustomization, UserEmailConfig, UserExportConfiguration, ExportFieldDefinition
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import authenticate


class UserRegistrationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'personal_email', 'phone', 'title', 'companyName', 'company_initial', 'address', 'email', 'website', 'cage', 'fax',
                  'password1', 'password2', 'user_type', 'logo']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'companyName': forms.TextInput(attrs={'class': 'form-control'}),
            'company_initial': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'personal_email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'website': forms.TextInput(attrs={'class': 'form-control'}),
            'cage': forms.TextInput(attrs={'class': 'form-control'}),
            'fax': forms.TextInput(attrs={'class': 'form-control'}),
            'password1': forms.PasswordInput(attrs={'class': 'form-control'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control'}),
            'user_type': forms.Select(attrs={'class': 'form-control'}),
            'logo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }


class LogoUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['logo']
        widgets = {
            'logo': forms.FileInput(attrs={'class': 'form-control'}),
        }


class GitHubWorkflowForm(forms.ModelForm):
    class Meta:
        model = GitHubWorkflow
        fields = ["cron_schedule"]


class UserOEMCustomizationForm(forms.ModelForm):
    # Explicitly override the email field to accept multiple emails
    custom_email = forms.CharField(
        max_length=500,
        required=False,
        help_text="Enter multiple emails separated by semicolons (;) or commas (,)"
    )

    class Meta:
        model = UserOEMCustomization
        fields = ['custom_name', 'custom_email', 'custom_phone', 'custom_fax',
                  'custom_city', 'custom_street', 'custom_postal_code', 'custom_poc']
        labels = {
            'custom_name': 'Name',
            'custom_email': 'Email',
            'custom_phone': 'Phone',
            'custom_fax': 'Fax',
            'custom_city': 'City',
            'custom_street': 'Street',
            'custom_postal_code': 'Postal Code',
            'custom_poc': 'Point of Contact'
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
                field.widget.attrs['placeholder'] = 'email1@company.com; email2@company.com'
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
            elif field_name == 'custom_poc':
                field.widget.attrs['placeholder'] = 'Enter poc'

    def clean_custom_email(self):
        """Validate multiple email format"""
        email_string = self.cleaned_data.get('custom_email', '')

        if email_string.strip():
            # Basic validation for multiple emails
            import re

            # Split by semicolon or comma
            separators = [';', ',']
            emails = [email_string.strip()]

            for separator in separators:
                temp_emails = []
                for email in emails:
                    temp_emails.extend(email.split(separator))
                emails = temp_emails

            # Validate each email
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            invalid_emails = []

            for email in emails:
                cleaned_email = email.strip()
                if cleaned_email and not re.match(email_pattern, cleaned_email):
                    invalid_emails.append(cleaned_email)

            if invalid_emails:
                raise forms.ValidationError(
                    f"Invalid email format: {', '.join(invalid_emails)}. "
                    "Please use format: email1@domain.com; email2@domain.com"
                )

        return email_string


class EmailSettingsForm(forms.ModelForm):
    class Meta:
        model = EmailSettings
        fields = [
            'auto_send',
            'send_day',
            'send_time',
            'last_processed',
            'send_time_1', 'enable_time_1',
            'send_time_2', 'enable_time_2',
            'send_time_3', 'enable_time_3',
            'send_scope'
        ]
        widgets = {
            'auto_send': forms.HiddenInput(),
            'send_day': forms.Select(attrs={
                'class': 'form-select'
            }),
            'send_time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time'
            }),
            'last_processed': forms.HiddenInput(),

            # New time interval widgets
            'send_time_1': forms.TimeInput(attrs={
                'class': 'form-control time-input',
                'type': 'time'
            }),
            'enable_time_1': forms.CheckboxInput(attrs={
                'class': 'form-check-input time-enable-checkbox'
            }),
            'send_time_2': forms.TimeInput(attrs={
                'class': 'form-control time-input',
                'type': 'time'
            }),
            'enable_time_2': forms.CheckboxInput(attrs={
                'class': 'form-check-input time-enable-checkbox'
            }),
            'send_time_3': forms.TimeInput(attrs={
                'class': 'form-control time-input',
                'type': 'time'
            }),
            'enable_time_3': forms.CheckboxInput(attrs={
                'class': 'form-check-input time-enable-checkbox'
            }),

            # Send scope widget
            'send_scope': forms.Select(attrs={
                'class': 'form-select'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add helpful text to the fields
        self.fields['send_day'].help_text = "Select 'Every day' to send emails daily, or choose a specific day of the week."
        self.fields['send_scope'].help_text = "Choose whether to send all pending solicitations or only today's solicitations."

        # Make fields not required
        if 'last_processed' in self.fields:
            self.fields['last_processed'].required = False

        if 'send_time' in self.fields:
            self.fields['send_time'].required = False

        # Make time 2 and time 3 optional
        if 'send_time_2' in self.fields:
            self.fields['send_time_2'].required = False

        if 'send_time_3' in self.fields:
            self.fields['send_time_3'].required = False

        if 'enable_time_2' in self.fields:
            self.fields['enable_time_2'].required = False

        if 'enable_time_3' in self.fields:
            self.fields['enable_time_3'].required = False


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'title', 'email', 'personal_email', 'phone', 'address',
                  'companyName', 'company_initial', 'cage', 'fax', 'website']

    def __init__(self, *args, **kwargs):
        super(UserUpdateForm, self).__init__(*args, **kwargs)
        # Add Bootstrap classes to form fields
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'


class EmailConfigForm(forms.ModelForm):
    class Meta:
        model = UserEmailConfig
        fields = [
            'email_host',
            'email_port',
            'email_use_tls',
            'email_host_user',
            'email_host_password',
            'default_from_email',
            'email_interval_seconds',
            'save_to_sent_folder',    # NEW FIELD
            'custom_imap_host',       # NEW FIELD
            'custom_imap_port',       # NEW FIELD
            'custom_sent_folder',     # NEW FIELD
        ]
        widgets = {
            'email_host': forms.TextInput(attrs={
                'placeholder': 'smtp.gmail.com or smtp-mail.outlook.com'
            }),
            'email_port': forms.NumberInput(attrs={
                'min': 1,
                'max': 65535,
                'value': 587
            }),
            'email_host_user': forms.EmailInput(attrs={
                'placeholder': 'your-email@gmail.com'
            }),
            'email_host_password': forms.TextInput(attrs={
                'type': 'password',
                'placeholder': 'Your email password or app password'
            }),
            'default_from_email': forms.EmailInput(attrs={
                'placeholder': 'your-email@gmail.com'
            }),
            'email_interval_seconds': forms.NumberInput(attrs={
                'min': 3,          # Minimum 3 seconds
                'max': 240,        # Maximum 240 seconds (4 minutes)
                'value': 10,       # Default 10 seconds
                'step': 1
            }),
            'custom_imap_host': forms.TextInput(attrs={
                'placeholder': 'imap.gmail.com (auto-detected if blank)'
            }),
            'custom_imap_port': forms.NumberInput(attrs={
                'min': 1,
                'max': 65535,
                'value': 993
            }),
            'custom_sent_folder': forms.TextInput(attrs={
                'placeholder': 'Sent Items (auto-detected if blank)'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes to form fields
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'form-control'})

        # Special handling for checkboxes
        self.fields['email_use_tls'].widget.attrs.update(
            {'class': 'form-check-input'})
        self.fields['save_to_sent_folder'].widget.attrs.update(
            {'class': 'form-check-input'})

        # Make port readonly since 587 is standard for most providers
        self.fields['email_port'].widget.attrs['readonly'] = True
        self.fields['email_port'].widget.attrs['class'] += ' readonly-field'

        # Make TLS disabled since it should always be True for security
        self.fields['email_use_tls'].widget.attrs['disabled'] = True
        self.fields['email_use_tls'].widget.attrs['checked'] = True

        # Add helpful labels
        self.fields['email_host'].label = 'SMTP Host'
        self.fields['email_port'].label = 'SMTP Port'
        self.fields['email_host_user'].label = 'Email Address (Username)'
        self.fields['email_host_password'].label = 'Email Password'
        self.fields['default_from_email'].label = 'Your Email Address'
        self.fields['email_use_tls'].label = 'Use TLS'
        self.fields['email_interval_seconds'].label = 'Email Sending Interval'
        self.fields['save_to_sent_folder'].label = 'Save to Sent Folder'
        self.fields['custom_imap_host'].label = 'Custom IMAP Host'
        self.fields['custom_imap_port'].label = 'Custom IMAP Port'
        self.fields['custom_sent_folder'].label = 'Custom Sent Folder Name'

        # Add help text
        self.fields[
            'email_interval_seconds'].help_text = 'Time delay between sending emails to different recipients (3-240 seconds)'
        self.fields['save_to_sent_folder'].help_text = 'Automatically save sent RFQ emails to your sent folder'
        self.fields['custom_imap_host'].help_text = 'Leave blank for auto-detection based on your SMTP host'
        self.fields['custom_sent_folder'].help_text = 'Leave blank for auto-detection based on your email provider'

        # Ensure password field preserves its value
        if self.instance and self.instance.pk and self.instance.email_host_password:
            self.fields['email_host_password'].widget.attrs['value'] = self.instance.email_host_password

    def clean_email_interval_seconds(self):
        interval = self.cleaned_data.get('email_interval_seconds')
        if interval is not None:
            if interval < 3:
                raise forms.ValidationError("Minimum interval is 3 seconds")
            if interval > 240:
                raise forms.ValidationError(
                    "Maximum interval is 4 minutes (240 seconds)")
        return interval

    def clean_email_host_password(self):
        password = self.cleaned_data.get('email_host_password')

        # Only validate if form is being submitted (has POST data)
        if self.data and not password:
            raise forms.ValidationError("Email host password is required")

        return password

    def clean_default_from_email(self):
        email = self.cleaned_data.get('default_from_email')

        # Only validate if form is being submitted (has POST data)
        if self.data and not email:
            raise forms.ValidationError("Default from email is required")

        return email

    def clean(self):
        cleaned_data = super().clean()
        default_from_email = cleaned_data.get('default_from_email')

        # Auto-set email_host_user to be the same as default_from_email
        if default_from_email:
            cleaned_data['email_host_user'] = default_from_email

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Ensure email_host_user is always the same as default_from_email
        instance.email_host_user = instance.default_from_email

        if commit:
            instance.save()
        return instance


class CustomPasswordChangeForm(forms.Form):
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your current password'
        }),
        label='Current Password'
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter new password'
        }),
        label='New Password'
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password'
        }),
        label='Confirm New Password'
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old_password = self.cleaned_data.get('old_password')
        if not self.user.check_password(old_password):
            raise forms.ValidationError('Your current password is incorrect.')
        return old_password

    def clean(self):
        cleaned_data = super().clean()
        new_password1 = cleaned_data.get('new_password1')
        new_password2 = cleaned_data.get('new_password2')

        if new_password1 and new_password2:
            if new_password1 != new_password2:
                raise forms.ValidationError(
                    'The two password fields must match.')

        # Add password validation
        if new_password1:
            # Check minimum length
            if len(new_password1) < 8:
                raise forms.ValidationError(
                    'Password must be at least 8 characters long.')

            # Check if password is too common or similar to user info
            if new_password1.lower() in [self.user.username.lower(), self.user.email.lower()]:
                raise forms.ValidationError(
                    'Password cannot be similar to your username or email.')

        return cleaned_data

    def save(self):
        password = self.cleaned_data['new_password1']
        self.user.set_password(password)
        self.user.save()
        return self.user


class UserExportConfigurationForm(forms.ModelForm):
    """
    Form for configuring individual export field mappings.
    Used in the user profile to configure how solicitation data maps to export fields.
    """
    class Meta:
        model = UserExportConfiguration
        fields = ['is_enabled', 'source_field', 'custom_value']
        widgets = {
            'is_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'source_field': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'e.g., cage, NSN, quantity'
            }),
            'custom_value': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Static value (overrides source field)'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make fields optional
        self.fields['source_field'].required = False
        self.fields['custom_value'].required = False
