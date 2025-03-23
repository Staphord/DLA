from django.apps import AppConfig

class SolicitationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'solicitations'
    
    def ready(self):
        # Avoid running during migrations or certain management commands
        import sys
        if 'makemigrations' not in sys.argv and 'migrate' not in sys.argv and 'collectstatic' not in sys.argv:
            # Only run when the main Django process is running (not for every import)
            if not any(cmd in sys.argv[0] for cmd in ['pytest', 'test', 'shell']):
                try:
                    from .tasks import setup_email_schedule
                    setup_email_schedule()
                except Exception as e:
                    print(f"Error setting up email schedule: {e}")