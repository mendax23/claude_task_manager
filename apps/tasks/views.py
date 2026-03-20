import csv
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import Task, TaskStatus
from .forms import TaskForm


def _error_response(message, status=400):
    """Return an HTMX-friendly error: fires the agentqueue:error client-side event."""
    response = HttpResponse(status=status)
    response["HX-Trigger"] = json.dumps({"agentqueue:error": {"message": message}})
    return response


def task_list(request):
    from django.db.models import Count, Q
    from django.core.paginator import Paginator
    from apps.projects.models import Project
    from apps.providers.models import LLMConfig
    from .forms import TaskForm

    SORT_OPTIONS = {
        "newest": "-created_at",
        "oldest": "created_at",
        "priority": "-priority",
        "title": "title",
        "updated": "-updated_at",
    }
    sort = request.GET.get("sort", "newest")
    order_field = SORT_OPTIONS.get(sort, "-created_at")
    tasks_qs = Task.objects.select_related("project", "llm_config").order_by(order_field)
    sort_options = [
        ("newest", "Newest first"),
        ("oldest", "Oldest first"),
        ("priority", "Priority"),
        ("title", "Title A-Z"),
        ("updated", "Last updated"),
    ]

    # Status counts for filter chip badges (single query)
    counts = Task.objects.aggregate(
        backlog=Count("pk", filter=Q(status=TaskStatus.BACKLOG)),
        scheduled=Count("pk", filter=Q(status=TaskStatus.SCHEDULED)),
        in_progress=Count("pk", filter=Q(status=TaskStatus.IN_PROGRESS)),
        done=Count("pk", filter=Q(status=TaskStatus.DONE)),
        failed=Count("pk", filter=Q(status=TaskStatus.FAILED)),
        paused=Count("pk", filter=Q(status=TaskStatus.PAUSED)),
        cancelled=Count("pk", filter=Q(status=TaskStatus.CANCELLED)),
    )

    # Pagination
    try:
        per_page = int(request.GET.get("per_page", 50))
    except (ValueError, TypeError):
        per_page = 50
    per_page = max(1, min(per_page, 200))  # clamp 1–200
    paginator = Paginator(tasks_qs, per_page)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(request, "tasks/list.html", {
        "tasks": page_obj,
        "page_obj": page_obj,
        "total_count": paginator.count,
        "current_sort": sort,
        "current_status": request.GET.get("status", ""),
        "sort_options": sort_options,
        "task_form": TaskForm(),
        "projects": Project.objects.all(),
        "llm_configs": LLMConfig.objects.all(),
        "status_counts": counts,
        "status_choices": TaskStatus.choices,
    })


def task_create(request):
    from django.http import HttpResponse
    from apps.projects.models import Project
    from apps.providers.models import LLMConfig

    initial = {}
    if request.method == "GET" and request.GET.get("project"):
        initial["project"] = request.GET["project"]
    form = TaskForm(request.POST or None, initial=initial)
    is_htmx = request.headers.get("HX-Request")

    if form.is_valid():
        task = form.save()
        if is_htmx:
            from urllib.parse import urlparse
            current_url = request.headers.get("HX-Current-URL", "/")
            redirect_to = urlparse(current_url).path or "/"
            response = HttpResponse()
            response["HX-Redirect"] = redirect_to
            response["HX-Trigger"] = json.dumps({"agentqueue:success": {"message": f'Task "{task.title}" added to backlog'}})
            return response
        return redirect("tasks:detail", pk=task.pk)

    ctx = {
        "form": form,
        "projects": Project.objects.all(),
        "llm_configs": LLMConfig.objects.all(),
    }
    if is_htmx:
        return render(request, "tasks/partials/create_modal_body.html", ctx)
    return render(request, "tasks/create.html", {"form": form})


