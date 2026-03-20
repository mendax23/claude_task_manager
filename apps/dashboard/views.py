from datetime import timedelta

from django.db.models import OuterRef, Q, Subquery, Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.projects.models import Project
from apps.providers.models import LLMConfig
from apps.scheduling.models import Schedule, TokenBudget
from apps.scheduling.services.idle_detector import IdleDetector
from apps.tasks.forms import TaskForm
from apps.tasks.models import Task, TaskRun, TaskStatus


KANBAN_COLUMNS = [
    {"key": TaskStatus.BACKLOG, "label": "Backlog", "icon": "inbox"},
    {"key": TaskStatus.SCHEDULED, "label": "Scheduled", "icon": "clock"},
    {"key": TaskStatus.IN_PROGRESS, "label": "In Progress", "icon": "play"},
    {"key": TaskStatus.DONE, "label": "Done", "icon": "check"},
]

_done_tokens_sq = TaskRun.objects.filter(
    task=OuterRef("pk"), status=TaskStatus.DONE
).order_by("-started_at").values("tokens_used")[:1]


def dashboard(request):
    tasks = list(
        Task.objects.select_related("project", "llm_config")
        .annotate(last_done_tokens=Subquery(_done_tokens_sq))
        .exclude(status=TaskStatus.CANCELLED)
        .order_by("kanban_order", "-priority", "created_at")
    )

    def tasks_for_column(col_key):
        # Failed and paused tasks appear in backlog so they're visible and re-runnable
        if col_key == TaskStatus.BACKLOG:
            return [t for t in tasks if t.status in (TaskStatus.BACKLOG, TaskStatus.FAILED, TaskStatus.PAUSED)]
        return [t for t in tasks if t.status == col_key]

    columns = [
        {**col, "tasks": tasks_for_column(col["key"])}
        for col in KANBAN_COLUMNS
    ]

    budget = TokenBudget.objects.select_related("provider").filter(
        provider__is_default=True
    ).first()

    schedule = Schedule.objects.filter(is_active=True).first()

    failed_tasks = Task.objects.filter(status=TaskStatus.FAILED).count()
    running_count = sum(1 for t in tasks if t.status == TaskStatus.IN_PROGRESS)
    done_count = sum(1 for t in tasks if t.status == TaskStatus.DONE)
    scheduled_count = sum(1 for t in tasks if t.status == TaskStatus.SCHEDULED)

    # Weekly stats
    one_week_ago = timezone.now() - timedelta(days=7)
    week_runs = TaskRun.objects.filter(started_at__gte=one_week_ago)
    week_done = week_runs.filter(status=TaskStatus.DONE).count()
    week_failed = week_runs.filter(status=TaskStatus.FAILED).count()
    week_total_finished = week_done + week_failed
    week_tokens = week_runs.aggregate(t=Sum("tokens_used"))["t"] or 0
    success_rate = round(week_done / week_total_finished * 100) if week_total_finished else None

    # Recent activity feed — last 12 runs
    recent_runs = (
        TaskRun.objects.select_related("task", "task__project")
        .exclude(status=TaskStatus.IN_PROGRESS)
        .order_by("-started_at")[:12]
    )

    # Per-project breakdown — use prefetch_related and evaluate to list to avoid N+1
    project_stats = list(
        Project.objects.filter(is_active=True)
        .prefetch_related("tasks")
    )
    project_breakdown = []
    for p in project_stats:
        p_tasks = list(p.tasks.all())  # uses prefetch cache — no extra queries
        if not p_tasks:
            continue
        running = sum(1 for t in p_tasks if t.status == TaskStatus.IN_PROGRESS)
        queued = sum(1 for t in p_tasks if t.status in (TaskStatus.BACKLOG, TaskStatus.SCHEDULED))
        done = sum(1 for t in p_tasks if t.status == TaskStatus.DONE)
        project_breakdown.append({
            "project": p,
            "running": running,
            "queued": queued,
            "done": done,
            "total": len(p_tasks),
        })
    project_breakdown.sort(key=lambda x: (-x["running"], -x["queued"], -x["total"]))

    return render(request, "dashboard/index.html", {
        "columns": columns,
        "budget": budget,
        "schedule": schedule,
        "failed_count": failed_tasks,
        "total_tasks": len(tasks),
        "running_count": running_count,
        "done_count": done_count,
        "scheduled_count": scheduled_count,
        "project_count": Project.objects.count(),
        "task_form": TaskForm(),
        "projects": Project.objects.all(),
        "llm_configs": LLMConfig.objects.all(),
        # Weekly analytics
        "week_done": week_done,
        "week_failed": week_failed,
        "week_tokens": week_tokens,
        "success_rate": success_rate,
        # Activity feed & project breakdown
        "recent_runs": recent_runs,
        "project_breakdown": project_breakdown,
    })


def command_search(request):
    """Global command palette search — returns HTML partial with matching results."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return render(request, "dashboard/partials/command_results.html", {
            "query": q, "tasks": [], "projects": [], "has_results": False,
        })

    tasks = Task.objects.select_related("project").filter(
        Q(title__icontains=q) | Q(prompt__icontains=q) | Q(tags__icontains=q)
    ).exclude(status=TaskStatus.CANCELLED).order_by("-priority", "-updated_at")[:8]

    from django.db.models import Count
    projects = Project.objects.filter(
        Q(name__icontains=q) | Q(description__icontains=q)
    ).annotate(task_count=Count("tasks"))[:5]

    return render(request, "dashboard/partials/command_results.html", {
        "query": q,
        "tasks": tasks,
        "projects": projects,
        "has_results": tasks.exists() or projects.exists(),
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
        "schedule": Schedule.objects.first(),
    })
