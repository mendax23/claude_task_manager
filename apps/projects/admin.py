from django.contrib import admin
from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "repo_path", "is_active", "llm_config", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "repo_path"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["created_at", "updated_at"]
