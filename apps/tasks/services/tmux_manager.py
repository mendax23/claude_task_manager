import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class TmuxManager:
    """
    Manages tmux sessions for task execution.
    Each task gets its own window within the 'agentqueue' tmux session.
    """

    def __init__(self):
        self.prefix = settings.AGENTQUEUE.get("TMUX_SESSION_PREFIX", "agentqueue")
        self._server = None

    @property
    def server(self):
        if self._server is None:
            try:
                import libtmux
                self._server = libtmux.Server()
            except ImportError:
                raise RuntimeError("libtmux not installed: pip install libtmux")
        return self._server

    def _find_session(self, session_name: str):
        results = self.server.sessions.filter(session_name=session_name)
        return results[0] if results else None

    def _find_window(self, session, window_name: str):
        results = session.windows.filter(window_name=window_name)
        return results[0] if results else None

    def _get_or_create_base_session(self):
        session = self._find_session(self.prefix)
        if not session:
            session = self.server.new_session(session_name=self.prefix, detach=True)
        return session

    def create_window(self, task_id: int, window_name: str | None = None) -> str:
        """Creates a new tmux window for a task. Returns 'session:window' identifier."""
        session = self._get_or_create_base_session()
        name = window_name or f"task-{task_id}"
        window = session.new_window(window_name=name, attach=False)
        return f"{self.prefix}:{name}"

    def send_command(self, session_window: str, command: str):
        """Sends a command to a tmux pane."""
        session_name, window_name = session_window.rsplit(":", 1)
        session = self._find_session(session_name)
        if not session:
            raise RuntimeError(f"tmux session '{session_name}' not found")
        window = self._find_window(session, window_name)
        if not window:
            raise RuntimeError(f"tmux window '{window_name}' not found")
        pane = window.panes[0]
        pane.send_keys(command)

    def capture_output(self, session_window: str, lines: int = 50) -> str:
        """Captures recent output from a tmux pane."""
        try:
            session_name, window_name = session_window.rsplit(":", 1)
            session = self._find_session(session_name)
            if not session:
                return ""
            window = self._find_window(session, window_name)
            if not window:
                return ""
            pane = window.panes[0]
            content = pane.capture_pane(start=f"-{lines}", end="-0")
            return "\n".join(content) if isinstance(content, list) else str(content)
        except Exception as e:
            logger.warning("tmux capture failed: %s", e)
            return ""

    def kill_session(self, session_window: str):
        """Kills a tmux window, stopping any running process."""
        if not session_window:
            return
        try:
            session_name, window_name = session_window.rsplit(":", 1)
            session = self._find_session(session_name)
            if not session:
                return
            window = self._find_window(session, window_name)
            if window:
                window.kill_window()
        except Exception as e:
            logger.warning("tmux kill failed: %s", e)

    def is_alive(self, session_window: str) -> bool:
        """Returns True if the tmux window still exists."""
        if not session_window:
            return False
        try:
            session_name, window_name = session_window.rsplit(":", 1)
            session = self._find_session(session_name)
            if not session:
                return False
            return bool(self._find_window(session, window_name))
        except Exception:
            return False

    def list_active_sessions(self) -> list[dict]:
        """Lists all agentqueue tmux windows."""
        try:
            session = self._find_session(self.prefix)
            if not session:
                return []
            return [
                {
                    "window": w.window_name,
                    "session_window": f"{self.prefix}:{w.window_name}",
                    "active": w.window_active == "1",
                }
                for w in session.windows
            ]
        except Exception:
            return []
