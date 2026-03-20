import pytest
from datetime import timedelta, time
from unittest.mock import patch, MagicMock
from django.utils import timezone


@pytest.fixture
def token_budget(db, llm_config):
    from apps.scheduling.models import TokenBudget
    return TokenBudget.objects.create(
        provider=llm_config,
        weekly_limit=1_000_000,
        tokens_used_this_week=500_000,
        tokens_used_this_session=100_000,
        last_reset_at=timezone.now() - timedelta(days=8),
        reset_weekday=1,
        reset_time=time(9, 0),
    )


# ── sample_idle_state ──


@pytest.mark.django_db
def test_sample_idle_state_creates_event():
    from apps.scheduling.celery_tasks import sample_idle_state
    from apps.scheduling.models import IdleEvent

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "120000"

    with patch("subprocess.run", return_value=mock_result):
        sample_idle_state()

    event = IdleEvent.objects.last()
    assert event is not None
    assert event.idle_ms == 120000
    assert event.source == "xprintidle"


@pytest.mark.django_db
def test_sample_idle_state_fallback_when_no_xprintidle():
    from apps.scheduling.celery_tasks import sample_idle_state
    from apps.scheduling.models import IdleEvent

    with patch("subprocess.run", side_effect=FileNotFoundError):
        sample_idle_state()

    event = IdleEvent.objects.last()
    assert event is not None
    assert event.idle_ms == 0
    assert event.source == "time_based"
    assert event.is_idle is False


# ── check_budget_reset ──


@pytest.mark.django_db
def test_check_budget_reset_resets_old_budget(token_budget):
    from apps.scheduling.celery_tasks import check_budget_reset

    check_budget_reset()
    token_budget.refresh_from_db()
    assert token_budget.tokens_used_this_week == 0
    assert token_budget.tokens_used_this_session == 0


@pytest.mark.django_db
def test_check_budget_reset_skips_recent(llm_config):
    from apps.scheduling.models import TokenBudget
    from apps.scheduling.celery_tasks import check_budget_reset

    budget = TokenBudget.objects.create(
        provider=llm_config,
        weekly_limit=1_000_000,
        tokens_used_this_week=500_000,
        last_reset_at=timezone.now() - timedelta(hours=1),
        reset_weekday=1,
        reset_time=time(9, 0),
    )
    check_budget_reset()
    budget.refresh_from_db()
    assert budget.tokens_used_this_week == 500_000  # unchanged


# ── schedule_evergreen_tasks ──


@pytest.mark.django_db
def test_schedule_evergreen_tasks_moves_to_scheduled(project, llm_config):
    from apps.tasks.models import Task, TaskType, TaskStatus
    from apps.tasks.celery_tasks import schedule_evergreen_tasks

    task = Task.objects.create(
        project=project,
        llm_config=llm_config,
        title="Evergreen Task",
        prompt="Repeat this",
        task_type=TaskType.EVERGREEN,
        status=TaskStatus.BACKLOG,
        next_run_at=timezone.now() - timedelta(hours=1),
        recurrence_rule="0 9 * * 1",
    )
    schedule_evergreen_tasks()
    task.refresh_from_db()
    assert task.status == TaskStatus.SCHEDULED


@pytest.mark.django_db
def test_schedule_evergreen_tasks_skips_future(project, llm_config):
    from apps.tasks.models import Task, TaskType, TaskStatus
    from apps.tasks.celery_tasks import schedule_evergreen_tasks

    task = Task.objects.create(
        project=project,
        llm_config=llm_config,
        title="Future Evergreen",
        prompt="Not yet",
        task_type=TaskType.EVERGREEN,
        status=TaskStatus.BACKLOG,
        next_run_at=timezone.now() + timedelta(days=1),
        recurrence_rule="0 9 * * 1",
    )
    schedule_evergreen_tasks()
    task.refresh_from_db()
    assert task.status == TaskStatus.BACKLOG


# ── advance_chains ──


@pytest.mark.django_db
def test_advance_chains_moves_to_next_step(project, llm_config):
    from apps.tasks.models import TaskChain, Task, TaskRun, TaskType, TaskStatus
    from apps.tasks.celery_tasks import advance_chains

    chain = TaskChain.objects.create(
        project=project, title="Test Chain", status=TaskStatus.IN_PROGRESS, current_step=0,
    )
    t1 = Task.objects.create(
        project=project, llm_config=llm_config,
        title="Step 1", prompt="do step 1",
        task_type=TaskType.CHAINED, status=TaskStatus.DONE,
        chain=chain, chain_order=0,
    )
    t2 = Task.objects.create(
        project=project, llm_config=llm_config,
        title="Step 2", prompt="do step 2",
        task_type=TaskType.CHAINED, status=TaskStatus.BACKLOG,
        chain=chain, chain_order=1,
    )

    with patch("apps.tasks.celery_tasks.run_task") as mock_run:
        mock_run.delay = MagicMock()
        advance_chains()

    chain.refresh_from_db()
    assert chain.current_step == 1
    t2.refresh_from_db()
    assert t2.status == TaskStatus.IN_PROGRESS
    assert TaskRun.objects.filter(task=t2).exists()


@pytest.mark.django_db
def test_advance_chains_marks_done_when_all_complete(project, llm_config):
    from apps.tasks.models import TaskChain, Task, TaskType, TaskStatus
    from apps.tasks.celery_tasks import advance_chains

    chain = TaskChain.objects.create(
        project=project, title="Done Chain", status=TaskStatus.IN_PROGRESS, current_step=0,
    )
    Task.objects.create(
        project=project, llm_config=llm_config,
        title="Only Step", prompt="do it",
        task_type=TaskType.CHAINED, status=TaskStatus.DONE,
        chain=chain, chain_order=0,
    )

    advance_chains()
    chain.refresh_from_db()
    assert chain.status == TaskStatus.DONE


@pytest.mark.django_db
def test_advance_chains_skips_incomplete_step(project, llm_config):
    from apps.tasks.models import TaskChain, Task, TaskType, TaskStatus
    from apps.tasks.celery_tasks import advance_chains

    chain = TaskChain.objects.create(
        project=project, title="Wait Chain", status=TaskStatus.IN_PROGRESS, current_step=0,
    )
    Task.objects.create(
        project=project, llm_config=llm_config,
        title="Still Running", prompt="busy",
        task_type=TaskType.CHAINED, status=TaskStatus.IN_PROGRESS,
        chain=chain, chain_order=0,
    )

    advance_chains()
    chain.refresh_from_db()
    assert chain.current_step == 0  # unchanged
