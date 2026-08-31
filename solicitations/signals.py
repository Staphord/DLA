from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
try:
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    CHANNELS_INSTALLED = True
except ImportError:
    CHANNELS_INSTALLED = False

from .models import RFQScriptLog


# ============================
# REAL-TIME LOG BROADCASTING
# ============================

@receiver(post_save, sender=RFQScriptLog)
def broadcast_new_log(sender, instance, created, **kwargs):
    """
    Broadcast new logs to WebSocket consumers
    """
    if not CHANNELS_INSTALLED:
        return

    if created and instance.session_id:
        channel_layer = get_channel_layer()
        room_group_name = f'logs_{instance.session_id}'

        log_data = {
            'type': 'new_log',
            'log': {
                'id': instance.id,
                'timestamp': instance.timestamp.isoformat() if instance.timestamp else None,
                'formatted_time': instance.timestamp.strftime('%H:%M:%S.%f')[:-3]
                if instance.timestamp else '',
                'level': instance.level,
                'category': instance.category,
                'message': instance.message,
                'cage_code': instance.cage_code,
                'rfq_id': instance.rfq_id,
                'email_recipient': instance.email_recipient,
                'email_subject': instance.email_subject,
                'error_details': instance.error_details,
                'task_id': instance.task_id,
                'session_id': instance.session_id,
                'user_id': instance.user_id,
            }
        }

        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'log_message',
                'data': log_data
            }
        )


# ============================
# EMAIL SCHEDULE SETUP (SAFE)
# ============================

@receiver(post_migrate)
def setup_email_schedule(sender, **kwargs):
    """
    Create or update email polling schedule AFTER migrations.
    Runs once. Safe for Django-Q.
    """
    if sender.name != "solicitations":
        return

    try:
        from .tasks import setup_email_schedule_sync_only
        setup_email_schedule_sync_only()
    except Exception as e:
        print(f"[Solicitations] Error setting up email schedule: {e}")
