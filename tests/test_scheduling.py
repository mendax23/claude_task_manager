import pytest
from unittest.mock import patch


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
