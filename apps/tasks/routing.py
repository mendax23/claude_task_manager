from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/dashboard/", consumers.DashboardConsumer.as_asgi()),
    path("ws/tasks/<int:task_id>/", consumers.TaskOutputConsumer.as_asgi()),
]
