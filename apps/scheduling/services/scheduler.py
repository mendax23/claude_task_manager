import logging
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


class SmartScheduler:
    """
    Decides whether to launch the next queued task based on:
    1. Gate checks (tasks available, within allowed hours, budget OK)
    2. Idle detection (short idle OR long idle)
    3. Token spreading (don't over-consume early in the week)
    4. Drain mode override (session expiring, or end-of-week)
    """

    def should_launch(self) -> "Task | None":
        """
        Returns the next Task to launch, or None if conditions are not met.
        """
        from apps.tasks.models import Task, TaskStatus
        from apps.scheduling.models import Schedule
        from .idle_detector import IdleDetector
        from .budget_tracker import BudgetTracker

        schedule = Schedule.objects.filter(is_active=True).first()
        if not schedule:
            logger.debug("No active schedule — skipping")
            return None

        # 1. Gate: tasks available?
        candidate = self._get_next_candidate()
        if not candidate:
            return None

        # 2. Gate: within allowed hours?
        if not self._within_allowed_hours(schedule):
            return None

        # 3. Gate: budget available?
        llm_config = candidate.get_effective_llm_config()
        budget_ok = True
        drain_mode = False
        if llm_config:
            tracker = BudgetTracker()
            status = tracker.get_status(llm_config.pk)
            if status.get("configured"):
                drain_mode = status.get("drain_mode", False)
                pct_used = status.get("pct_used", 0)
                if pct_used >= 95:
                    logger.info("Token budget exhausted (%.1f%%) — skipping", pct_used)
                    return None

        # 4. Gate: concurrency limit
        in_progress = Task.objects.filter(status=TaskStatus.IN_PROGRESS).count()
        if in_progress >= schedule.max_concurrent_tasks:
            return None

        # 5. Idle check (skip for evergreen tasks with ignore_idle + past next_run_at)
        skip_idle = (
            candidate.ignore_idle
            and candidate.task_type == "evergreen"
            and candidate.next_run_at is not None
            and candidate.next_run_at <= timezone.now()
        )
        if not skip_idle:
            detector = IdleDetector()
            short_idle = detector.is_short_idle(schedule.idle_threshold_minutes)
            long_idle = detector.is_long_idle(schedule.away_threshold_hours)
            if not (short_idle or long_idle):
                return None

        # 6. Token spreading (skip if drain mode)
        if not drain_mode and llm_config and schedule.enable_token_spreading:
            tracker = BudgetTracker()
            if tracker.should_defer_by_curve(llm_config.pk):
                logger.info("Token spreading: deferring task (too early in week)")
                return None

        return candidate

    def _get_next_candidate(self) -> "Task | None":
        from apps.tasks.models import Task, TaskStatus

        return (
            Task.objects.filter(status__in=[TaskStatus.BACKLOG, TaskStatus.SCHEDULED])
            .filter(
                models.Q(next_run_at__isnull=True) | models.Q(next_run_at__lte=timezone.now())
            )
            .order_by("-priority", "kanban_order")
            .first()
        )

    def _within_allowed_hours(self, schedule) -> bool:
        now = timezone.localtime()
        now_hour = now.hour
        now_weekday = now.weekday()  # 0=Monday, 6=Sunday

        # Check allowed days bitmask (bit 0 = Monday, bit 6 = Sunday)
        if schedule.allowed_days is not None and schedule.allowed_days != 127:
            if not (schedule.allowed_days & (1 << now_weekday)):
                return False

        if not schedule.allowed_hours:
            return True

        for window in schedule.allowed_hours:
            start = window.get("start", 0)
            end = window.get("end", 24)
            if start <= end:
                if start <= now_hour < end:
                    return True
            else:
                # Overnight window (e.g. 22 -> 8)
                if now_hour >= start or now_hour < end:
                    return True
        return False

