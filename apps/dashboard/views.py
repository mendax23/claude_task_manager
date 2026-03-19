from django.shortcuts import render
from django.http import JsonResponse
from apps.tasks.models import Task, TaskStatus
from apps.scheduling.models import TokenBudget, Schedule
from apps.scheduling.services.idle_detector import IdleDetector


KANBAN_COLUMNS = [
    {"key": TaskStatus.BACKLOG, "label": "Backlog", "icon": "inbox"},
    {"key": TaskStatus.SCHEDULED, "label": "Scheduled", "icon": "clock"},
    {"key": TaskStatus.IN_PROGRESS, "label": "In Progress", "icon": "play"},
    {"key": TaskStatus.DONE, "label": "Done", "icon": "check"},
]


def dashboard(request):
    tasks = list(
        Task.objects.select_related("project", "llm_config")
        .exclude(status__in=[TaskStatus.CANCELLED, TaskStatus.FAILED])
        .order_by("kanban_order", "-priority", "created_at")
    )

    columns = [
        {**col, "tasks": [t for t in tasks if t.status == col["key"]]}
        for col in KANBAN_COLUMNS
    ]

    budget = TokenBudget.objects.select_related("provider").filter(
        provider__is_default=True
    ).first()

    schedule = Schedule.objects.filter(is_active=True).first()

    failed_tasks = Task.objects.filter(status=TaskStatus.FAILED).count()

    return render(request, "dashboard/index.html", {
        "columns": columns,
        "budget": budget,
        "schedule": schedule,
        "failed_count": failed_tasks,
        "total_tasks": len(tasks),
    })


def budget_bar(request):
    """HTMX partial: refreshed token budget bar content."""
    budget = TokenBudget.objects.select_related("provider").filter(
        provider__is_default=True
    ).first()
    detector = IdleDetector()
    is_idle = detector.is_short_idle()
    return render(request, "components/token_budget_bar.html", {
        "budget": budget,
        "is_idle": is_idle,
    })
