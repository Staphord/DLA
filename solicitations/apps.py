from django.apps import AppConfig


class SolicitationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'solicitations'

    def ready(self):
        """
        SAFE:
        - Only import signal handlers
        - No database writes
        - No scheduling
        - No task execution
        """
        try:
            from . import signals  # noqa: F401
        except Exception as e:
            # Avoid crashing Django during startup
            print(f"[SolicitationsConfig] Error loading signals: {e}")
