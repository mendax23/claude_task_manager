import json
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from .models import Task, TaskStatus
from .forms import TaskForm


def _error_response(message, status=400):
    """Return an HTMX-friendly error: fires the agentqueue:error client-side event."""
    response = HttpResponse(status=status)
    response["HX-Trigger"] = json.dumps({"agentqueue:error": {"message": message}})
    return response


def task_list(request):
    tasks = Task.objects.select_related("project").all()
    return render(request, "tasks/list.html", {"tasks": tasks})


def task_create(request):
    from django.http import HttpResponse
    from apps.projects.models import Project
    from apps.providers.models import LLMConfig

    form = TaskForm(request.POST or None)
    is_htmx = request.headers.get("HX-Request")

    if form.is_valid():
        form.save()
        if is_htmx:
            response = HttpResponse()
            response["HX-Redirect"] = "/"
            return response
        return redirect("dashboard:index")

    ctx = {
        "form": form,
        "projects": Project.objects.all(),
        "llm_configs": LLMConfig.objects.all(),
    }
    if is_htmx:
        return render(request, "tasks/partials/create_modal_body.html", ctx)
    return render(request, "tasks/create.html", {"form": form})


def task_detail(request, pk):
    task = get_object_or_404(Task.objects.select_related("project", "llm_config"), pk=pk)
    partial = request.GET.get("partial")
    if partial == "card":
        return render(request, "tasks/partials/task_card.html", {"task": task})
    if partial == "panel":
        runs = task.runs.order_by("-started_at")[:8]
        return render(request, "tasks/partials/detail_panel.html", {"task": task, "runs": runs})
    runs = task.runs.order_by("-started_at")[:10]
    return render(request, "tasks/detail.html", {"task": task, "runs": runs})


@require_POST
def task_trigger(request, pk):
    from apps.tasks.celery_tasks import run_task
    from apps.tasks.models import TaskRun

    task = get_object_or_404(
        Task.objects.select_related("project", "llm_config"), pk=pk
    )

    triggerable = {TaskStatus.BACKLOG, TaskStatus.SCHEDULED, TaskStatus.FAILED, TaskStatus.IN_PROGRESS}
    if task.status not in triggerable:
        return _error_response(f"Can't run a task that is already '{task.get_status_display()}'.")

    if task.status == TaskStatus.IN_PROGRESS:
        if task.runs.filter(status=TaskStatus.IN_PROGRESS).exists():
            return _error_response("This task is already running.")

    llm_config = task.get_effective_llm_config()
    if not llm_config:
        return _error_response(
            f"No AI provider configured for \"{task.title}\". "
            "Add a provider in Settings → Providers and assign it to this project."
        )

    run = TaskRun.objects.create(task=task)
    task.status = TaskStatus.IN_PROGRESS
    task.save(update_fields=["status", "updated_at"])

    try:
        run_task.delay(task.pk, run.pk)
    except Exception:
        # No Celery/Redis available — run directly in a background thread
        import threading
        from apps.tasks.services.task_runner import TaskRunner

        def _run():
            TaskRunner().run(task, run)

        threading.Thread(target=_run, daemon=True).start()

    return render(request, "tasks/partials/task_card.html", {"task": task})


@require_POST
def task_cancel(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if task.status != TaskStatus.IN_PROGRESS:
        return _error_response("Only running tasks can be cancelled.")

    run = task.runs.filter(status=TaskStatus.IN_PROGRESS).first()
    if run:
        try:
            from apps.tasks.services.tmux_manager import TmuxManager
            TmuxManager().kill_session(run.tmux_session)
        except Exception:
            pass
        run.status = TaskStatus.CANCELLED
        run.save(update_fields=["status"])

    # Allow caller to specify the resulting status (e.g. 'backlog' when dragging back)
    next_status = request.POST.get("next_status", TaskStatus.CANCELLED)
    if next_status not in (TaskStatus.CANCELLED, TaskStatus.BACKLOG, TaskStatus.SCHEDULED):
        next_status = TaskStatus.CANCELLED

    task.status = next_status
    task.save(update_fields=["status", "updated_at"])

    response = render(request, "tasks/partials/task_card.html", {"task": task})
    response["HX-Trigger"] = json.dumps({"agentqueue:success": {"message": f"\"{task.title}\" cancelled."}})
    return response


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
