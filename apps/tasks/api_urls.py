from django.urls import path
from . import api_views

urlpatterns = [
    path("tasks/", api_views.TaskListCreateView.as_view(), name="api-task-list"),
    path("tasks/<int:pk>/", api_views.TaskDetailView.as_view(), name="api-task-detail"),
    path("runs/<int:pk>/", api_views.TaskRunDetailView.as_view(), name="api-run-detail"),
    path("poll/", api_views.active_tasks_poll, name="api-poll"),
]
