from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('solicitations', '0035_bidassessment_bid_reference'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BidReferenceTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('components', models.JSONField(default=list, help_text='Ordered list of bid reference components')),
                ('separator', models.CharField(choices=[('-', 'Hyphen (-)'), ('_', 'Underscore (_)'), ('', 'No separator'), ('.', 'Period (.)'), ('/', 'Forward slash (/)')], default='-', help_text='Character(s) to separate components', max_length=5)),
                ('date_format', models.CharField(choices=[('MMDDYY', 'MMDDYY (010125)'), ('DDMMYY', 'DDMMYY (010125)'), ('YYMMDD', 'YYMMDD (250101)'), ('YYYY-MM-DD', 'YYYY-MM-DD (2025-01-01)'), ('YYYYMMDD', 'YYYYMMDD (20250101)'), ('MMM-YY', 'MMM-YY (Jan-25)'), ('MMMM-YYYY', 'MMMM-YYYY (January-2025)'), ('MM/DD', 'MM/DD (01/01)')], default='MMDDYY', help_text='Format for date component', max_length=15)),
                ('custom_text', models.CharField(blank=True, help_text="Custom text to include if 'custom_text' component is selected", max_length=50)),
                ('sequence_padding', models.IntegerField(default=5, help_text='Number of digits for sequence (e.g., 5 = 00001)')),
                ('sequence_reset_period', models.CharField(choices=[('never', 'Never reset'), ('yearly', 'Reset every year'), ('monthly', 'Reset every month'), ('daily', 'Reset every day')], default='never', help_text='When to reset sequence counter', max_length=10)),
                ('last_sequence_number', models.IntegerField(default=0, help_text='Last used bid reference sequence number')),
                ('last_sequence_reset_date', models.DateField(auto_now_add=True, help_text='Date when sequence was last reset')),
                ('preview', models.CharField(blank=True, help_text='Preview of what the bid reference will look like', max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='bid_reference_template', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Bid Reference Template',
                'verbose_name_plural': 'Bid Reference Templates',
            },
        ),
    ]
