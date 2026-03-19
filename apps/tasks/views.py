from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.conf import settings
from .models import Task, TaskStatus
from .forms import TaskForm


def task_list(request):
    tasks = Task.objects.select_related("project").all()
    return render(request, "tasks/list.html", {"tasks": tasks})


def task_create(request):
    form = TaskForm(request.POST or None)
    if form.is_valid():
        task = form.save()
        return redirect("tasks:detail", pk=task.pk)
    return render(request, "tasks/create.html", {"form": form})


def task_detail(request, pk):
    task = get_object_or_404(Task, pk=pk)
    # HTMX partial: return just the card for live updates
    if request.GET.get("partial") == "card":
        return render(request, "tasks/partials/task_card.html", {"task": task})
    runs = task.runs.order_by("-started_at")[:10]
    return render(request, "tasks/detail.html", {"task": task, "runs": runs})


@require_POST
def task_trigger(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if task.status not in (TaskStatus.BACKLOG, TaskStatus.SCHEDULED, TaskStatus.FAILED):
        return JsonResponse({"error": "Task is not in a triggerable state."}, status=400)

    from apps.tasks.celery_tasks import run_task
    from apps.tasks.models import TaskRun

    run = TaskRun.objects.create(task=task)
    task.status = TaskStatus.IN_PROGRESS
    task.save(update_fields=["status", "updated_at"])
    run_task.delay(task.pk, run.pk)

    return render(request, "tasks/partials/task_card.html", {"task": task})


@require_POST
def task_cancel(request, pk):
    task = get_object_or_404(Task, pk=pk)
    run = task.runs.filter(status=TaskStatus.IN_PROGRESS).first()
    if run:
        from apps.tasks.services.tmux_manager import TmuxManager
        TmuxManager().kill_session(run.tmux_session)
        run.status = TaskStatus.CANCELLED
        run.save(update_fields=["status"])
        task.status = TaskStatus.CANCELLED
        task.save(update_fields=["status", "updated_at"])

    return render(request, "tasks/partials/task_card.html", {"task": task})


def tmux_attach_command(request, pk):
    task = get_object_or_404(Task, pk=pk)
    prefix = settings.AGENTQUEUE.get("TMUX_SESSION_PREFIX", "agentqueue")
    session = f"{prefix}:task-{task.pk}"
    command = f"tmux attach-session -t {session}"
    return JsonResponse({"command": command, "session": session})


@require_POST
def task_reorder(request):
    task_id = request.POST.get("task_id")
    new_status = request.POST.get("new_status")
    new_order = request.POST.get("new_order", 0)

    task = get_object_or_404(Task, pk=task_id)
    if new_status in TaskStatus.values:
        task.status = new_status
    task.kanban_order = int(new_order)
    task.save(update_fields=["status", "kanban_order", "updated_at"])

    return JsonResponse({"ok": True})
