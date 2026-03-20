from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from .models import Project
from .forms import ProjectForm


def project_list(request):
    from django.db.models import Count, Q
    projects = Project.objects.filter(is_active=True).annotate(
        tasks_total=Count("tasks"),
        tasks_backlog=Count("tasks", filter=Q(tasks__status="backlog")),
        tasks_running=Count("tasks", filter=Q(tasks__status="in_progress")),
        tasks_done=Count("tasks", filter=Q(tasks__status="done")),
        tasks_failed=Count("tasks", filter=Q(tasks__status="failed")),
        tasks_scheduled=Count("tasks", filter=Q(tasks__status="scheduled")),
        tasks_paused=Count("tasks", filter=Q(tasks__status="paused")),
    )
    return render(request, "projects/list.html", {"projects": projects})


def project_detail(request, slug):
    project = get_object_or_404(Project, slug=slug)
    tasks = project.tasks.select_related("llm_config").order_by("kanban_order", "-priority")
    return render(request, "projects/detail.html", {"project": project, "tasks": tasks})


def project_create(request):
    form = ProjectForm(request.POST or None)
    if form.is_valid():
        project = form.save()
        return redirect("projects:detail", slug=project.slug)
    return render(request, "projects/create.html", {"form": form})


def project_edit(request, slug):
    project = get_object_or_404(Project, slug=slug)
    form = ProjectForm(request.POST or None, instance=project)
    if request.method == "POST" and form.is_valid():
        project = form.save()
        return redirect("projects:detail", slug=project.slug)
    return render(request, "projects/edit.html", {"form": form, "project": project})


@require_POST
def project_delete(request, slug):
    project = get_object_or_404(Project, slug=slug)
    project.is_active = False
    project.save(update_fields=["is_active", "updated_at"])
    return redirect("projects:list")


@require_POST
def suggest_tasks(request, slug):
    import json
    from django.http import HttpResponse
    project = get_object_or_404(Project, slug=slug)

    llm_config = project.llm_config
    if not llm_config:
        from apps.providers.models import LLMConfig
        llm_config = LLMConfig.objects.filter(is_default=True).first()
    if not llm_config:
        response = HttpResponse(status=400)
        response["HX-Trigger"] = json.dumps({"agentqueue:error": {"message": "No AI provider configured. Add one in Providers first."}})
        return response

    try:
        from asgiref.sync import async_to_sync
        from apps.projects.services.suggestion_service import SuggestionService
        service = SuggestionService(project, llm_config)
        suggestions = async_to_sync(service.suggest_tasks)()
    except Exception as e:
        response = HttpResponse(status=500)
        response["HX-Trigger"] = json.dumps({"agentqueue:error": {"message": f"Suggestion failed: {e}"}})
        return response

    if not suggestions:
        response = HttpResponse(status=200)
        response.content = b"<p class='text-sm text-gray-500 py-4'>No suggestions returned. Try again.</p>"
        return response

    return render(request, "projects/partials/suggestions_result.html", {
        "project": project,
        "suggestions": suggestions,
    })


@require_POST
def create_from_suggestion(request, slug):
    import json
    from django.http import HttpResponse
    project = get_object_or_404(Project, slug=slug)

    title = request.POST.get("title", "").strip()
    prompt = request.POST.get("prompt", "").strip()
    task_type = request.POST.get("task_type", "one_shot")
    try:
        priority = int(request.POST.get("priority", 2))
    except (ValueError, TypeError):
        priority = 2
    tags_raw = request.POST.get("tags", "[]")

    if not title or not prompt:
        response = HttpResponse(status=400)
        response["HX-Trigger"] = json.dumps({"agentqueue:error": {"message": "Title and prompt are required."}})
        return response

    try:
        tags = json.loads(tags_raw)
    except Exception:
        # Handle Python list repr from Django template rendering
        try:
            import ast
            tags = ast.literal_eval(tags_raw)
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []

    from apps.tasks.models import Task, TaskStatus
    task = Task.objects.create(
        project=project,
        title=title,
        prompt=prompt,
        task_type=task_type,
        priority=priority,
        tags=tags,
        status=TaskStatus.BACKLOG,
    )

    response = HttpResponse(
        f'<span class="text-xs text-green-400 px-2">✓ Added</span>',
        status=200,
    )
    response["HX-Trigger"] = json.dumps({"agentqueue:success": {"message": f'"{title}" added to backlog.'}})
    return response
