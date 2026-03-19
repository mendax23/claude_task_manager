import pytest
from django.utils import timezone


@pytest.mark.django_db
def test_task_mark_done(task):
    task.mark_done(summary="All done")
    assert task.status == "done"
    assert task.result_summary == "All done"
    assert task.completed_at is not None


@pytest.mark.django_db
def test_task_get_effective_llm_config_task_level(task, llm_config):
    assert task.get_effective_llm_config() == llm_config


@pytest.mark.django_db
def test_task_get_effective_llm_config_project_level(db, project, llm_config):
    from apps.tasks.models import Task, TaskType, TaskStatus
    project.llm_config = llm_config
    project.save()
    task = Task.objects.create(
        project=project,
        title="No explicit config",
        prompt="test",
        task_type=TaskType.ONE_SHOT,
        status=TaskStatus.BACKLOG,
    )
    assert task.get_effective_llm_config() == llm_config


@pytest.mark.django_db
def test_llm_config_only_one_default(db):
    from apps.providers.models import LLMConfig, ProviderType
    cfg1 = LLMConfig.objects.create(name="cfg1", provider_type=ProviderType.CLAUDE_MAX, is_default=True)
    cfg2 = LLMConfig.objects.create(name="cfg2", provider_type=ProviderType.OLLAMA, is_default=True)
    cfg1.refresh_from_db()
    assert not cfg1.is_default
    assert cfg2.is_default


@pytest.mark.django_db
def test_project_slug_auto_generated(db):
    from apps.projects.models import Project
    p = Project.objects.create(name="My Awesome Project", repo_path="/tmp")
    assert p.slug == "my-awesome-project"


@pytest.mark.django_db
def test_token_budget_pct_used(db, llm_config):
    from apps.scheduling.models import TokenBudget
    budget = TokenBudget.objects.create(
        provider=llm_config,
        weekly_limit=100_000,
        tokens_used_this_week=25_000,
    )
    assert budget.pct_used == 25.0
    assert budget.remaining == 75_000


@pytest.mark.django_db
def test_task_chain_advance(db, project):
    from apps.tasks.models import TaskChain, Task, TaskType, TaskStatus
    chain = TaskChain.objects.create(project=project, title="My Chain", status=TaskStatus.IN_PROGRESS)
    t1 = Task.objects.create(
        project=project, title="Step 1", prompt="step 1", chain=chain, chain_order=0,
        task_type=TaskType.CHAINED, status=TaskStatus.BACKLOG,
    )
    t2 = Task.objects.create(
        project=project, title="Step 2", prompt="step 2", chain=chain, chain_order=1,
        task_type=TaskType.CHAINED, status=TaskStatus.BACKLOG,
    )
    assert chain.get_next_task() == t1
    chain.advance()
    assert chain.current_step == 1
    assert chain.get_next_task() == t2