def task_detail(request, pk):
    from django.db.models import Sum, Avg, F, OuterRef, Subquery
    from apps.tasks.models import TaskRun as _TaskRun
    _done_tokens_sq = _TaskRun.objects.filter(
        task=OuterRef("pk"), status=TaskStatus.DONE
    ).order_by("-started_at").values("tokens_used")[:1]
    task = get_object_or_404(
        Task.objects.select_related("project", "llm_config")
        .annotate(last_done_tokens=Subquery(_done_tokens_sq)),
        pk=pk,
    )
    partial = request.GET.get("partial")
    if partial == "card":
        return render(request, "components/task_card.html", {"task": task})
    if partial == "panel":
        runs = task.runs.order_by("-started_at")[:8]
        return render(request, "tasks/partials/detail_panel.html", {"task": task, "runs": runs})
    runs = task.runs.order_by("-started_at")[:10]
    agg = task.runs.filter(finished_at__isnull=False).aggregate(
        total_tokens=Sum("tokens_used"),
        avg_duration=Avg(F("finished_at") - F("started_at")),
    )
    total_tokens = agg["total_tokens"] or 0
    avg_duration_td = agg["avg_duration"]
    if avg_duration_td:
        total_secs = int(avg_duration_td.total_seconds())
        if total_secs >= 3600:
            avg_duration = f"{total_secs // 3600}h {(total_secs % 3600) // 60}m"
        elif total_secs >= 60:
            avg_duration = f"{total_secs // 60}m {total_secs % 60}s"
        else:
            avg_duration = f"{total_secs}s"
    else:
        avg_duration = None
    # Prev/next navigation
    prev_task = Task.objects.filter(created_at__gt=task.created_at).order_by("created_at").values_list("pk", flat=True).first()
    next_task = Task.objects.filter(created_at__lt=task.created_at).order_by("-created_at").values_list("pk", flat=True).first()

    ctx = {
        "task": task,
        "runs": runs,
        "total_tokens": total_tokens,
        "avg_duration": avg_duration,
        "status_choices": TaskStatus.choices,
        "prev_task_pk": prev_task,
        "next_task_pk": next_task,
    }
    if partial == "content":
        return render(request, "tasks/partials/detail_content.html", ctx)
    return render(request, "tasks/detail.html", ctx)


@require_POST
def task_trigger(request, pk):
    from apps.tasks.celery_tasks import run_task
    from apps.tasks.models import TaskRun

    triggerable = {
        TaskStatus.BACKLOG, TaskStatus.SCHEDULED, TaskStatus.FAILED,
        TaskStatus.CANCELLED, TaskStatus.DONE, TaskStatus.PAUSED,
    }

    with transaction.atomic():
        task = get_object_or_404(
            Task.objects.select_for_update().select_related("project", "llm_config"), pk=pk
        )

        if task.status == TaskStatus.IN_PROGRESS:
            if task.runs.filter(status=TaskStatus.IN_PROGRESS).exists():
                return _error_response("This task is already running.")

        if task.status not in triggerable and task.status != TaskStatus.IN_PROGRESS:
            return _error_response(f"Can't run a task that is already '{task.get_status_display()}'.")

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
            from django.db import close_old_connections
            close_old_connections()
            TaskRunner().run(task, run)

        threading.Thread(target=_run, daemon=True).start()

    return render(request, "components/task_card.html", {"task": task})


@require_POST
def task_cancel(request, pk):
    with transaction.atomic():
        task = get_object_or_404(Task.objects.select_for_update(), pk=pk)
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

        # Default to backlog so cancelled tasks can be re-run immediately
        next_status = request.POST.get("next_status", TaskStatus.BACKLOG)
        if next_status not in (TaskStatus.CANCELLED, TaskStatus.BACKLOG, TaskStatus.SCHEDULED):
            next_status = TaskStatus.BACKLOG

        task.status = next_status
        task.tmux_session = ""
        task.save(update_fields=["status", "tmux_session", "updated_at"])

    response = render(request, "components/task_card.html", {"task": task})
    response["HX-Trigger"] = json.dumps({"agentqueue:success": {"message": f"\"{task.title}\" cancelled."}})
    return response


