from django.db.models.signals import post_save
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import RFQScriptLog
import json

@receiver(post_save, sender=RFQScriptLog)
def broadcast_new_log(sender, instance, created, **kwargs):
    """Broadcast new logs to WebSocket consumers"""
    if created and instance.session_id:
        channel_layer = get_channel_layer()
        room_group_name = f'logs_{instance.session_id}'
        
        # Prepare log data for real-time display
        log_data = {
            'type': 'new_log',
            'log': {
                'id': instance.id,
                'timestamp': instance.timestamp.isoformat() if instance.timestamp else None,
                'formatted_time': instance.timestamp.strftime('%H:%M:%S.%f')[:-3] if instance.timestamp else '',
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
        
        # Send to group
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'log_message',
                'data': log_data
            }
        )