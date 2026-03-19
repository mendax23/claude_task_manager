from django.contrib import admin
from .models import Task, TaskRun, TaskChain


class TaskRunInline(admin.TabularInline):
    model = TaskRun
    extra = 0
    readonly_fields = ["started_at", "finished_at", "status", "tokens_used", "tmux_session"]
    fields = ["status", "started_at", "finished_at", "tokens_used", "tmux_session"]
    can_delete = False


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "task_type", "status", "priority", "next_run_at", "created_at"]
    list_filter = ["status", "task_type", "priority", "project"]
    search_fields = ["title", "prompt"]
    readonly_fields = ["created_at", "updated_at", "completed_at"]
    inlines = [TaskRunInline]
    fieldsets = [
        (None, {"fields": ["project", "title", "task_type", "status", "priority"]}),
        ("Prompt", {"fields": ["prompt", "llm_config"]}),
        ("Scheduling", {"fields": ["recurrence_rule", "next_run_at", "estimated_tokens", "kanban_order"]}),
        ("Chain", {"fields": ["chain", "chain_order"]}),
        ("Result", {"fields": ["result_summary", "completed_at"]}),
        ("Meta", {"fields": ["tags", "tmux_session", "created_at", "updated_at"]}),
    ]


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = ["task", "status", "started_at", "finished_at", "tokens_used"]
    list_filter = ["status"]
    search_fields = ["task__title"]
    readonly_fields = ["started_at", "finished_at", "created_at", "updated_at"]


@admin.register(TaskChain)
class TaskChainAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "status", "current_step", "created_at"]
    list_filter = ["status"]
