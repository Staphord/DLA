from django.core.management.base import BaseCommand
from solicitations.tasks import force_release_user_lock, get_user_processing_status
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Force release a user processing lock'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'user_id',
            type=int,
            help='User ID to release lock for',
        )
        parser.add_argument(
            '--lock-type',
            type=str,
            default='processing',
            choices=['automated', 'manual', 'large_batch', 'processing'],
            help='Type of lock to release (default: processing)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force release without confirmation',
        )
    
    def handle(self, *args, **options):
        User = get_user_model()
        user_id = options['user_id']
        lock_type = options['lock_type']
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User ID {user_id} not found"))
            return
        
        # Check current status
        status = get_user_processing_status(user_id)
        if not status:
            self.stdout.write(self.style.ERROR(f"Could not get status for user {user_id}"))
            return
        
        if lock_type not in status['redis_locks']:
            self.stdout.write(
                self.style.WARNING(f"No {lock_type} lock found for user {user.username} (ID: {user_id})")
            )
            return
        
        lock_info = status['redis_locks'][lock_type]
        
        self.stdout.write(f"Found {lock_type} lock for user {user.username} (ID: {user_id})")
        self.stdout.write(f"Lock ID: {lock_info['lock_id']}")
        self.stdout.write(f"TTL: {lock_info['ttl_minutes']} minutes")
        
        if not options['force']:
            confirm = input("Are you sure you want to force release this lock? (y/N): ")
            if confirm.lower() != 'y':
                self.stdout.write("Cancelled")
                return
        
        # Force release the lock
        released = force_release_user_lock(user_id, lock_type)
        
        if released:
            self.stdout.write(
                self.style.SUCCESS(f"Successfully released {lock_type} lock for user {user.username}")
            )
        else:
            self.stdout.write(
                self.style.ERROR(f"Failed to release {lock_type} lock for user {user.username}")
            )