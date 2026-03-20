"""
Celery beat periodic task schedule.
Loaded via CELERYBEAT_SCHEDULE in settings or via DatabaseScheduler (recommended).

When using DatabaseScheduler (default), these are managed via the Django admin
under Periodic Tasks. This file serves as documentation and initial bootstrap.
"""

from celery.schedules import crontab

CELERYBEAT_SCHEDULE = {
    # Sample idle state every 30s for accurate idle detection
    "scheduling.sample_idle_state": {
        "task": "apps.scheduling.celery_tasks.sample_idle_state",
        "schedule": 30.0,
    },
    # Check whether to trigger a task every 60s
    "scheduling.check_and_trigger": {
        "task": "apps.scheduling.celery_tasks.check_and_trigger",
        "schedule": 60.0,
    },
    # Move evergreen tasks with next_run_at <= now to SCHEDULED (every 5min)
    "tasks.schedule_evergreen": {
        "task": "apps.tasks.celery_tasks.schedule_evergreen_tasks",
        "schedule": crontab(minute="*/5"),
    },
    # Advance chained tasks when a step completes (every 30s)
    "tasks.advance_chains": {
        "task": "apps.tasks.celery_tasks.advance_chains",
        "schedule": 30.0,
    },
    # Check weekly token budget reset (hourly)
    "scheduling.check_budget_reset": {
        "task": "apps.scheduling.celery_tasks.check_budget_reset",
        "schedule": crontab(minute=0, hour="*"),
    },
    # Prune old IdleEvent records (daily at 3am)
    "scheduling.prune_idle_events": {
        "task": "apps.scheduling.celery_tasks.prune_idle_events",
        "schedule": crontab(minute=0, hour=3),
    },
}
