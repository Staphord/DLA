from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/logs/<str:session_id>/', consumers.LogStreamConsumer.as_asgi()),
]