import json
from channels.generic.websocket import AsyncWebsocketConsumer


class DashboardConsumer(AsyncWebsocketConsumer):
    """
    Main dashboard WebSocket consumer.
    Broadcasts task updates, budget changes, and idle state to all connected clients.
    """

    GROUP_NAME = "dashboard"

    async def connect(self):
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def receive(self, text_data):
        # Client-to-server messages (e.g. manual ping)
        pass

    # --- Event handlers (called by channel layer group_send) ---

    async def task_update(self, event):
        await self.send(text_data=json.dumps({"type": "task_update", **event}))

    async def budget_update(self, event):
        await self.send(text_data=json.dumps({"type": "budget_update", **event}))

    async def idle_update(self, event):
        await self.send(text_data=json.dumps({"type": "idle_update", **event}))

    async def notification(self, event):
        await self.send(text_data=json.dumps({"type": "notification", **event}))


class TaskOutputConsumer(AsyncWebsocketConsumer):
    """
    Per-task WebSocket consumer for streaming live output.
    Clients subscribe to ws/tasks/{task_id}/ to receive output chunks.
    """

    async def connect(self):
        self.task_id = self.scope["url_route"]["kwargs"]["task_id"]
        self.group_name = f"task-{self.task_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        pass

    async def output_chunk(self, event):
        await self.send(text_data=json.dumps({"type": "output_chunk", **event}))

    async def task_complete(self, event):
        await self.send(text_data=json.dumps({"type": "task_complete", **event}))
