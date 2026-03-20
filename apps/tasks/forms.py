from django import forms
from .models import Task, TaskType, TaskPriority


class TaskForm(forms.ModelForm):
    # Comma-separated tags string — converted to list in save()
    tags_input = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "python, refactor, tests"}),
    )

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.tags:
            self.fields["tags_input"].initial = ", ".join(self.instance.tags)

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw = self.cleaned_data.get("tags_input", "")
        instance.tags = [t.strip() for t in raw.split(",") if t.strip()]
        if commit:
            instance.save()
        return instance
