from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from .models import Project
from .forms import ProjectForm


def project_list(request):
    projects = Project.objects.filter(is_active=True)
    return render(request, "projects/list.html", {"projects": projects})


def project_detail(request, slug):
    project = get_object_or_404(Project, slug=slug)
    tasks = project.tasks.order_by("kanban_order", "-priority")
    return render(request, "projects/detail.html", {"project": project, "tasks": tasks})


def project_create(request):
    form = ProjectForm(request.POST or None)
    if form.is_valid():
        project = form.save()
        return redirect("projects:detail", slug=project.slug)
    return render(request, "projects/create.html", {"form": form})


@require_POST
def suggest_tasks(request, slug):
    project = get_object_or_404(Project, slug=slug)
    # Async task suggestion — dispatches Celery task, responds immediately
    # Full implementation in Phase 7
    from apps.projects.tasks import generate_suggestions
    generate_suggestions.delay(project.pk)
    return render(request, "projects/partials/suggestion_loading.html", {"project": project})
