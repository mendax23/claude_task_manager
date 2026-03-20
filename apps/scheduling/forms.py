from django import forms
from .models import Schedule, TokenBudget


class ScheduleForm(forms.ModelForm):
    class Meta:
        model = Schedule
        fields = [
            "is_active", "idle_threshold_minutes", "away_threshold_hours",
            "max_run_window_hours", "max_concurrent_tasks", "enable_token_spreading",
            "allowed_days", "allowed_hours",
        ]


class TokenBudgetForm(forms.ModelForm):
    class Meta:
        model = TokenBudget
        fields = [
            "provider", "weekly_limit", "reset_weekday", "reset_time",
            "session_expires_at", "drain_threshold_hours",
        ]
        widgets = {
            "session_expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "reset_time": forms.TimeInput(attrs={"type": "time"}),
        }
