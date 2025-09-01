from django.core.management.base import BaseCommand
from solicitations.tasks import cleanup_stale_user_locks, get_all_user_locks

class Command(BaseCommand):
    help = 'Cleanup stale user processing locks'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without actually doing it',
        )
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting lock cleanup..."))
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
        
        # Get current locks
        before_locks = get_all_user_locks()
        self.stdout.write(f"Active locks before cleanup: {len(before_locks)}")
        
        if before_locks:
            self.stdout.write("Current active locks:")
            for lock in before_locks:
                self.stdout.write(
                    f"  User {lock['user_id']} | {lock['lock_type']} | TTL: {lock['ttl_minutes']} min"
                )
        
        if not options['dry_run']:
            # Perform cleanup
            result = cleanup_stale_user_locks()
            
            if result:
                self.stdout.write(self.style.SUCCESS("Cleanup completed:"))
                self.stdout.write(f"  Total locks found: {result['total_locks']}")
                self.stdout.write(f"  Stale locks identified: {result['stale_locks']}")
                self.stdout.write(f"  Active locks remaining: {result['active_locks']}")
            else:
                self.stdout.write(self.style.ERROR("Cleanup failed"))
        else:
            self.stdout.write("Dry run completed - no changes made")