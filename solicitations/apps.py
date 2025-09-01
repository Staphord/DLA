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
                    # Import and call the sync-only version during app startup
                    from .tasks import setup_email_schedule_sync_only
                    setup_email_schedule_sync_only()
                except Exception as e:
                    print(f"Error setting up email schedule: {e}")
                
                # Import signals for real-time log broadcasting
                try:
                    from . import signals
                except Exception as e:
                    print(f"Error importing signals: {e}")