from django import forms
from .models import Task, TaskType, TaskPriority


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            "project", "title", "prompt", "task_type", "priority",
            "llm_config", "recurrence_rule", "estimated_tokens",
        ]
        widgets = {
            "prompt": forms.Textarea(attrs={"rows": 8, "placeholder": "Describe exactly what the AI should do..."}),
            "recurrence_rule": forms.TextInput(attrs={"placeholder": "0 9 * * 1  (cron, for evergreen tasks)"}),
        }
