from django.core.management.base import BaseCommand
from django_q.models import Schedule, Task
from solicitations.models import EmailSettings
from django.utils import timezone
from datetime import timedelta

class Command(BaseCommand):
    help = 'Verify system is in manual-only mode'

    def handle(self, *args, **options):
        self.stdout.write("=== MANUAL-ONLY MODE VERIFICATION ===\n")
        
        # Check 1: Auto-send users
        auto_users = EmailSettings.objects.filter(auto_send=True)
        if auto_users.exists():
            self.stdout.write(self.style.ERROR(f"Found {auto_users.count()} users with auto-send enabled:"))
            for setting in auto_users:
                self.stdout.write(f"   - {setting.user.username}")
        else:
            self.stdout.write(self.style.SUCCESS("No users have auto-send enabled"))
        
        # Check 2: Scheduled tasks
        schedules = Schedule.objects.all()
        if schedules.exists():
            self.stdout.write(self.style.ERROR(f"Found {schedules.count()} scheduled tasks:"))
            for schedule in schedules:
                self.stdout.write(f"   - {schedule.name}: {schedule.func}")
        else:
            self.stdout.write(self.style.SUCCESS("No scheduled tasks exist"))
        
        # Check 3: Running automated tasks
        auto_tasks = Task.objects.filter(
            func='solicitations.tasks.process_user_solicitations',
            stopped__isnull=True
        )
        if auto_tasks.exists():
            self.stdout.write(self.style.ERROR(f"Found {auto_tasks.count()} running automated tasks"))
        else:
            self.stdout.write(self.style.SUCCESS("No automated tasks running"))
        
        # Check 4: Recent automated activity
        recent_auto = Task.objects.filter(
            func='solicitations.tasks.process_user_solicitations',
            started__gte=timezone.now() - timedelta(hours=1)
        )
        if recent_auto.exists():
            self.stdout.write(self.style.WARNING(f"Found {recent_auto.count()} automated tasks in last hour"))
        else:
            self.stdout.write(self.style.SUCCESS("No recent automated activity"))
        
        # Check 5: Manual tasks (should be allowed)
        manual_tasks = Task.objects.filter(
            func='solicitations.tasks.process_manual_rfq_batch',
            stopped__isnull=True
        )
        self.stdout.write(f"Currently {manual_tasks.count()} manual tasks running (this is OK)")
        
        # Summary
        issues = 0
        if auto_users.exists():
            issues += 1
        if schedules.exists():
            issues += 1
        if auto_tasks.exists():
            issues += 1
            
        if issues == 0:
            self.stdout.write(self.style.SUCCESS("\n SYSTEM IS IN MANUAL-ONLY MODE"))
            self.stdout.write("Only manual RFQ processing is enabled")
        else:
            self.stdout.write(self.style.ERROR(f"\nSYSTEM NOT FULLY MANUAL ({issues} issues found)"))
            self.stdout.write("Run the disable script to fix remaining issues")