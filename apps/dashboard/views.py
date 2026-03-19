from django.shortcuts import render
from apps.tasks.models import Task, TaskStatus
from apps.scheduling.models import TokenBudget, Schedule


KANBAN_COLUMNS = [
    {"key": TaskStatus.BACKLOG, "label": "Backlog", "color": "slate"},
    {"key": TaskStatus.SCHEDULED, "label": "Scheduled", "color": "blue"},
    {"key": TaskStatus.IN_PROGRESS, "label": "In Progress", "color": "amber"},
    {"key": TaskStatus.DONE, "label": "Done", "color": "green"},
]


def dashboard(request):
    tasks = Task.objects.select_related("project", "llm_config").exclude(
        status__in=[TaskStatus.CANCELLED, TaskStatus.FAILED]
    )

    columns = []
    for col in KANBAN_COLUMNS:
        columns.append({
            **col,
            "tasks": [t for t in tasks if t.status == col["key"]],
        })

    budget = TokenBudget.objects.select_related("provider").filter(
        provider__is_default=True
    ).first()

    schedule = Schedule.objects.filter(is_active=True).first()

    return render(request, "dashboard/index.html", {
        "columns": columns,
        "budget": budget,
        "schedule": schedule,
    })
