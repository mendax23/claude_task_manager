from django.contrib import admin
from .models import LLMConfig


@admin.register(LLMConfig)
class LLMConfigAdmin(admin.ModelAdmin):
    list_display = ["name", "provider_type", "model_name", "is_default", "is_active", "created_at"]
    list_filter = ["provider_type", "is_default", "is_active"]
    search_fields = ["name", "model_name"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["name", "provider_type", "is_default", "is_active"]}),
        ("Credentials", {"fields": ["api_key", "base_url", "model_name", "claude_cli_path"]}),
        ("Generation", {"fields": ["max_tokens", "temperature", "system_prompt", "extra_params"]}),
        ("Tracking", {"fields": ["cost_per_1k_tokens", "created_at", "updated_at"]}),
    ]
