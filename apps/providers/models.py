from django.core.exceptions import ValidationError
from django.db import models
from apps.core.models import TimeStampedModel


class ProviderType(models.TextChoices):
    CLAUDE_MAX = "claude_max", "Claude Max (CLI)"
    ANTHROPIC = "anthropic", "Anthropic API"
    OPENROUTER = "openrouter", "OpenRouter"
    OLLAMA = "ollama", "Ollama (Local)"


class LLMConfig(TimeStampedModel):
    name = models.CharField(max_length=255)
    provider_type = models.CharField(max_length=30, choices=ProviderType.choices)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    # Credentials (provider-specific)
    api_key = models.CharField(max_length=500, blank=True)
    base_url = models.URLField(blank=True)  # Ollama or OpenRouter custom endpoint
    model_name = models.CharField(max_length=255, blank=True)  # e.g. claude-opus-4-6

    # Claude Max specific
    claude_cli_path = models.CharField(max_length=500, default="claude")

    # Generation params
    max_tokens = models.PositiveIntegerField(default=8192)
    temperature = models.FloatField(default=0.7)
    system_prompt = models.TextField(blank=True)
    extra_params = models.JSONField(default=dict)

    # Cost tracking (optional, for display only)
    cost_per_1k_tokens = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    class Meta:
        verbose_name = "LLM Configuration"
        verbose_name_plural = "LLM Configurations"
        ordering = ["-is_default", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"

    def clean(self):
        api_required = {ProviderType.ANTHROPIC, ProviderType.OPENROUTER}
        if self.provider_type in api_required and not self.api_key:
            raise ValidationError(
                {"api_key": f"API key is required for {self.get_provider_type_display()}."}
            )

    def save(self, *args, **kwargs):
        # Ensure only one default provider
        if self.is_default:
            LLMConfig.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
