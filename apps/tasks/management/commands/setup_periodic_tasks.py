"""
Register all AgentQueue periodic tasks in django_celery_beat.

Usage:
    python manage.py setup_periodic_tasks
"""
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule


INTERVAL_TASKS = [
    {
        "name": "Sample idle state",
        "task": "apps.scheduling.celery_tasks.sample_idle_state",
        "every": 30,
        "period": IntervalSchedule.SECONDS,
    },
    {
        "name": "Check and trigger tasks",
        "task": "apps.scheduling.celery_tasks.check_and_trigger",
        "every": 60,
        "period": IntervalSchedule.SECONDS,
    },
    {
        "name": "Recover stale tasks",
        "task": "apps.tasks.celery_tasks.recover_stale_tasks",
        "every": 2,
        "period": IntervalSchedule.MINUTES,
    },
    {
        "name": "Schedule evergreen tasks",
        "task": "apps.tasks.celery_tasks.schedule_evergreen_tasks",
        "every": 60,
        "period": IntervalSchedule.SECONDS,
    },
    {
        "name": "Advance task chains",
        "task": "apps.tasks.celery_tasks.advance_chains",
        "every": 60,
        "period": IntervalSchedule.SECONDS,
    },
    {
        "name": "Cleanup finished tmux windows",
        "task": "apps.scheduling.celery_tasks.cleanup_finished_tmux",
        "every": 10,
        "period": IntervalSchedule.MINUTES,
    },
]

CRONTAB_TASKS = [
    {
        "name": "Check budget reset",
        "task": "apps.scheduling.celery_tasks.check_budget_reset",
        "minute": "0",
        "hour": "*",
    },
    {
        "name": "Prune idle events",
        "task": "apps.scheduling.celery_tasks.prune_idle_events",
        "minute": "0",
        "hour": "3",
    },
]


class Command(BaseCommand):
    help = "Create or update all AgentQueue periodic tasks in django_celery_beat."

    def handle(self, *args, **options):
        created = 0
        updated = 0

        for spec in INTERVAL_TASKS:
            schedule, _ = IntervalSchedule.objects.get_or_create(
                every=spec["every"], period=spec["period"],
            )
            _, was_created = PeriodicTask.objects.update_or_create(
                name=spec["name"],
                defaults={
                    "task": spec["task"],
                    "interval": schedule,
                    "crontab": None,
                    "enabled": True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        for spec in CRONTAB_TASKS:
            schedule, _ = CrontabSchedule.objects.get_or_create(
                minute=spec["minute"],
                hour=spec["hour"],
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
            )
            _, was_created = PeriodicTask.objects.update_or_create(
                name=spec["name"],
                defaults={
                    "task": spec["task"],
                    "crontab": schedule,
                    "interval": None,
                    "enabled": True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created} created, {updated} updated "
                f"({created + updated} total periodic tasks)"
            )
        )
