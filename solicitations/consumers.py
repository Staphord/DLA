import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from .models import RFQScriptSession

class LogStreamConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Get session_id from URL route
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.room_group_name = f'logs_{self.session_id}'
        
        # Check if user is authenticated and owns this session
        user = self.scope.get('user')
        if isinstance(user, AnonymousUser):
            await self.close()
            return
            
        # Verify user owns this session
        session_exists = await self.verify_session_ownership(user, self.session_id)
        if not session_exists:
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send initial connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'session_id': self.session_id,
            'message': 'Connected to real-time logs'
        }))

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')
            
            if message_type == 'ping':
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': text_data_json.get('timestamp')
                }))
        except json.JSONDecodeError:
            pass

    async def log_message(self, event):
        """Receive message from room group"""
        await self.send(text_data=json.dumps(event['data']))

    @database_sync_to_async
    def verify_session_ownership(self, user, session_id):
        """Verify that the user owns this session"""
        try:
            RFQScriptSession.objects.get(session_id=session_id, user=user)
            return True
        except RFQScriptSession.DoesNotExist:
            return False