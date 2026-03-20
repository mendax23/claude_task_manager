from django.urls import path
from . import views

app_name = "tasks"

urlpatterns = [
    path("", views.task_list, name="list"),
    path("create/", views.task_create, name="create"),
    path("<int:pk>/", views.task_detail, name="detail"),
    path("<int:pk>/edit/", views.task_edit, name="edit"),
    path("<int:pk>/trigger/", views.task_trigger, name="trigger"),
    path("<int:pk>/cancel/", views.task_cancel, name="cancel"),
    path("<int:pk>/duplicate/", views.task_duplicate, name="duplicate"),
    path("<int:pk>/delete/", views.task_delete, name="delete"),
    path("<int:pk>/restore/", views.task_restore, name="restore"),
    path("<int:pk>/tmux-attach/", views.tmux_attach_command, name="tmux_attach"),
    path("<int:pk>/set-status/", views.task_set_status, name="set_status"),
    path("reorder/", views.task_reorder, name="reorder"),
    path("clear-done/", views.clear_done, name="clear_done"),
    path("retry-failed/", views.retry_failed, name="retry_failed"),
    path("run-scheduled/", views.run_scheduled, name="run_scheduled"),
    path("bulk/", views.task_bulk_action, name="bulk_action"),
    path("export/", views.task_export, name="export"),
]
