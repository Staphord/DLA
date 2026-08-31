from django.core.management.base import BaseCommand
from solicitations.tasks import get_all_user_locks, get_user_processing_status
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Check status of all user processing locks'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            help='Check specific user ID',
        )
        parser.add_argument(
            '--username',
            type=str,
            help='Check specific username',
        )
        parser.add_argument(
            '--detailed',
            action='store_true',
            help='Show detailed information',
        )
    
    def handle(self, *args, **options):
        User = get_user_model()
        
        if options['user_id']:
            # Check specific user by ID
            user_id = options['user_id']
            status = get_user_processing_status(user_id)
            if status:
                self.stdout.write(self.style.SUCCESS(f"Status for user ID {user_id}:"))
                self.print_user_status(status, detailed=options['detailed'])
            else:
                self.stdout.write(self.style.ERROR(f"User ID {user_id} not found"))
                
        elif options['username']:
            # Check specific user by username
            try:
                user = User.objects.get(username=options['username'])
                status = get_user_processing_status(user.id)
                if status:
                    self.stdout.write(self.style.SUCCESS(f"Status for user {options['username']}:"))
                    self.print_user_status(status, detailed=options['detailed'])
                else:
                    self.stdout.write(self.style.ERROR(f"Could not get status for user {options['username']}"))
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"User {options['username']} not found"))
                
        else:
            # Check all locks
            self.stdout.write(self.style.SUCCESS("Checking all user processing locks..."))
            
            all_locks = get_all_user_locks()
            
            if not all_locks:
                self.stdout.write(self.style.WARNING("No active user locks found"))
                return
            
            self.stdout.write(f"Found {len(all_locks)} active locks:")
            self.stdout.write("-" * 80)
            
            for lock in all_locks:
                self.stdout.write(
                    f"User {lock['user_id']:>4} | "
                    f"{lock['lock_type']:>12} | "
                    f"TTL: {lock['ttl_minutes']:>6.1f} min | "
                    f"Lock ID: {lock['lock_id']}"
                )
                
                if options['detailed']:
                    # Get detailed user info
                    try:
                        user = User.objects.get(id=lock['user_id'])
                        self.stdout.write(f"Username: {user.username}")
                    except User.DoesNotExist:
                        self.stdout.write(f"Username: [User not found]")
                    self.stdout.write("")
    
    def print_user_status(self, status, detailed=False):
        self.stdout.write(f"  Username: {status['username']}")
        self.stdout.write(f"  User ID: {status['user_id']}")
        self.stdout.write(f"  Can Process: {status['can_process']}")
        
        if status['redis_locks']:
            self.stdout.write("  Active Locks:")
            for lock_type, lock_info in status['redis_locks'].items():
                self.stdout.write(f"    - {lock_type}: TTL {lock_info['ttl_minutes']} min")
        else:
            self.stdout.write("  Active Locks: None")
        
        if status['processing_blocked_by']:
            self.stdout.write(f"  Blocked By: {', '.join(status['processing_blocked_by'])}")
        
        self.stdout.write(f"  Pending Solicitations: {status['pending_solicitations']}")
        
        if detailed:
            self.stdout.write(f"  Active Tasks: {len(status['active_tasks'])}")
            for task in status['active_tasks']:
                self.stdout.write(f"    - {task['task_name']} (ID: {task['id']})")
            
            if status['email_settings']:
                es = status['email_settings']
                self.stdout.write("  Email Settings:")
                self.stdout.write(f"    - Auto Send: {es['auto_send']}")
                self.stdout.write(f"    - Send Day: {es['send_day']}")
                self.stdout.write(f"    - Send Time: {es['send_time']}")
                self.stdout.write(f"    - Last Processed: {es['last_processed']}")