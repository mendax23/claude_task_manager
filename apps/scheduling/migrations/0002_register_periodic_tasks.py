"""
Data migration: registers the AgentQueue Celery beat periodic tasks
in the django_celery_beat database so they run automatically.
"""
from django.db import migrations


PERIODIC_TASKS = [
    {
        "name": "agentqueue.sample_idle_state",
        "task": "apps.scheduling.celery_tasks.sample_idle_state",
        "interval_every": 30,
        "interval_period": "seconds",
        "enabled": True,
    },
    {
        "name": "agentqueue.check_and_trigger",
        "task": "apps.scheduling.celery_tasks.check_and_trigger",
        "interval_every": 60,
        "interval_period": "seconds",
        "enabled": True,
    },
    {
        "name": "agentqueue.schedule_evergreen_tasks",
        "task": "apps.tasks.celery_tasks.schedule_evergreen_tasks",
        "interval_every": 5,
        "interval_period": "minutes",
        "enabled": True,
    },
    {
        "name": "agentqueue.advance_chains",
        "task": "apps.tasks.celery_tasks.advance_chains",
        "interval_every": 30,
        "interval_period": "seconds",
        "enabled": True,
    },
    {
        "name": "agentqueue.check_budget_reset",
        "task": "apps.scheduling.celery_tasks.check_budget_reset",
        "interval_every": 1,
        "interval_period": "hours",
        "enabled": True,
    },
]


def register_tasks(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    for task_def in PERIODIC_TASKS:
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=task_def["interval_every"],
            period=task_def["interval_period"],
        )
        PeriodicTask.objects.update_or_create(
            name=task_def["name"],
            defaults={
                "task": task_def["task"],
                "interval": schedule,
                "enabled": task_def["enabled"],
            },
        )


def deregister_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    names = [t["name"] for t in PERIODIC_TASKS]
    PeriodicTask.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0001_initial"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(register_tasks, deregister_tasks),
    ]