def task_edit(request, pk):
    """Inline edit endpoint — GET returns edit form, POST saves and returns updated panel."""
    from apps.projects.models import Project
    from apps.providers.models import LLMConfig

    task = get_object_or_404(Task.objects.select_related("project", "llm_config"), pk=pk)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            response = HttpResponse(status=200)
            response["HX-Redirect"] = f"/tasks/{task.pk}/"
            return response
        # Restore submitted (dirty) values so the user sees what they typed
        task.title = request.POST.get("title", task.title)
        task.prompt = request.POST.get("prompt", task.prompt)
        task.recurrence_rule = request.POST.get("recurrence_rule", task.recurrence_rule)
        submitted_priority = request.POST.get("priority")
        if submitted_priority:
            task.priority = submitted_priority
        submitted_type = request.POST.get("task_type")
        if submitted_type:
            task.task_type = submitted_type
        ctx = {
            "task": task,
            "form": form,
            "form_errors": form.errors,
            "projects": Project.objects.all(),
            "llm_configs": LLMConfig.objects.all(),
        }
        return render(request, "tasks/partials/edit_form.html", ctx)

    form = TaskForm(instance=task)
    ctx = {
        "task": task,
        "form": form,
        "projects": Project.objects.all(),
        "llm_configs": LLMConfig.objects.all(),
    }
    return render(request, "tasks/partials/edit_form.html", ctx)


def tmux_attach_command(request, pk):
    task = get_object_or_404(Task, pk=pk)
    prefix = settings.AGENTQUEUE.get("TMUX_SESSION_PREFIX", "agentqueue")
    session = f"{prefix}:task-{task.pk}"
    command = f"tmux attach-session -t {session}"
    return JsonResponse({"command": command, "session": session})


@require_POST
def task_duplicate(request, pk):
    from django.contrib import messages
    task = get_object_or_404(Task, pk=pk)
    new_task = Task.objects.create(
        project=task.project,
        llm_config=task.llm_config,
        title=f"{task.title} (copy)",
        prompt=task.prompt,
        task_type=task.task_type,
        status=TaskStatus.BACKLOG,
        priority=task.priority,
        recurrence_rule=task.recurrence_rule,
        estimated_tokens=task.estimated_tokens,
        tags=list(task.tags) if task.tags else [],
    )
    messages.success(request, f'Task duplicated as "{new_task.title}"')
    return redirect("tasks:detail", pk=new_task.pk)


@require_POST
def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    permanent = request.POST.get("permanent") == "1"
    if permanent:
        task.delete()
        return redirect("dashboard:index")
    # Soft-delete: mark as cancelled so user can undo
    task.status = TaskStatus.CANCELLED
    task.save(update_fields=["status", "updated_at"])
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=200)
        response["HX-Redirect"] = "/"
        response["HX-Trigger"] = json.dumps({
            "agentqueue:undo": {"message": f'"{task.title}" deleted', "undo_url": f"/tasks/{task.pk}/restore/"}
        })
        return response
    return redirect("dashboard:index")


@require_POST
def task_restore(request, pk):
    """Undo a soft-delete — restore a cancelled task back to backlog."""
    task = get_object_or_404(Task, pk=pk)
    if task.status != TaskStatus.CANCELLED:
        return _error_response("Only cancelled tasks can be restored.")
    task.status = TaskStatus.BACKLOG
    task.save(update_fields=["status", "updated_at"])
    response = HttpResponse(status=200)
    response["HX-Trigger"] = json.dumps({
        "agentqueue:success": {"message": f'"{task.title}" restored to backlog'}
    })
    return response


