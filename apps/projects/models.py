from django.db import models
from django.utils.text import slugify
from apps.core.models import TimeStampedModel


class Project(TimeStampedModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    repo_path = models.CharField(max_length=1024, help_text="Absolute path to the git repository")
    remote_url = models.URLField(blank=True, help_text="e.g. https://github.com/user/repo")
    description = models.TextField(blank=True)
    default_branch = models.CharField(max_length=100, default="main")
    is_active = models.BooleanField(default=True)
    llm_config = models.ForeignKey(
        "providers.LLMConfig",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="projects",
        help_text="Override default LLM for this project",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
