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

        now = timezone.now()

        # Primary: tasks that are ready (backlog or scheduled with next_run_at passed)
        candidate = (
            Task.objects.filter(status__in=[TaskStatus.BACKLOG, TaskStatus.SCHEDULED])
            .filter(
                models.Q(next_run_at__isnull=True) | models.Q(next_run_at__lte=now)
            )
            .order_by("-priority", "kanban_order")
            .first()
        )
        if candidate:
            return candidate

        # Opportunistic: if budget is draining (end of week / session expiring),
        # pull forward evergreen tasks that haven't run yet this cycle, even if
        # their next_run_at is in the future. This uses remaining tokens before
        # the weekly reset instead of wasting them.
        if self._should_opportunistic_launch():
            return (
                Task.objects.filter(
                    status=TaskStatus.SCHEDULED,
                    task_type="evergreen",
                    next_run_at__gt=now,
                )
                .order_by("-priority", "next_run_at")
                .first()
            )

        return None

    def _should_opportunistic_launch(self) -> bool:
        """
        Returns True if we should pull forward evergreen tasks because
        tokens would otherwise go unused before the weekly reset.
        """
        from .budget_tracker import BudgetTracker
        from apps.providers.models import LLMConfig

        default_config = LLMConfig.objects.filter(is_default=True, is_active=True).first()
        if not default_config:
            return False

        tracker = BudgetTracker()
        status = tracker.get_status(default_config.pk)
        if not status.get("configured"):
            return False

        pct_week = status.get("pct_week_elapsed", 0)
        pct_used = status.get("pct_used", 0)
        drain_mode = status.get("drain_mode", False)

        # Opportunistic launch when:
        # 1. Drain mode is active (session expiring or end of week)
        #    AND there are meaningful tokens left (> 10% remaining)
        # 2. OR: week is >80% done and <60% of budget used (underutilization)
        if drain_mode and pct_used < 90:
            return True
        if pct_week > 80 and pct_used < 60:
            return True

        return False

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