@require_POST
def clear_done(request):
    """Move all done tasks to cancelled (archive) so they disappear from the kanban."""
    count = Task.objects.filter(status=TaskStatus.DONE).update(
        status=TaskStatus.CANCELLED
    )
    response = HttpResponse(status=200)
    response["HX-Redirect"] = "/"
    response["HX-Trigger"] = json.dumps({
        "agentqueue:success": {"message": f"{count} completed task{'s' if count != 1 else ''} archived."}
    })
    return response


@require_POST
def retry_failed(request):
    """Re-queue all failed tasks back to scheduled status."""
    count = Task.objects.filter(status=TaskStatus.FAILED).update(
        status=TaskStatus.SCHEDULED
    )
    response = HttpResponse(status=200)
    response["HX-Redirect"] = "/"
    response["HX-Trigger"] = json.dumps({
        "agentqueue:success": {"message": f"{count} failed task{'s' if count != 1 else ''} re-queued."}
    })
    return response


@require_POST
def run_scheduled(request):
    """Trigger all scheduled tasks at once."""
    from apps.tasks.celery_tasks import run_task
    from apps.tasks.models import TaskRun

    tasks_qs = Task.objects.filter(status=TaskStatus.SCHEDULED).select_related("project", "llm_config")
    triggered = 0
    for task_obj in tasks_qs:
        with transaction.atomic():
            task_obj = Task.objects.select_for_update().get(pk=task_obj.pk)
            if task_obj.status != TaskStatus.SCHEDULED:
                continue
            llm_config = task_obj.get_effective_llm_config()
            if not llm_config:
                continue
            run = TaskRun.objects.create(task=task_obj)
            task_obj.status = TaskStatus.IN_PROGRESS
            task_obj.save(update_fields=["status", "updated_at"])
        try:
            run_task.delay(task_obj.pk, run.pk)
        except Exception:
            import threading
            from apps.tasks.services.task_runner import TaskRunner

            def _run(t=task_obj, r=run):
                from django.db import close_old_connections
                close_old_connections()
                TaskRunner().run(t, r)
            threading.Thread(target=_run, daemon=True).start()
        triggered += 1

    response = HttpResponse(status=200)
    response["HX-Redirect"] = "/"
    response["HX-Trigger"] = json.dumps({
        "agentqueue:success": {"message": f"{triggered} scheduled task{'s' if triggered != 1 else ''} started."}
    })
    return response


@require_POST
def task_reorder(request):
    task_id = request.POST.get("task_id")
    new_status = request.POST.get("new_status")
    new_order = request.POST.get("new_order", 0)

    task = get_object_or_404(Task, pk=task_id)
    if new_status in TaskStatus.values:
        task.status = new_status
    try:
        task.kanban_order = int(new_order)
    except (ValueError, TypeError):
        task.kanban_order = 0
    task.save(update_fields=["status", "kanban_order", "updated_at"])

    return JsonResponse({"ok": True})


