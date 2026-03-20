from django.http import JsonResponse
from rest_framework import generics
from .models import Task, TaskRun, TaskStatus
from .serializers import TaskSerializer, TaskRunSerializer


class TaskListCreateView(generics.ListCreateAPIView):
    queryset = Task.objects.select_related("project", "llm_config").all()
    serializer_class = TaskSerializer


class TaskDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer


class TaskRunDetailView(generics.RetrieveAPIView):
    queryset = TaskRun.objects.select_related("task").all()
    serializer_class = TaskRunSerializer


def active_tasks_poll(request):
    """Lightweight polling endpoint for when WebSocket is unavailable."""
    tasks = Task.objects.filter(
        status__in=[TaskStatus.IN_PROGRESS, TaskStatus.SCHEDULED]
    ).values("pk", "title", "status")
    return JsonResponse({
        "tasks": {
            t["pk"]: {"status": t["status"], "title": t["title"]}
            for t in tasks
        }
    })
