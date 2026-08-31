from django.core.management.base import BaseCommand
from solicitations.tasks import process_manual_rfq_batch
from django.contrib.auth import get_user_model
from solicitations.models import Solicitation
from django_q.tasks import async_task

class Command(BaseCommand):
    help = 'Test user processing with a small batch'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'username',
            type=str,
            help='Username to test processing for',
        )
        parser.add_argument(
            '--count',
            type=int,
            default=3,
            help='Number of solicitations to process (default: 3)',
        )
        parser.add_argument(
            '--async',
            action='store_true',
            help='Run asynchronously using Django Q',
        )
    
    def handle(self, *args, **options):
        User = get_user_model()
        username = options['username']
        count = options['count']
        run_async = options['async']
        
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User '{username}' not found"))
            return
        
        # Get some solicitations to test with
        solicitations = Solicitation.objects.filter(
            cage__isnull=False
        ).exclude(
            cage__in=['-', 'N/A', '']
        )[:count]
        
        if not solicitations.exists():
            self.stdout.write(self.style.ERROR("No valid solicitations found for testing"))
            return
        
        solicitation_ids = list(solicitations.values_list('id', flat=True))
        
        self.stdout.write(f"Testing processing for user: {username} (ID: {user.id})")
        self.stdout.write(f"Using {len(solicitation_ids)} solicitations: {solicitation_ids}")
        
        if run_async:
            # Run asynchronously
            task_id = async_task(
                'solicitations.tasks.process_manual_rfq_batch',
                solicitation_ids,
                user.id,
                task_name=f'TEST_Processing_for_{username}',
                sync=False
            )
            self.stdout.write(
                self.style.SUCCESS(f"Queued async task with ID: {task_id}")
            )
        else:
            # Run synchronously
            self.stdout.write("Running synchronously...")
            result = process_manual_rfq_batch(solicitation_ids, user.id)
            
            self.stdout.write("Result:")
            for key, value in result.items():
                self.stdout.write(f"  {key}: {value}")