from rest_framework import generics
from .models import Task, TaskRun
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
