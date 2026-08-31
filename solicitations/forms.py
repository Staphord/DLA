from django import forms
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm
from accounts.models import CustomUser
from solicitations.models import EmailSettings, RFQIDTemplate, BidReferenceTemplate, RfqAutoFetchSettings, GitHubWorkflow, UserOEMCustomization, UserEmailConfig, UserExportConfiguration, ExportFieldDefinition, RfqReply, Solicitation, ScrapingSchedule, EmailTemplateConfig, QClusterMonitorConfig
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


class ScrapingScheduleForm(forms.ModelForm):
    scrape_time = forms.TimeField(
        required=True,
        help_text="Time to run scraping (24-hour format)",
        widget=forms.TimeInput(attrs={
            'class': 'form-control',
            'type': 'time'
        })
    )
    second_scrape_time = forms.TimeField(
        required=False,
        help_text="Time to run second scraping phase (optional, 24-hour format)",
        widget=forms.TimeInput(attrs={
            'class': 'form-control',
            'type': 'time'
        })
    )

    class Meta:
        model = ScrapingSchedule
        fields = ['enabled', 'scrape_day', 'scrape_time', 'second_scrape_time']
        widgets = {
            'enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'scrape_day': forms.Select(attrs={'class': 'form-select'}),
        }


class QClusterMonitorConfigForm(forms.ModelForm):
    notification_emails = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'admin@example.com, ops@example.com',
        }),
        help_text='Enter one or more email addresses, separated by commas.',
    )

    class Meta:
        model = QClusterMonitorConfig
        fields = [
            'notification_emails',
            'stall_threshold_minutes',
            'alert_debounce_minutes',
            'is_monitoring_enabled',
        ]
        widgets = {
            'stall_threshold_minutes': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
            }),
            'alert_debounce_minutes': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
            }),
            'is_monitoring_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
        }

    def clean_notification_emails(self):
        import re

        email_string = self.cleaned_data.get('notification_emails', '')
        if not email_string.strip():
            return ''

        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        parsed = [
            email.strip()
            for email in email_string.split(',')
            if email.strip()
        ]
        invalid = [e for e in parsed if not re.match(email_pattern, e)]
        if invalid:
            raise forms.ValidationError(
                f"Invalid email format: {', '.join(invalid)}"
            )
        return ', '.join(parsed)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('is_monitoring_enabled') and not cleaned_data.get('notification_emails', '').strip():
            self.add_error(
                'notification_emails',
                'At least one notification email is required when monitoring is enabled.',
            )
        return cleaned_data

    def clean_stall_threshold_minutes(self):
        value = self.cleaned_data.get('stall_threshold_minutes')
        if value is not None and value < 1:
            raise forms.ValidationError('Stall threshold must be at least 1 minute.')
        return value

    def clean_alert_debounce_minutes(self):
        value = self.cleaned_data.get('alert_debounce_minutes')
        if value is not None and value < 0:
            raise forms.ValidationError('Alert debounce cannot be negative.')
        return value


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


class RfqAutoFetchSettingsForm(forms.ModelForm):
    class Meta:
        model = RfqAutoFetchSettings
        fields = ['enabled', 'day', 'fetch_time']
        widgets = {
            'enabled': forms.HiddenInput(),
            'day': forms.Select(attrs={
                'class': 'form-select',
            }),
            'fetch_time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time',
            }),
        }


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'title', 'email', 'personal_email', 'phone', 'address',
                  'companyName', 'company_initial', 'cage', 'fax', 'website', 'added_days']

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


