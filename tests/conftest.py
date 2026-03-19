import pytest


@pytest.fixture
def llm_config(db):
    from apps.providers.models import LLMConfig, ProviderType
    return LLMConfig.objects.create(
        name="test-config",
        provider_type=ProviderType.CLAUDE_MAX,
        is_default=True,
        model_name="claude-opus-4-6",
    )


@pytest.fixture
def project(db):
    from apps.projects.models import Project
    return Project.objects.create(
        name="Test Project",
        repo_path="/tmp/test-repo",
    )


@pytest.fixture
def task(db, project, llm_config):
    from apps.tasks.models import Task, TaskType, TaskStatus, TaskPriority
    return Task.objects.create(
        project=project,
        llm_config=llm_config,
        title="Test Task",
        prompt="Write a hello world function",
        task_type=TaskType.ONE_SHOT,
        status=TaskStatus.BACKLOG,
        priority=TaskPriority.MEDIUM,
    )


@pytest.fixture
def schedule(db):
    from apps.scheduling.models import Schedule
    return Schedule.objects.create(
        name="test",
        is_active=True,
        idle_threshold_minutes=15,
        away_threshold_hours=1,
        enable_token_spreading=False,
    )
