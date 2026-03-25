import logging
from celery import shared_task
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task
def sample_idle_state():
    """Called every 30s — samples xprintidle, saves IdleEvent, broadcasts to dashboard."""
    from apps.scheduling.services.idle_detector import IdleDetector

    detector = IdleDetector()
    event = detector.sample_and_save()

    channel_layer = get_channel_layer()
    if channel_layer:
        try:
            async_to_sync(channel_layer.group_send)(
                "dashboard",
                {
                    "type": "idle_update",
                    "is_idle": event.is_idle,
                    "idle_ms": event.idle_ms,
                    "source": event.source,
                },
            )
        except Exception as e:
            logger.debug("idle broadcast skipped: %s", e)


@shared_task
def check_and_trigger():
    """Called every 60s — runs SmartScheduler, launches task if conditions met."""
    from apps.scheduling.services.scheduler import SmartScheduler
    from apps.tasks.models import TaskRun, TaskStatus
    from apps.tasks.celery_tasks import run_task

    scheduler = SmartScheduler()
    task = scheduler.should_launch()

    if not task:
        return

    logger.info("SmartScheduler launching task: %s", task.title)
    with transaction.atomic():
        from apps.tasks.models import Task as TaskModel
        task = TaskModel.objects.select_for_update().get(pk=task.pk)
        if task.status not in (TaskStatus.BACKLOG, TaskStatus.SCHEDULED):
            logger.info("Task %s status changed before launch, skipping", task.title)
            return
        run = TaskRun.objects.create(task=task)
        task.status = TaskStatus.IN_PROGRESS
        task.save(update_fields=["status", "updated_at"])
    run_task.delay(task.pk, run.pk)


@shared_task
def check_budget_reset():
    """Called hourly — resets weekly token counters if reset day/time has passed."""
    from apps.scheduling.services.budget_tracker import BudgetTracker
    BudgetTracker().reset_if_needed()


@shared_task
def cleanup_finished_tmux():
    """Called every 10 min — removes tmux windows from completed/failed tasks and temp files."""
    import glob
    import os
    from datetime import timedelta
    from apps.tasks.models import Task, TaskStatus
    from apps.tasks.services.tmux_manager import TmuxManager
    from django.utils import timezone as tz

    tmux = TmuxManager()
    cutoff = tz.now() - timedelta(minutes=10)

    # Find completed tasks that still have tmux windows
    finished = Task.objects.filter(
        status__in=[TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED],
        tmux_session__gt="",
        updated_at__lt=cutoff,
    )
    for task in finished:
        if tmux.is_alive(task.tmux_session):
            tmux.kill_session(task.tmux_session)
            logger.debug("Cleaned up tmux window for task %s", task.pk)
        task.tmux_session = ""
        task.save(update_fields=["tmux_session", "updated_at"])

    # Clean up temp output/prompt files older than 1 hour
    one_hour_ago = tz.now() - timedelta(hours=1)
    for pattern in ["/tmp/aq_task_*.txt", "/tmp/aq_task_*.json", "/tmp/aq_prompt_*.txt"]:
        for path in glob.glob(pattern):
            try:
                if os.path.getmtime(path) < one_hour_ago.timestamp():
                    os.remove(path)
            except OSError:
                pass


@shared_task
def prune_idle_events(days: int = 7):
    """Called daily — deletes IdleEvent records older than N days."""
    from datetime import timedelta
    from django.utils import timezone as tz
    from apps.scheduling.models import IdleEvent

    cutoff = tz.now() - timedelta(days=days)
    count, _ = IdleEvent.objects.filter(created_at__lt=cutoff).delete()
    if count:
        logger.info("Pruned %d idle events older than %d days", count, days)
