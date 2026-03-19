from django import forms
from .models import Project

_input = "w-full bg-gray-800 border border-gray-700/80 rounded-xl px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/20 transition-colors"
_select = _input + " appearance-none cursor-pointer"
_textarea = "w-full bg-gray-800 border border-gray-700/80 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/20 transition-colors resize-y"


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "repo_path", "remote_url", "description", "default_branch", "llm_config"]
        widgets = {
            "name": forms.TextInput(attrs={"class": _input, "placeholder": "My Awesome Project"}),
            "repo_path": forms.TextInput(attrs={"class": _input, "placeholder": "/home/user/projects/myrepo"}),
            "remote_url": forms.URLInput(attrs={"class": _input, "placeholder": "https://github.com/you/repo"}),
            "description": forms.Textarea(attrs={"class": _textarea, "rows": 3, "placeholder": "What is this project about?"}),
            "default_branch": forms.TextInput(attrs={"class": _input, "placeholder": "main"}),
            "llm_config": forms.Select(attrs={"class": _select}),
        }
