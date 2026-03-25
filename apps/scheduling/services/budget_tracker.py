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

        reset_weekday = budget.reset_weekday  # 1=Monday (ISO weekday)
        reset_time = budget.reset_time

        # Convert ISO weekday (1=Mon) to Python isoweekday() for comparison
        current_weekday = now.isoweekday()  # 1=Monday, 7=Sunday
        current_time = now.time()

        # Build the most recent reset point: last occurrence of reset_weekday at reset_time
        days_since_target_day = (current_weekday - reset_weekday) % 7
        candidate_date = (now - timedelta(days=days_since_target_day)).date()

        from datetime import datetime
        candidate_dt = datetime.combine(candidate_date, reset_time)
        if now.tzinfo:
            from django.utils import timezone as tz
            candidate_dt = tz.make_aware(candidate_dt, now.tzinfo)

        # If candidate is in the future (same weekday but time hasn't passed), go back a week
        if candidate_dt > now:
            candidate_dt -= timedelta(days=7)

        # Reset if the last reset was before the most recent valid reset point
        return budget.last_reset_at < candidate_dt

    def get_burn_rate_status(self, llm_config_id: int) -> dict:
        """
        Calculates whether tokens are being underutilized based on burn rate.
        Returns a dict with:
          - tokens_per_hour_available: how many tokens/hour remain until reset
          - tokens_per_hour_avg: average user consumption rate this week
          - surplus: True if projected waste > 20% of weekly limit
          - hours_until_reset: hours until next budget reset
        """
        from apps.scheduling.models import TokenBudget

        try:
            budget = TokenBudget.objects.get(provider_id=llm_config_id)
        except TokenBudget.DoesNotExist:
            return {"surplus": False}

        pct_week = self._pct_week_elapsed(budget)
        if pct_week < 1:
            return {"surplus": False}

        # Hours elapsed and remaining in the week
        elapsed_hours = max(1, (pct_week / 100) * 7 * 24)
        remaining_hours = max(1, ((100 - pct_week) / 100) * 7 * 24)

        # User's actual consumption rate this week
        tokens_per_hour_avg = budget.tokens_used_this_week / elapsed_hours

        # Available tokens per hour if we want to use everything before reset
        tokens_per_hour_available = budget.remaining / remaining_hours

        # Surplus exists when the available rate significantly exceeds usage rate
        # i.e. the user won't use all tokens at their current pace
        projected_usage = tokens_per_hour_avg * remaining_hours
        projected_waste = budget.remaining - projected_usage
        surplus = projected_waste > (budget.weekly_limit * 0.20)  # >20% would go unused

        return {
            "surplus": surplus,
            "tokens_per_hour_available": round(tokens_per_hour_available),
            "tokens_per_hour_avg": round(tokens_per_hour_avg),
            "projected_waste_pct": round((projected_waste / budget.weekly_limit) * 100, 1) if budget.weekly_limit else 0,
            "hours_until_reset": round(remaining_hours, 1),
            "remaining": budget.remaining,
        }

    def _pct_week_elapsed(self, budget) -> float:
        if not budget.last_reset_at:
            return 0.0
        elapsed = (timezone.now() - budget.last_reset_at).total_seconds()
        week_seconds = 7 * 24 * 3600
        return min(100.0, (elapsed / week_seconds) * 100)
