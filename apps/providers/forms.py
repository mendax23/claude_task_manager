from django import forms
from .models import LLMConfig, ProviderType


class LLMConfigForm(forms.ModelForm):
    class Meta:
        model = LLMConfig
        fields = [
            "name", "provider_type", "is_default", "model_name",
            "api_key", "base_url", "claude_cli_path",
            "max_tokens", "temperature", "system_prompt",
        ]
        widgets = {
            "api_key": forms.PasswordInput(render_value=True),
        }

    def clean(self):
        cleaned = super().clean()
        provider_type = cleaned.get("provider_type")
        api_key = cleaned.get("api_key")
        api_required = {ProviderType.ANTHROPIC, ProviderType.OPENROUTER}
        if provider_type in api_required and not api_key:
            self.add_error("api_key", f"API key is required for {provider_type}.")
        return cleaned
