import pytest
from datetime import timedelta, time, datetime
from unittest.mock import patch
from django.utils import timezone


@pytest.mark.django_db
def test_smart_scheduler_no_schedule_returns_none():
    from apps.scheduling.services.scheduler import SmartScheduler
    # No Schedule object exists -> should return None
    result = SmartScheduler().should_launch()
    assert result is None


@pytest.mark.django_db
def test_smart_scheduler_no_tasks_returns_none(schedule):
    from apps.scheduling.services.scheduler import SmartScheduler
    result = SmartScheduler().should_launch()
    assert result is None


@pytest.mark.django_db
def test_smart_scheduler_not_idle_returns_none(schedule, task):
    from apps.scheduling.services.scheduler import SmartScheduler
    from apps.scheduling.services.idle_detector import IdleDetector

    with patch.object(IdleDetector, 'is_short_idle', return_value=False), \
         patch.object(IdleDetector, 'is_long_idle', return_value=False):
        result = SmartScheduler().should_launch()
        assert result is None


@pytest.mark.django_db
def test_smart_scheduler_idle_launches_task(schedule, task):
    from apps.scheduling.services.scheduler import SmartScheduler
    from apps.scheduling.services.idle_detector import IdleDetector

    with patch.object(IdleDetector, 'is_short_idle', return_value=True), \
         patch.object(IdleDetector, 'is_long_idle', return_value=False):
        result = SmartScheduler().should_launch()
        assert result == task


@pytest.mark.django_db
def test_smart_scheduler_skips_when_task_in_progress(schedule, task):
    from apps.scheduling.services.scheduler import SmartScheduler
    from apps.scheduling.services.idle_detector import IdleDetector
    from apps.tasks.models import TaskStatus

    task.status = TaskStatus.IN_PROGRESS
    task.save()

    with patch.object(IdleDetector, 'is_short_idle', return_value=True):
        result = SmartScheduler().should_launch()
        assert result is None


@pytest.mark.django_db
def test_budget_tracker_reset(db, llm_config):
    from apps.scheduling.models import TokenBudget
    from apps.scheduling.services.budget_tracker import BudgetTracker
    from django.utils import timezone
    from datetime import timedelta

    budget = TokenBudget.objects.create(
        provider=llm_config,
        weekly_limit=1_000_000,
        tokens_used_this_week=500_000,
        last_reset_at=timezone.now() - timedelta(days=8),
    )

    BudgetTracker().reset_if_needed()
    budget.refresh_from_db()
    assert budget.tokens_used_this_week == 0


@pytest.mark.django_db
def test_idle_detector_long_idle_with_no_events(db):
    from apps.scheduling.services.idle_detector import IdleDetector
    # No IdleEvents in DB = user has been away since the beginning
    result = IdleDetector().is_long_idle(threshold_hours=1)
    assert result is True


# ── Budget Reset Weekday/Time Tests ──


@pytest.mark.django_db
def test_budget_reset_on_correct_weekday(db, llm_config):
    from apps.scheduling.models import TokenBudget
    from apps.scheduling.services.budget_tracker import BudgetTracker

    now = timezone.now()
    current_weekday = now.isoweekday()  # 1=Mon .. 7=Sun

    budget = TokenBudget.objects.create(
        provider=llm_config,
        weekly_limit=1_000_000,
        tokens_used_this_week=500_000,
        reset_weekday=current_weekday,
        reset_time=time(0, 0),
        last_reset_at=now - timedelta(days=8),
    )

    BudgetTracker().reset_if_needed()
    budget.refresh_from_db()
    assert budget.tokens_used_this_week == 0


@pytest.mark.django_db
def test_budget_reset_skips_wrong_weekday(db, llm_config):
    from apps.scheduling.models import TokenBudget
    from apps.scheduling.services.budget_tracker import BudgetTracker

    now = timezone.now()
    # Pick a weekday that's NOT today but also makes it so no reset point
    # was passed since last_reset_at
    wrong_weekday = ((now.isoweekday()) % 7) + 1  # tomorrow's weekday

    budget = TokenBudget.objects.create(
        provider=llm_config,
        weekly_limit=1_000_000,
        tokens_used_this_week=500_000,
        reset_weekday=wrong_weekday,
        reset_time=time(0, 0),
        # Last reset was 2 days ago — not yet time for next reset on wrong weekday
        last_reset_at=now - timedelta(days=2),
    )

    BudgetTracker().reset_if_needed()
    budget.refresh_from_db()
    assert budget.tokens_used_this_week == 500_000


@pytest.mark.django_db
def test_budget_reset_missed_window_still_triggers(db, llm_config):
    from apps.scheduling.models import TokenBudget
    from apps.scheduling.services.budget_tracker import BudgetTracker

    now = timezone.now()
    budget = TokenBudget.objects.create(
        provider=llm_config,
        weekly_limit=1_000_000,
        tokens_used_this_week=750_000,
        reset_weekday=1,
        reset_time=time(9, 0),
        last_reset_at=now - timedelta(days=14),  # missed 2 weeks
    )

    BudgetTracker().reset_if_needed()
    budget.refresh_from_db()
    assert budget.tokens_used_this_week == 0


@pytest.mark.django_db
def test_budget_no_reset_at_means_reset(db, llm_config):
    from apps.scheduling.models import TokenBudget
    from apps.scheduling.services.budget_tracker import BudgetTracker

    budget = TokenBudget.objects.create(
        provider=llm_config,
        weekly_limit=1_000_000,
        tokens_used_this_week=500_000,
        last_reset_at=None,
    )

    BudgetTracker().reset_if_needed()
    budget.refresh_from_db()
    assert budget.tokens_used_this_week == 0


@pytest.mark.django_db
def test_budget_tracker_should_defer_by_curve(db, llm_config):
    from apps.scheduling.models import TokenBudget
    from apps.scheduling.services.budget_tracker import BudgetTracker

    budget = TokenBudget.objects.create(
        provider=llm_config,
        weekly_limit=1_000_000,
        tokens_used_this_week=300_000,  # 30% used
        last_reset_at=timezone.now() - timedelta(hours=12),  # ~7% of week elapsed
        budget_curve=[
            {"pct_week": 25, "max_pct_budget": 20},
            {"pct_week": 50, "max_pct_budget": 45},
        ],
    )

    tracker = BudgetTracker()
    # 30% used but only 7% of week elapsed, curve says max 20% at 25% elapsed
    assert tracker.should_defer_by_curve(llm_config.pk) is True


@pytest.mark.django_db
def test_budget_tracker_no_curve_no_defer(db, llm_config):
    from apps.scheduling.models import TokenBudget
    from apps.scheduling.services.budget_tracker import BudgetTracker

    TokenBudget.objects.create(
        provider=llm_config,
        weekly_limit=1_000_000,
        tokens_used_this_week=900_000,
        last_reset_at=timezone.now() - timedelta(hours=1),
        budget_curve=[],
    )

    tracker = BudgetTracker()
    assert tracker.should_defer_by_curve(llm_config.pk) is False
