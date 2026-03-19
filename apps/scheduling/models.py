from django.db import models
from apps.core.models import TimeStampedModel


class Schedule(TimeStampedModel):
    """Global scheduling configuration."""

    name = models.CharField(max_length=255, default="default")
    is_active = models.BooleanField(default=True)

    # Idle detection thresholds
    idle_threshold_minutes = models.PositiveIntegerField(
        default=15,
        help_text="Minutes of inactivity before considered 'short idle'",
    )
    away_threshold_hours = models.PositiveIntegerField(
        default=1,
        help_text="Hours since last activity before considered 'away'",
    )

    # Safety limits
    max_run_window_hours = models.PositiveIntegerField(
        default=4,
        help_text="Max hours of continuous task running while idle",
    )

    # Time restrictions (JSON list of {start: 22, end: 8} hour ranges)
    allowed_hours = models.JSONField(
        default=list,
        blank=True,
        help_text='e.g. [{"start": 22, "end": 8}] — empty means always allowed',
    )

    # Days of week bitmask (bit 0 = Monday, bit 6 = Sunday), 127 = all days
    allowed_days = models.IntegerField(default=127)

    # Smart token spreading
    enable_token_spreading = models.BooleanField(
        default=True,
        help_text="Prevent burning all tokens at the start of the week",
    )

    class Meta:
        ordering = ["-is_active", "name"]

    def __str__(self):
        return f"Schedule: {self.name}"


class TokenBudget(TimeStampedModel):
    """Tracks token consumption for a given LLM config."""

    provider = models.OneToOneField(
        "providers.LLMConfig",
        on_delete=models.CASCADE,
        related_name="budget",
    )

    # Weekly limits
    weekly_limit = models.PositiveIntegerField(
        default=1_000_000,
        help_text="Estimated weekly token limit (for Claude Max: configure based on your plan)",
    )
    reset_weekday = models.PositiveIntegerField(
        default=1, help_text="ISO weekday when budget resets (1=Monday)"
    )
    reset_time = models.TimeField(default="09:00")

    # Budget curve: don't use more than X% of budget before Y% of week has elapsed
    # Format: [{"pct_week": 25, "max_pct_budget": 20}, {"pct_week": 50, "max_pct_budget": 45}]
    budget_curve = models.JSONField(
        default=list,
        blank=True,
        help_text="Token spreading curve. Leave empty to disable.",
    )

    # Running totals (reset each cycle)
    tokens_used_this_week = models.PositiveIntegerField(default=0)
    tokens_used_this_session = models.PositiveIntegerField(default=0)
    session_limit = models.PositiveIntegerField(null=True, blank=True)
    last_reset_at = models.DateTimeField(null=True, blank=True)

    # Claude Max session expiry
    session_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the current Claude session expires — triggers drain mode",
    )
    drain_threshold_hours = models.PositiveIntegerField(
        default=24,
        help_text="Hours before session expiry to enter drain mode",
    )

    class Meta:
        verbose_name = "Token Budget"

    def __str__(self):
        return f"Budget for {self.provider}"

    @property
    def pct_used(self) -> float:
        if not self.weekly_limit:
            return 0.0
        return (self.tokens_used_this_week / self.weekly_limit) * 100

    @property
    def remaining(self) -> int:
        return max(0, self.weekly_limit - self.tokens_used_this_week)


class IdleEvent(TimeStampedModel):
    """Log of idle detection samples — used for long-term idle detection."""

    idle_ms = models.BigIntegerField(help_text="Milliseconds idle from xprintidle")
    is_idle = models.BooleanField()
    source = models.CharField(
        max_length=50,
        help_text="'xprintidle' or 'time_based'",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"])]

    def __str__(self):
        status = "idle" if self.is_idle else "active"
        return f"{status} @ {self.created_at}"
