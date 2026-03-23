from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.utils import timezone
from apps.core.models import TimeStampedModel


class TaskStatus(models.TextChoices):
    BACKLOG = "backlog", "Backlog"
    SCHEDULED = "scheduled", "Scheduled"
    IN_PROGRESS = "in_progress", "In Progress"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    PAUSED = "paused", "Paused"


class TaskType(models.TextChoices):
    ONE_SHOT = "one_shot", "One Shot"
    EVERGREEN = "evergreen", "Evergreen"
    CHAINED = "chained", "Chained"


class TaskPriority(models.IntegerChoices):
    LOW = 1, "Low"
    MEDIUM = 2, "Medium"
    HIGH = 3, "High"
    URGENT = 4, "Urgent"


class TaskChain(TimeStampedModel):
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="chains"
    )
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=TaskStatus.choices, default=TaskStatus.BACKLOG
    )
    current_step = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Chain: {self.title}"

    def advance(self):
        self.current_step += 1
        self.save(update_fields=["current_step", "updated_at"])

    def get_next_task(self):
        return self.tasks.filter(chain_order=self.current_step, status=TaskStatus.BACKLOG).first()


class Task(TimeStampedModel):
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="tasks"
    )
    llm_config = models.ForeignKey(
        "providers.LLMConfig",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )
    title = models.CharField(max_length=500)
    prompt = models.TextField(validators=[MaxLengthValidator(50000)])
    task_type = models.CharField(
        max_length=20, choices=TaskType.choices, default=TaskType.ONE_SHOT
    )
    status = models.CharField(
        max_length=20, choices=TaskStatus.choices, default=TaskStatus.BACKLOG
    )
    priority = models.IntegerField(
        choices=TaskPriority.choices, default=TaskPriority.MEDIUM
    )

    # Evergreen scheduling
    recurrence_rule = models.CharField(
        max_length=255,
        blank=True,
        help_text="Cron expression for evergreen tasks, e.g. '0 9 * * 1'",
    )
    next_run_at = models.DateTimeField(null=True, blank=True)
    ignore_idle = models.BooleanField(
        default=False,
        help_text="Run even when user is active (for scheduled evergreen tasks)",
    )

    # Chain support
    chain = models.ForeignKey(
        TaskChain,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )
    chain_order = models.PositiveIntegerField(default=0)

    # CLI execution options
    dangerously_skip_permissions = models.BooleanField(
        default=False,
        help_text="Pass --dangerously-skip-permissions to Claude Code CLI (no tool confirmations)",
    )

    # Loop mode: re-run task automatically on completion
    loop_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times to re-run after completion (0 = no loop)",
    )
    loop_iterations_done = models.PositiveIntegerField(
        default=0,
        help_text="Iterations completed so far in the current loop",
    )

    # Metadata
    estimated_tokens = models.PositiveIntegerField(default=0)
    tags = models.JSONField(default=list, blank=True)
    kanban_order = models.PositiveIntegerField(default=0)

    # tmux tracking
    tmux_session = models.CharField(max_length=255, blank=True)

    # Result
    result_summary = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["kanban_order", "-priority", "created_at"]

    def __str__(self):
        return self.title

    def clean(self):
        if self.task_type == TaskType.EVERGREEN and self.recurrence_rule:
            try:
                from croniter import croniter
                if not croniter.is_valid(self.recurrence_rule):
                    raise ValidationError(
                        {"recurrence_rule": "Invalid cron expression. Example: '0 9 * * 1' (Mon 9am)."}
                    )
            except ImportError:
                pass
        if self.chain_id and self.chain_order < 0:
            raise ValidationError({"chain_order": "Chain order must be zero or positive."})

    def mark_done(self, summary: str = ""):
        self.completed_at = timezone.now()
        self.result_summary = summary

        # Loop mode: if iterations remain, queue the next run instead of marking done
        if self.loop_count > 0 and self.loop_iterations_done < self.loop_count:
            self.loop_iterations_done += 1
            self.status = TaskStatus.SCHEDULED
            self.save(update_fields=[
                "status", "completed_at", "result_summary",
                "loop_iterations_done", "updated_at",
            ])
            return

        self.status = TaskStatus.DONE
        self.save(update_fields=["status", "completed_at", "result_summary", "updated_at"])

    def mark_failed(self):
        self.status = TaskStatus.FAILED
        self.save(update_fields=["status", "updated_at"])

    def reschedule_evergreen(self):
        """Compute next_run_at from recurrence_rule and reset to SCHEDULED."""
        if not self.recurrence_rule:
            return
        try:
            from croniter import croniter
            cron = croniter(self.recurrence_rule, timezone.now())
            self.next_run_at = cron.get_next(timezone.datetime)
            self.status = TaskStatus.SCHEDULED
            self.save(update_fields=["next_run_at", "status", "updated_at"])
        except Exception:
            pass

    def get_effective_llm_config(self):
        """Returns task-level config, falls back to project-level, then default."""
        if self.llm_config_id:
            return self.llm_config
        if self.project.llm_config_id:
            return self.project.llm_config
        from apps.providers.models import LLMConfig
        return LLMConfig.objects.filter(is_default=True, is_active=True).first()


class TaskRun(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="runs")
    celery_task_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=TaskStatus.choices, default=TaskStatus.IN_PROGRESS
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    tokens_used = models.PositiveIntegerField(default=0)
    output_log = models.TextField(blank=True)
    error_log = models.TextField(blank=True)
    tmux_session = models.CharField(max_length=255, blank=True)
    tmux_window = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Run #{self.pk} for {self.task.title}"
