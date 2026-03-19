from django.contrib import admin
from .models import Schedule, TokenBudget, IdleEvent


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "idle_threshold_minutes", "away_threshold_hours", "enable_token_spreading"]
    list_filter = ["is_active"]


@admin.register(TokenBudget)
class TokenBudgetAdmin(admin.ModelAdmin):
    list_display = ["provider", "weekly_limit", "tokens_used_this_week", "pct_used", "session_expires_at"]
    readonly_fields = ["tokens_used_this_week", "tokens_used_this_session", "last_reset_at", "created_at", "updated_at"]

    def pct_used(self, obj):
        return f"{obj.pct_used:.1f}%"


@admin.register(IdleEvent)
class IdleEventAdmin(admin.ModelAdmin):
    list_display = ["is_idle", "idle_ms", "source", "created_at"]
    list_filter = ["is_idle", "source"]
    readonly_fields = ["created_at"]
