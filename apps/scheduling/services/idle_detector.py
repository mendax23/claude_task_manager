import logging
import subprocess
from datetime import timedelta
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class IdleDetector:
    """
    Two-layer idle detection:
    - Short-term: xprintidle (X11 input inactivity in ms)
    - Long-term: query IdleEvent history for extended absences (e.g. 3 days away)
    """

    def __init__(self):
        self.xprintidle_path = settings.AGENTQUEUE.get("XPRINTIDLE_PATH", "xprintidle")
        self._xprintidle_available: bool | None = None

    def check_xprintidle_available(self) -> bool:
        if self._xprintidle_available is None:
            try:
                result = subprocess.run(
                    [self.xprintidle_path],
                    capture_output=True,
                    timeout=3,
                )
                self._xprintidle_available = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._xprintidle_available = False
                logger.warning(
                    "xprintidle not found. Install it for accurate idle detection: "
                    "sudo apt install xprintidle  |  Time-based detection will be used as fallback."
                )
        return self._xprintidle_available

    def get_idle_ms(self) -> int:
        """Returns milliseconds of X11 inactivity. Returns 0 if unavailable."""
        if not self.check_xprintidle_available():
            return 0
        try:
            result = subprocess.run(
                [self.xprintidle_path],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return int(result.stdout.strip())
        except Exception as e:
            logger.warning("xprintidle error: %s", e)
            return 0

    def is_short_idle(self, threshold_minutes: int | None = None) -> bool:
        """True if xprintidle reports inactivity >= threshold."""
        if threshold_minutes is None:
            threshold_minutes = settings.AGENTQUEUE.get("DEFAULT_IDLE_THRESHOLD_MINUTES", 15)
        idle_ms = self.get_idle_ms()
        return idle_ms >= threshold_minutes * 60 * 1000

    def is_long_idle(self, threshold_hours: int | None = None) -> bool:
        """
        True if the last active IdleEvent was more than threshold_hours ago.
        This handles cases where the user is away for days (xprintidle resets on login).
        """
        if threshold_hours is None:
            threshold_hours = settings.AGENTQUEUE.get("DEFAULT_AWAY_THRESHOLD_HOURS", 1)

        from apps.scheduling.models import IdleEvent

        cutoff = timezone.now() - timedelta(hours=threshold_hours)
        recent_active = IdleEvent.objects.filter(
            is_idle=False,
            created_at__gte=cutoff,
        ).exists()
        return not recent_active

    def sample_and_save(self) -> "IdleEvent":
        """Called by Celery beat every 30s — saves current idle state to DB."""
        from apps.scheduling.models import IdleEvent

        if self.check_xprintidle_available():
            idle_ms = self.get_idle_ms()
            threshold_ms = settings.AGENTQUEUE.get("DEFAULT_IDLE_THRESHOLD_MINUTES", 15) * 60 * 1000
            is_idle = idle_ms >= threshold_ms
            source = "xprintidle"
        else:
            # Fallback: always record as "active" when we can't measure
            idle_ms = 0
            is_idle = False
            source = "time_based"

        return IdleEvent.objects.create(idle_ms=idle_ms, is_idle=is_idle, source=source)
