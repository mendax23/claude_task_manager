import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


class BudgetTracker:
    """Manages token budget accounting and reset logic."""

    def get_status(self, llm_config_id: int) -> dict:
        from apps.scheduling.models import TokenBudget

        try:
            budget = TokenBudget.objects.get(provider_id=llm_config_id)
        except TokenBudget.DoesNotExist:
            return {"configured": False}

        now = timezone.now()
        pct_used = budget.pct_used

        # Is drain mode active?
        drain_mode = False
        if budget.session_expires_at:
            hours_until_expiry = (budget.session_expires_at - now).total_seconds() / 3600
            drain_mode = hours_until_expiry <= budget.drain_threshold_hours

        # End-of-week drain
        pct_week_elapsed = self._pct_week_elapsed(budget)
        end_of_week_drain = pct_week_elapsed > 85 and pct_used < 70

        return {
            "configured": True,
            "weekly_limit": budget.weekly_limit,
            "tokens_used": budget.tokens_used_this_week,
            "remaining": budget.remaining,
            "pct_used": round(pct_used, 1),
            "pct_week_elapsed": round(pct_week_elapsed, 1),
            "drain_mode": drain_mode or end_of_week_drain,
            "session_expires_at": budget.session_expires_at.isoformat() if budget.session_expires_at else None,
        }

    def should_defer_by_curve(self, llm_config_id: int) -> bool:
        """Returns True if current usage exceeds the budget curve limit for this week position."""
        from apps.scheduling.models import TokenBudget

        try:
            budget = TokenBudget.objects.get(provider_id=llm_config_id)
        except TokenBudget.DoesNotExist:
            return False

        if not budget.budget_curve:
            return False

        pct_week = self._pct_week_elapsed(budget)
        pct_used = budget.pct_used

        # Find the applicable curve point
        max_allowed = 100.0
        for point in sorted(budget.budget_curve, key=lambda p: p["pct_week"]):
            if pct_week <= point["pct_week"]:
                max_allowed = point["max_pct_budget"]
                break

        return pct_used >= max_allowed

    def reset_if_needed(self):
        """Called by Celery beat hourly — resets weekly counters if reset day/time has passed."""
        from apps.scheduling.models import TokenBudget

        now = timezone.now()
        for budget in TokenBudget.objects.all():
            if self._should_reset(budget, now):
                budget.tokens_used_this_week = 0
                budget.tokens_used_this_session = 0
                budget.last_reset_at = now
                budget.save(update_fields=[
                    "tokens_used_this_week", "tokens_used_this_session",
                    "last_reset_at", "updated_at"
                ])
                logger.info("Reset token budget for %s", budget.provider)

    def _should_reset(self, budget, now) -> bool:
        if not budget.last_reset_at:
            return True
        reset_weekday = budget.reset_weekday  # 1=Monday
        reset_time = budget.reset_time
        # Find the most recent reset point
        days_since_reset = (now - budget.last_reset_at).days
        return days_since_reset >= 7

    def _pct_week_elapsed(self, budget) -> float:
        if not budget.last_reset_at:
            return 0.0
        elapsed = (timezone.now() - budget.last_reset_at).total_seconds()
        week_seconds = 7 * 24 * 3600
        return min(100.0, (elapsed / week_seconds) * 100)
