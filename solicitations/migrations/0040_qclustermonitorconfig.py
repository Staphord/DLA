from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('solicitations', '0039_solicitation_higher_level_quality_indicator'),
    ]

    operations = [
        migrations.CreateModel(
            name='QClusterMonitorConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notification_emails', models.TextField(blank=True, default='', help_text='Comma-separated email addresses for health check alerts')),
                ('check_interval_minutes', models.PositiveSmallIntegerField(default=5, help_text='How often the cron health check should run (informational; update crontab manually)')),
                ('stall_threshold_minutes', models.PositiveSmallIntegerField(default=30, help_text='Minutes since last completed Django-Q task before the cluster is considered stalled')),
                ('is_monitoring_enabled', models.BooleanField(default=False, help_text='Enable automatic health checks and recovery')),
                ('last_alert_sent_at', models.DateTimeField(blank=True, help_text='Last time a failure alert email was sent (debounce repeat alerts)', null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='qcluster_monitor_config_updates', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Django-Q Monitor Configuration',
                'verbose_name_plural': 'Django-Q Monitor Configuration',
            },
        ),
    ]