@require_POST
def task_bulk_action(request):
    """Handle bulk operations on multiple tasks."""
    task_ids = request.POST.getlist("task_ids")
    action = request.POST.get("action")

    if not task_ids or not action:
        return _error_response("Missing task IDs or action.")

    tasks = Task.objects.filter(pk__in=task_ids)

    if action == "delete":
        count = tasks.count()
        tasks.delete()
        response = HttpResponse(status=200)
        response["HX-Redirect"] = "/tasks/"
        response["HX-Trigger"] = json.dumps({
            "agentqueue:success": {"message": f"{count} task{'s' if count != 1 else ''} deleted."}
        })
        return response

    if action == "trigger":
        from apps.tasks.celery_tasks import run_task
        from apps.tasks.models import TaskRun

        triggered = 0
        triggerable = {TaskStatus.BACKLOG, TaskStatus.SCHEDULED, TaskStatus.FAILED, TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.PAUSED}
        for task in tasks.filter(status__in=triggerable):
            with transaction.atomic():
                task = Task.objects.select_for_update().get(pk=task.pk)
                if task.status not in triggerable:
                    continue
                task.status = TaskStatus.IN_PROGRESS
                task.save(update_fields=["status", "updated_at"])
                run = TaskRun.objects.create(task=task)
            try:
                run_task.delay(task.pk, run.pk)
            except Exception:
                import threading
                threading.Thread(target=lambda t=task, r=run: __import__('apps.tasks.services.task_runner', fromlist=['TaskRunner']).TaskRunner().run(t, r), daemon=True).start()
            triggered += 1
        response = HttpResponse(status=200)
        response["HX-Redirect"] = "/tasks/"
        response["HX-Trigger"] = json.dumps({
            "agentqueue:success": {"message": f"{triggered} task{'s' if triggered != 1 else ''} started."}
        })
        return response

    if action == "cancel":
        cancelled = 0
        for task in tasks.filter(status=TaskStatus.IN_PROGRESS):
            task.status = TaskStatus.BACKLOG
            task.save(update_fields=["status", "updated_at"])
            for run in task.runs.filter(status=TaskStatus.IN_PROGRESS):
                if run.tmux_session:
                    try:
                        from apps.tasks.services.tmux_manager import TmuxManager
                        TmuxManager().kill_session(run.tmux_session)
                    except Exception:
                        pass
                run.status = TaskStatus.CANCELLED
                run.save(update_fields=["status"])
            cancelled += 1
        response = HttpResponse(status=200)
        response["HX-Redirect"] = "/tasks/"
        response["HX-Trigger"] = json.dumps({
            "agentqueue:success": {"message": f"{cancelled} task{'s' if cancelled != 1 else ''} cancelled."}
        })
        return response

    if action in TaskStatus.values:
        count = tasks.update(status=action)
        response = HttpResponse(status=200)
        response["HX-Redirect"] = "/tasks/"
        response["HX-Trigger"] = json.dumps({
            "agentqueue:success": {"message": f"{count} task{'s' if count != 1 else ''} moved to {action.replace('_', ' ')}."}
        })
        return response

    return _error_response("Unknown action.")


@require_POST
def task_set_status(request, pk):
    """Quick status change — used from the detail page dropdown."""
    new_status = request.POST.get("status")
    if not new_status or new_status not in TaskStatus.values:
        return _error_response("Invalid status.")

    task = get_object_or_404(Task, pk=pk)

    # Don't allow setting to in_progress via this endpoint (use trigger instead)
    if new_status == TaskStatus.IN_PROGRESS:
        return _error_response("Use the Run button to start tasks.")

    task.status = new_status
    update_fields = ["status", "updated_at"]
    if new_status == TaskStatus.DONE and not task.completed_at:
        task.completed_at = timezone.now()
        update_fields.append("completed_at")
    task.save(update_fields=update_fields)

    response = HttpResponse(status=200)
    response["HX-Trigger"] = json.dumps({
        "agentqueue:success": {"message": f'Status changed to "{task.get_status_display()}"'}
    })
    return response


def task_export(request):
    """Export tasks as CSV."""
    status_filter = request.GET.get("status")
    tasks_qs = Task.objects.select_related("project").order_by("-created_at")
    if status_filter and status_filter in TaskStatus.values:
        tasks_qs = tasks_qs.filter(status=status_filter)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="agentqueue_tasks.csv"'

    writer = csv.writer(response)
    writer.writerow(["ID", "Title", "Status", "Priority", "Type", "Project", "Tags", "Created", "Updated", "Completed"])
    for t in tasks_qs:
        writer.writerow([
            t.pk,
            t.title,
            t.get_status_display(),
            t.get_priority_display(),
            t.get_task_type_display(),
            t.project.name if t.project else "",
            ", ".join(t.tags) if t.tags else "",
            t.created_at.isoformat() if t.created_at else "",
            t.updated_at.isoformat() if t.updated_at else "",
            t.completed_at.isoformat() if t.completed_at else "",
        ])
    return response
