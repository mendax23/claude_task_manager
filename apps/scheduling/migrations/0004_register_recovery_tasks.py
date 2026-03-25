"""
Data migration: registers stale task recovery and tmux cleanup periodic tasks.
"""
from django.db import migrations


PERIODIC_TASKS = [
    {
        "name": "agentqueue.recover_stale_tasks",
        "task": "apps.tasks.celery_tasks.recover_stale_tasks",
        "interval_every": 2,
        "interval_period": "minutes",
        "enabled": True,
    },
    {
        "name": "agentqueue.cleanup_finished_tmux",
        "task": "apps.scheduling.celery_tasks.cleanup_finished_tmux",
        "interval_every": 10,
        "interval_period": "minutes",
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
        ("scheduling", "0003_schedule_max_concurrent"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(register_tasks, deregister_tasks),
    ]
