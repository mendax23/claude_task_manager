from django import forms
from .models import Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "repo_path", "remote_url", "description", "default_branch", "llm_config"]
        widgets = {
            "repo_path": forms.TextInput(attrs={"placeholder": "/home/user/projects/myrepo"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }
