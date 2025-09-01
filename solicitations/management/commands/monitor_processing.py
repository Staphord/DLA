from django.core.management.base import BaseCommand
from solicitations.tasks import get_all_user_locks, get_user_processing_status
from django_q.models import Task, OrmQ
from solicitations.models import SolicitationEmailStatus
from django.contrib.auth import get_user_model
import time
from datetime import datetime

class Command(BaseCommand):
    help = 'Monitor user processing in real-time'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=30,
            help='Refresh interval in seconds (default: 30)',
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run once and exit (no continuous monitoring)',
        )
    
    def handle(self, *args, **options):
        interval = options['interval']
        run_once = options['once']
        
        self.stdout.write(self.style.SUCCESS("Starting processing monitor..."))
        
        if not run_once:
            self.stdout.write(f"Refreshing every {interval} seconds. Press Ctrl+C to stop.")
        
        try:
            while True:
                self.display_status()
                
                if run_once:
                    break
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self.stdout.write("\nMonitoring stopped.")
    
    def display_status(self):
        # Clear screen (optional - comment out if you prefer scrolling)
        # import os
        # os.system('clear' if os.name == 'posix' else 'cls')
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.stdout.write("=" * 80)
        self.stdout.write(f"RFQ PROCESSING MONITOR - {now}")
        self.stdout.write("=" * 80)
        
        # Get active locks
        active_locks = get_all_user_locks()
        
        # Get active Django Q tasks
        active_tasks = Task.objects.filter(
            stopped__isnull=True,
            func__contains='solicitations.tasks'
        ).values('id', 'name', 'func', 'started', 'args')
        
        # Get queued tasks
        queued_tasks = OrmQ.objects.filter(
            func__contains='solicitations.tasks'
        ).count()
        
        # Get pending solicitations count
        pending_solicitations = SolicitationEmailStatus.objects.filter(
            email_sent=False,
            processing_attempts__lt=3
        ).count()
        
        # Display summary
        self.stdout.write(f"SUMMARY:")
        self.stdout.write(f"Active Locks: {len(active_locks)}")
        self.stdout.write(f"Running Tasks: {len(active_tasks)}")
        self.stdout.write(f"Queued Tasks: {queued_tasks}")
        self.stdout.write(f"Pending Solicitations: {pending_solicitations}")
        self.stdout.write("")
        
        # Display active locks
        if active_locks:
            self.stdout.write("ACTIVE USER LOCKS:")
            User = get_user_model()
            for lock in active_locks:
                try:
                    user = User.objects.get(id=lock['user_id'])
                    username = user.username
                except User.DoesNotExist:
                    username = "[Unknown]"
                
                self.stdout.write(
                    f"   User {lock['user_id']:>3} ({username:>15}) | "
                    f"{lock['lock_type']:>12} | "
                    f"TTL: {lock['ttl_minutes']:>6.1f} min"
                )
        else:
            self.stdout.write("No active user locks")
        
        self.stdout.write("")
        
        # Display running tasks
        if active_tasks:
            self.stdout.write("RUNNING TASKS:")
            for task in active_tasks:
                runtime = (datetime.now() - task['started']).total_seconds() / 60
                self.stdout.write(
                    f"   Task {task['id']:>3} | "
                    f"Runtime: {runtime:>6.1f} min | "
                    f"Function: {task['func'].split('.')[-1]}"
                )
        else:
            self.stdout.write("No running tasks")
        
        self.stdout.write("")