class RfqReplyEditForm(forms.ModelForm):
    """
    Form for editing RFQ reply data.
    Allows users to update pricing, quantities, and other extracted information.
    """
    class Meta:
        model = RfqReply
        fields = [
            'rfq_unique_id',
            'solicitation_number',
            'nsn',
            'part_number',
            'nomenclature',
            'quantity',
            'unit',
            'unit_price',
            'total_price',
            # Additional costs (other_oem_charges is auto-computed from these)
            'tax',
            'packaging_cost',
            'handling_fee',
            'insurance_cost',
            'customs_duty',
            'setup_cost',
            'minimum_order_charge',
            'rush_delivery_fee',
            'environmental_fee',
            'certification_cost',
            'documentation_fee',
            'oem_name',
            'replied_email',
            'notes',
        ]
        widgets = {
            'rfq_unique_id': forms.TextInput(attrs={'class': 'form-control'}),
            'solicitation_number': forms.TextInput(attrs={'class': 'form-control'}),
            'nsn': forms.TextInput(attrs={'class': 'form-control'}),
            'part_number': forms.TextInput(attrs={'class': 'form-control'}),
            'nomenclature': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'quantity': forms.TextInput(attrs={'class': 'form-control'}),
            'unit': forms.TextInput(attrs={'class': 'form-control'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'total_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'tax': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'packaging_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'handling_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'insurance_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'customs_duty': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'setup_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'minimum_order_charge': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'rush_delivery_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'environmental_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'certification_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'documentation_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'oem_name': forms.TextInput(attrs={'class': 'form-control'}),
            'replied_email': forms.EmailInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'rfq_unique_id': 'RFQ ID',
            'solicitation_number': 'Solicitation Number',
            'nsn': 'NSN',
            'part_number': 'Part Number',
            'nomenclature': 'Nomenclature',
            'quantity': 'Quantity',
            'unit': 'Unit',
            'unit_price': 'Unit Price',
            'total_price': 'Total Price',
            'tax': 'Tax (VAT/GST/Sales Tax)',
            'packaging_cost': 'Packaging Cost',
            'handling_fee': 'Handling Fee',
            'insurance_cost': 'Insurance Cost',
            'customs_duty': 'Customs/Duty',
            'setup_cost': 'Setup/Tooling Cost',
            'minimum_order_charge': 'Minimum Order Charge',
            'rush_delivery_fee': 'Rush Delivery Fee',
            'environmental_fee': 'Environmental/Disposal Fee',
            'certification_cost': 'Certification/Testing Cost',
            'documentation_fee': 'Documentation Fee',
            'oem_name': 'OEM Name',
            'replied_email': 'Replied Email',
            'notes': 'Notes',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make all fields optional
        for field_name, field in self.fields.items():
            field.required = False


class SolicitationEditForm(forms.ModelForm):
    """
    Form for editing Solicitation data when working from a replied RFQ.
    Allows correcting scraped header information that will affect all linked RFQs/replies.
    """

    class Meta:
        model = Solicitation
        fields = [
            'cage',
            'nomenclature',
            'solicitation',
            'status',
            'part_number',
            'pr',
            'unit',
            'quantity',
            'NSN',
            'issued_date',
            'return_by_date',
            'organization_name',
            'street_name',
            'city',
            'fax',
            'phone',
            'postal_code',
            'email',
            'inspection_point',
            'acceptance_point',
            'deliver_fob',
            'deliver_days',
            'buyer_info',
            'solicitation_line_number',
            'purchase_request_number',
            'is_set_aside',
        ]
        widgets = {
            'cage': forms.TextInput(attrs={'class': 'form-control'}),
            'nomenclature': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'solicitation': forms.TextInput(attrs={'class': 'form-control'}),
            'status': forms.TextInput(attrs={'class': 'form-control'}),
            'part_number': forms.TextInput(attrs={'class': 'form-control'}),
            'pr': forms.TextInput(attrs={'class': 'form-control'}),
            'unit': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.TextInput(attrs={'class': 'form-control'}),
            'NSN': forms.TextInput(attrs={'class': 'form-control'}),
            'issued_date': forms.TextInput(attrs={'class': 'form-control'}),
            'return_by_date': forms.TextInput(attrs={'class': 'form-control'}),
            'organization_name': forms.TextInput(attrs={'class': 'form-control'}),
            'street_name': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'fax': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'inspection_point': forms.TextInput(attrs={'class': 'form-control'}),
            'acceptance_point': forms.TextInput(attrs={'class': 'form-control'}),
            'deliver_fob': forms.TextInput(attrs={'class': 'form-control'}),
            'deliver_days': forms.TextInput(attrs={'class': 'form-control'}),
            'buyer_info': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'solicitation_line_number': forms.TextInput(attrs={'class': 'form-control'}),
            'purchase_request_number': forms.TextInput(attrs={'class': 'form-control'}),
            'is_set_aside': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make all fields optional so user can adjust only what they need
        for field_name, field in self.fields.items():
            field.required = False


class EmailTemplateConfigForm(forms.ModelForm):
    """Form for configuring email template styling and field visibility"""

    # Offer a safe set of common email-friendly font stacks
    FONT_FAMILY_CHOICES = [
        # Sans-serif families
        ('Arial, sans-serif', 'Arial'),
        ('Helvetica, Arial, sans-serif', 'Helvetica / Arial'),
        ('"Segoe UI", Tahoma, Geneva, Verdana, sans-serif', 'Segoe UI'),
        ('Verdana, Geneva, sans-serif', 'Verdana'),
        ('Tahoma, Geneva, sans-serif', 'Tahoma'),
        ('"Trebuchet MS", Helvetica, sans-serif', 'Trebuchet MS'),
        ('"Lucida Sans Unicode", "Lucida Grande", sans-serif', 'Lucida Sans'),
        ('"Gill Sans", "Gill Sans MT", Calibri, sans-serif', 'Gill Sans / Calibri'),
        ('"Calibri", "Segoe UI", sans-serif', 'Calibri'),
        # Geometric sans; common on Windows; Trebuchet/Arial fallbacks for Mac/Linux and email clients
        ('"Century Gothic", CenturyGothic, "Trebuchet MS", Arial, sans-serif', 'Century Gothic'),

        # Serif families
        ('Georgia, "Times New Roman", serif', 'Georgia'),
        ('"Times New Roman", Times, serif', 'Times New Roman'),
        ('"Palatino Linotype", "Book Antiqua", Palatino, serif', 'Palatino'),
        ('"Garamond", "Times New Roman", serif', 'Garamond'),

        # Monospace
        ('"Courier New", Courier, monospace', 'Courier New (monospace)'),
        ('Consolas, "Liberation Mono", Menlo, Courier, monospace', 'Consolas (monospace)'),
    ]

    # Explicit field so ModelForm uses this as a <select>
    font_family = forms.ChoiceField(
        choices=FONT_FAMILY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control form-select'}),
        required=True,
        label="Font family",
    )

    class Meta:
        model = EmailTemplateConfig
        fields = [
            # Layout Style
            'layout_style',
            # Colors
            'primary_text_color', 'secondary_text_color', 'background_color',
            'border_color', 'link_color', 'header_bg_color', 'header_text_color', 'banner_bg_color',
            # Fonts
            'font_family', 'font_size', 'font_weight_normal', 'font_weight_bold',
            # Spacing
            'padding', 'margin', 'table_cell_padding', 'table_cell_spacing',
            # Table Styling
            'table_border_width', 'table_border_style', 'table_width',
            # Field Visibility
            'show_date', 'show_our_ref', 'show_to_company', 'show_cage_code',
            'show_phone', 'show_fax', 'show_oem_email', 'show_items_table',
            'show_items_col_index', 'show_items_col_nsn', 'show_items_col_nomen', 'show_items_col_part_no',
            'show_items_col_solicitation_no', 'show_items_col_qty_unit', 'show_items_col_unit_price', 'show_items_col_total_price',
            'show_technical_drawing', 'show_moq', 'show_quote_valid_days',
            'show_inspection_point', 'show_shipping_cost', 'show_terms',
            'show_shipping_dimensions', 'show_delivery_days', 'show_country_of_origin',
            'show_iso_certification', 'show_quoted_by', 'show_quote_date',
            'show_return_by_date_note', 'show_signature_section', 'show_logo',
            'logo_width',
            'show_resale_notice',
        ]
        widgets = {
            # Layout Style
            'layout_style': forms.Select(attrs={'class': 'form-control form-select', 'onchange': 'updatePreview()'}),
            # Color inputs with type="color"
            'primary_text_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'secondary_text_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'background_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'border_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'link_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'header_bg_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'header_text_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'banner_bg_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            # Font size & weights stay as free text
            'font_size': forms.TextInput(attrs={'class': 'form-control'}),
            'font_weight_normal': forms.TextInput(attrs={'class': 'form-control'}),
            'font_weight_bold': forms.TextInput(attrs={'class': 'form-control'}),
            'padding': forms.TextInput(attrs={'class': 'form-control'}),
            'margin': forms.TextInput(attrs={'class': 'form-control'}),
            'table_cell_padding': forms.TextInput(attrs={'class': 'form-control'}),
            'table_cell_spacing': forms.TextInput(attrs={'class': 'form-control'}),
            'table_border_width': forms.TextInput(attrs={'class': 'form-control'}),
            'table_border_style': forms.Select(attrs={'class': 'form-control'}, choices=[
                ('solid', 'Solid'),
                ('dashed', 'Dashed'),
                ('dotted', 'Dotted'),
                ('double', 'Double'),
                ('none', 'None'),
            ]),
            'table_width': forms.TextInput(attrs={'class': 'form-control'}),
            # Checkboxes for visibility
            'show_date': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_our_ref': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_to_company': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_cage_code': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_phone': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_fax': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_oem_email': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_items_table': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_items_col_index': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_items_col_nsn': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_items_col_nomen': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_items_col_part_no': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_items_col_solicitation_no': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_items_col_qty_unit': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_items_col_unit_price': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_items_col_total_price': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_technical_drawing': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_moq': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_quote_valid_days': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_inspection_point': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_shipping_cost': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_terms': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_shipping_dimensions': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_delivery_days': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_country_of_origin': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_iso_certification': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_quoted_by': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_quote_date': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_return_by_date_note': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_signature_section': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_logo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'logo_width': forms.NumberInput(attrs={'class': 'form-control', 'min': 40, 'max': 400, 'step': 10}),
            'show_resale_notice': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make all fields optional
        for field_name, field in self.fields.items():
            field.required = False
            
class RFQIDTemplateForm(forms.ModelForm):
    """
    Form for configuring RFQ ID template.
    Allows drag-and-drop reordering of components.
    """
    
    class Meta:
        model = RFQIDTemplate
        fields = [
            'components',
            'separator',
            'date_format',
            'custom_text',
            'sequence_padding',
            'sequence_reset_period',
        ]
        widgets = {
            'components': forms.HiddenInput(),  # JSON will be set via JavaScript
            'separator': forms.Select(attrs={'class': 'form-select'}),
            'date_format': forms.Select(attrs={'class': 'form-select'}),
            'custom_text': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., PRO, VER, etc.'
            }),
            'sequence_padding': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 3,
                'max': 10,
                'help_text': 'Number of digits (3-10)'
            }),
            'sequence_reset_period': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Components are submitted via `components_json` and copied in the view.
        # Keep model field non-required here to avoid "components is required"
        # before custom JSON handling runs.
        self.fields['components'].required = False
        self.fields['separator'].required = False
        
        # Make components field work with JSON
        if self.instance and self.instance.pk:
            self.fields['components'].initial = self.instance.components
        else:
            self.fields['components'].initial = RFQIDTemplate.get_default_template(None)['components']
    
    def clean_sequence_padding(self):
        padding = self.cleaned_data.get('sequence_padding')
        if padding and (padding < 3 or padding > 10):
            raise forms.ValidationError("Sequence padding must be between 3 and 10 digits")
        return padding


class BidReferenceTemplateForm(forms.ModelForm):
    """Form for configuring BID REF. format."""

    class Meta:
        model = BidReferenceTemplate
        fields = [
            'components',
            'separator',
            'date_format',
            'custom_text',
            'sequence_padding',
            'sequence_reset_period',
        ]
        widgets = {
            'components': forms.HiddenInput(),
            'separator': forms.Select(attrs={'class': 'form-select'}),
            'date_format': forms.Select(attrs={'class': 'form-select'}),
            'custom_text': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., BID, QUOTE, REF'
            }),
            'sequence_padding': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 3,
                'max': 10,
            }),
            'sequence_reset_period': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['components'].required = False
        self.fields['separator'].required = False
        if self.instance and self.instance.pk:
            self.fields['components'].initial = self.instance.components
        else:
            self.fields['components'].initial = BidReferenceTemplate.get_default_template()['components']

    def clean_sequence_padding(self):
        padding = self.cleaned_data.get('sequence_padding')
        if padding and (padding < 3 or padding > 10):
            raise forms.ValidationError("Sequence padding must be between 3 and 10 digits")
        return padding
