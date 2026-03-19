"""
OutputStreamer: reads tmux pane output in a polling loop and broadcasts
chunks via Django Channels. Used as a background task during task execution.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


class OutputStreamer:
    """
    Polls a tmux pane every 500ms and pushes new output to the channel layer.
    Runs as an async task alongside the LLM streaming in TaskRunner.
    """

    def __init__(self, task_id: int, tmux_session: str, channel_layer):
        self.task_id = task_id
        self.tmux_session = tmux_session
        self.channel_layer = channel_layer
        self._last_output = ""
        self._running = False

    async def stream_until_done(self, done_event: asyncio.Event):
        """
        Poll tmux pane output until done_event is set.
        Broadcasts new lines to the task's channel group.
        """
        from apps.tasks.services.tmux_manager import TmuxManager
        tmux = TmuxManager()
        self._running = True

        while not done_event.is_set():
            await asyncio.sleep(0.5)
            try:
                current = tmux.capture_output(self.tmux_session, lines=100)
                if current != self._last_output:
                    new_text = self._diff(self._last_output, current)
                    if new_text:
                        await self.channel_layer.group_send(
                            f"task-{self.task_id}",
                            {
                                "type": "output_chunk",
                                "task_id": self.task_id,
                                "text": new_text,
                            },
                        )
                    self._last_output = current
            except Exception as e:
                logger.debug("OutputStreamer poll error: %s", e)

        self._running = False

    def _diff(self, old: str, new: str) -> str:
        """Returns the new content appended since the last poll."""
        if not old:
            return new
        if new.startswith(old):
            return new[len(old):]
        # Output was truncated (tmux scrollback limit) — return full new content
        return new
