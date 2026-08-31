"""
Django-Q cluster health check and auto-recovery.

Cron setup and sudoers examples: see QCLUSTER_MONITORING_SETUP.md in the project root.
"""

import logging
import subprocess
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
from django_q.models import Success, Task

from solicitations.models import QClusterMonitorConfig

QCLUSTER_SERVICE = 'django-q-dla-new.service'
PRIMARY_LOG_PATH = Path('/var/log/qcluster_check.log')
FALLBACK_LOG_PATH = Path(settings.BASE_DIR) / 'logs' / 'qcluster_check.log'

logger = logging.getLogger('rfq.qcluster_monitor')


class Command(BaseCommand):
    help = (
        'Check Django-Q cluster health (MySQL + recent task activity) and '
        'restart django-q-dla-new.service when unhealthy.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run checks and log results without restarting or sending email',
        )
        parser.add_argument(
            '--force-alert',
            action='store_true',
            help='Send alert email even if debounce window has not elapsed',
        )

    def handle(self, *args, **options):
        try:
            self._run_check(*args, **options)
        except Exception as exc:
            self._log(f'UNHANDLED ERROR: {exc}')

    def _run_check(self, *args, **options):
        dry_run = options['dry_run']
        force_alert = options['force_alert']
        now = timezone.now()

        try:
            config = QClusterMonitorConfig.get_solo()
        except Exception as exc:
            self._log(f'ERROR: Failed to load QClusterMonitorConfig: {exc}')
            return

        if not config.is_monitoring_enabled:
            self._log('Monitoring disabled; exiting without checks.')
            return

        failures = []
        mysql_ok, mysql_detail = self._check_mysql()
        if not mysql_ok:
            failures.append(f'MySQL connectivity failed: {mysql_detail}')

        stall_ok, stall_detail = self._check_qcluster_activity(config.stall_threshold_minutes)
        if not stall_ok:
            failures.append(f'Django-Q stall detected: {stall_detail}')

        if not failures:
            self._log(
                f'HEARTBEAT OK at {now.isoformat()} - MySQL OK; '
                f'{stall_detail}'
            )
            return

        failure_reason = '; '.join(failures)
        self._log(f'HEALTH CHECK FAILED at {now.isoformat()}: {failure_reason}')

        restart_ok = False
        restart_detail = 'Skipped (dry-run)' if dry_run else 'Not attempted'
        if not dry_run:
            restart_ok, restart_detail = self._restart_qcluster_service()

        self._log(
            f'Restart {"succeeded" if restart_ok else "failed"}: {restart_detail}'
        )

        if not config.get_notification_email_list():
            self._log('No notification emails configured; alert email skipped.')
            return

        debounce_minutes = config.alert_debounce_minutes or 0
        if not dry_run and not self._should_send_alert(config, force_alert, debounce_minutes):
            self._log(
                f'Alert suppressed (debounce {debounce_minutes} min); '
                f'last alert at {config.last_alert_sent_at}'
            )
            return

        if dry_run:
            self._log('Dry-run: alert email not sent.')
            return

        email_ok = self._send_alert_email(
            config=config,
            failure_reason=failure_reason,
            restart_ok=restart_ok,
            restart_detail=restart_detail,
            checked_at=now,
        )
        if email_ok:
            config.last_alert_sent_at = now
            config.save(update_fields=['last_alert_sent_at'])
            self._log('Alert email sent.')
        else:
            self._log('Alert email failed to send.')

    def _check_mysql(self):
        try:
            connection.close_if_unusable_or_obsolete()
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                row = cursor.fetchone()
            if row and row[0] == 1:
                return True, 'SELECT 1 succeeded'
            return False, f'unexpected result: {row}'
        except Exception as exc:
            return False, str(exc)

    def _check_qcluster_activity(self, stall_threshold_minutes):
        try:
            running_count = Task.objects.filter(stopped__isnull=True).count()
            if running_count > 0:
                return True, f'{running_count} task(s) currently running'

            latest = Success.objects.order_by('-stopped').first()
            if not latest or not latest.stopped:
                return False, 'no completed Django-Q tasks found'

            age = timezone.now() - latest.stopped
            threshold = timedelta(minutes=stall_threshold_minutes)
            if age <= threshold:
                minutes_ago = int(age.total_seconds() // 60)
                return True, (
                    f'last completed task {minutes_ago} min ago '
                    f'({latest.name or latest.func})'
                )

            minutes_stale = int(age.total_seconds() // 60)
            return False, (
                f'last completed task was {minutes_stale} min ago '
                f'({latest.name or latest.func}), threshold is {stall_threshold_minutes} min'
            )
        except Exception as exc:
            return False, str(exc)

    def _restart_qcluster_service(self):
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'restart', QCLUSTER_SERVICE],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode == 0:
                return True, f'systemctl restart {QCLUSTER_SERVICE} exited 0'
            detail = (result.stderr or result.stdout or '').strip()
            return False, f'exit code {result.returncode}: {detail or "no output"}'
        except Exception as exc:
            return False, str(exc)

    def _should_send_alert(self, config, force_alert, debounce_minutes):
        if force_alert or debounce_minutes <= 0 or not config.last_alert_sent_at:
            return True
        elapsed = timezone.now() - config.last_alert_sent_at
        return elapsed >= timedelta(minutes=debounce_minutes)

    def _send_alert_email(self, config, failure_reason, restart_ok, restart_detail, checked_at):
        recipients = config.get_notification_email_list()
        if not recipients:
            return False

        local_now = timezone.localtime(checked_at)
        when_str = (
            f'{local_now.strftime("%B")} {local_now.day}, {local_now.year}, '
            f'{local_now.strftime("%I:%M %p").lstrip("0")}'
        )

        last_success_at = None
        try:
            latest = Success.objects.order_by('-stopped').first()
            if latest and latest.stopped:
                last_success_at = timezone.localtime(latest.stopped)
        except Exception:
            last_success_at = None

        if last_success_at:
            down_minutes = max(1, int((local_now - last_success_at).total_seconds() // 60))
            down_for_str = f'{down_minutes} minute{"s" if down_minutes != 1 else ""}'
            window_start = last_success_at.strftime('%I:%M %p').lstrip('0')
            window_end = local_now.strftime('%I:%M %p').lstrip('0')
            window_str = f'{window_start} – {window_end}'
        else:
            down_for_str = 'unknown (no recent completed task found)'
            window_str = when_str

        if restart_ok:
            what_happened_extra = (
                'This has been detected and automatically fixed.'
            )
            what_we_did = (
                'The system automatically restarted itself and is now working normally.'
            )
            subject = 'RFQ Automated Sending - System Notice'
            closing = 'If everything looks normal, no further action is needed.'
        else:
            what_happened_extra = (
                'This has been detected, but the automatic restart did not succeed.'
            )
            what_we_did = (
                'The system attempted an automatic restart, but it did not complete '
                'successfully. Please contact your system administrator.'
            )
            subject = 'RFQ Automated Sending - System Notice (Action Needed)'
            closing = 'Please follow up until automated RFQ sending is confirmed working again.'

        body = f"""RFQ Automated Sending System Notice
========================================

What happened:
The system that sends automated RFQs stopped working properly for
a short period. {what_happened_extra}

When: {when_str}
Down for approximately: {down_for_str}

What we did about it:
{what_we_did}

What you should do:
Please check that no RFQs were missed during this time window
(around {window_str})

{closing}

This is an automated notice from the RFQ System Monitor.
"""

        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=False,
            )
            return True
        except Exception as exc:
            self._log(f'ERROR sending alert email: {exc}')
            return False

    def _log(self, message):
        timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f'[{timestamp}] {message}'
        self.stdout.write(line)
        logger.info(message)
        self._append_log_file(line)

    def _append_log_file(self, line):
        for path in (PRIMARY_LOG_PATH, FALLBACK_LOG_PATH):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('a', encoding='utf-8') as handle:
                    handle.write(line + '\n')
                return
            except OSError:
                continue
