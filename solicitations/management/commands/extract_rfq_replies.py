"""
Django management command to extract RFQ replies from user email inboxes

Usage:
    python manage.py extract_rfq_replies --user-id 1
    python manage.py extract_rfq_replies --username john
    python manage.py extract_rfq_replies --all-users
    python manage.py extract_rfq_replies --all-users --days 7
"""

from extractRfqReplies import extract_rfq_replies_for_user, extract_rfq_replies_for_all_users
from django.core.management.base import BaseCommand, CommandError
from accounts.models import CustomUser
import sys
import os

# Import the extraction script
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


class Command(BaseCommand):
    help = 'Extract RFQ replies from user email inboxes and store in database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            help='Extract for specific user ID',
        )
        parser.add_argument(
            '--username',
            type=str,
            help='Extract for specific username',
        )
        parser.add_argument(
            '--all-users',
            action='store_true',
            help='Extract for all active users',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Days back to search for emails (default: 30)',
        )

    def handle(self, *args, **options):
        user_id = options.get('user_id')
        username = options.get('username')
        all_users = options.get('all_users')
        days_back = options.get('days')

        self.stdout.write(self.style.SUCCESS('='*70))
        self.stdout.write(self.style.SUCCESS('RFQ Reply Email Extraction'))
        self.stdout.write(self.style.SUCCESS('='*70))

        if user_id:
            # Extract for specific user by ID
            self.stdout.write(
                f'\nExtracting RFQ replies for user ID: {user_id}')
            self.stdout.write(f'Searching emails from last {days_back} days\n')

            result = extract_rfq_replies_for_user(user_id, days_back=days_back)

            if result.get('success'):
                self.stdout.write(self.style.SUCCESS(
                    f"\n[SUCCESS] Extraction completed successfully!"
                ))
                self.stdout.write(f"  Extracted: {result.get('extracted', 0)}")
                self.stdout.write(f"  Errors: {result.get('errors', 0)}")
                self.stdout.write(
                    f"  Total processed: {result.get('total', 0)}")
            else:
                self.stdout.write(self.style.ERROR(
                    f"\n[ERROR] Extraction failed: {result.get('error', 'Unknown error')}"
                ))
                raise CommandError(result.get('error', 'Extraction failed'))

        elif username:
            # Extract for specific user by username
            self.stdout.write(
                f'\nExtracting RFQ replies for username: {username}')
            self.stdout.write(f'Searching emails from last {days_back} days\n')

            try:
                user = CustomUser.objects.get(username=username)
                result = extract_rfq_replies_for_user(
                    user.id, days_back=days_back)

                if result.get('success'):
                    self.stdout.write(self.style.SUCCESS(
                        f"\n[SUCCESS] Extraction completed successfully!"
                    ))
                    self.stdout.write(
                        f"  Extracted: {result.get('extracted', 0)}")
                    self.stdout.write(f"  Errors: {result.get('errors', 0)}")
                    self.stdout.write(
                        f"  Total processed: {result.get('total', 0)}")
                else:
                    self.stdout.write(self.style.ERROR(
                        f"\n[ERROR] Extraction failed: {result.get('error', 'Unknown error')}"
                    ))
                    raise CommandError(result.get(
                        'error', 'Extraction failed'))

            except CustomUser.DoesNotExist:
                raise CommandError(f"User '{username}' not found")

        elif all_users:
            # Extract for all users
            self.stdout.write(f'\nExtracting RFQ replies for ALL active users')
            self.stdout.write(f'Searching emails from last {days_back} days\n')

            results = extract_rfq_replies_for_all_users(days_back=days_back)

            # Display summary
            total_extracted = sum(r.get('extracted', 0)
                                  for r in results.values())
            total_errors = sum(r.get('errors', 0) for r in results.values())
            successful_users = sum(
                1 for r in results.values() if r.get('success'))

            self.stdout.write(self.style.SUCCESS('\n' + '='*70))
            self.stdout.write(self.style.SUCCESS('SUMMARY'))
            self.stdout.write(self.style.SUCCESS('='*70))
            self.stdout.write(f"  Users processed: {len(results)}")
            self.stdout.write(f"  Successful: {successful_users}")
            self.stdout.write(f"  Total extracted: {total_extracted}")
            self.stdout.write(f"  Total errors: {total_errors}")

            # Show per-user results
            self.stdout.write('\nPer-user results:')
            for username, result in results.items():
                if result.get('success'):
                    self.stdout.write(
                        f"  [OK] {username}: {result.get('extracted', 0)} extracted, "
                        f"{result.get('errors', 0)} errors"
                    )
                else:
                    self.stdout.write(self.style.ERROR(
                        f"  [FAIL] {username}: {result.get('error', 'Failed')}"
                    ))

        else:
            # No arguments provided
            self.stdout.write(self.style.WARNING(
                '\nNo extraction target specified. Use one of:'
            ))
            self.stdout.write('  --user-id <id>')
            self.stdout.write('  --username <username>')
            self.stdout.write('  --all-users')
            self.stdout.write('\nExamples:')
            self.stdout.write(
                '  python manage.py extract_rfq_replies --user-id 1 --days 30')
            self.stdout.write(
                '  python manage.py extract_rfq_replies --username john --days 7')
            self.stdout.write(
                '  python manage.py extract_rfq_replies --all-users')
            raise CommandError('No extraction target specified')

        self.stdout.write(self.style.SUCCESS('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS('Done!'))
        self.stdout.write(self.style.SUCCESS('='*70 + '\n'))
