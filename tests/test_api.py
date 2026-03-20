import pytest
from django.test import Client
from apps.tasks.models import Task, TaskRun, TaskStatus, TaskType, TaskPriority


@pytest.fixture
def api_client():
    return Client()


# ── Task List/Create API ──


@pytest.mark.django_db
def test_api_task_list(api_client, task):
    response = api_client.get("/api/tasks/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(t["title"] == task.title for t in data)


@pytest.mark.django_db
def test_api_task_create(api_client, project, llm_config):
    response = api_client.post(
        "/api/tasks/",
        data={
            "project": project.pk,
            "title": "API Task",
            "prompt": "Do something via API",
            "task_type": TaskType.ONE_SHOT,
            "priority": TaskPriority.MEDIUM,
            "estimated_tokens": 0,
            "kanban_order": 0,
            "chain_order": 0,
        },
        content_type="application/json",
    )
    assert response.status_code == 201
    assert Task.objects.filter(title="API Task").exists()


@pytest.mark.django_db
def test_api_task_create_missing_fields(api_client, project):
    response = api_client.post(
        "/api/tasks/",
        data={"project": project.pk},
        content_type="application/json",
    )
    assert response.status_code == 400


# ── Task Detail API ──


@pytest.mark.django_db
def test_api_task_detail(api_client, task):
    response = api_client.get(f"/api/tasks/{task.pk}/")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == task.title


@pytest.mark.django_db
def test_api_task_update(api_client, task):
    response = api_client.patch(
        f"/api/tasks/{task.pk}/",
        data={"title": "Updated Title"},
        content_type="application/json",
    )
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.title == "Updated Title"


@pytest.mark.django_db
def test_api_task_delete(api_client, task):
    pk = task.pk
    response = api_client.delete(f"/api/tasks/{pk}/")
    assert response.status_code == 204
    assert not Task.objects.filter(pk=pk).exists()


@pytest.mark.django_db
def test_api_task_detail_404(api_client):
    response = api_client.get("/api/tasks/99999/")
    assert response.status_code == 404


# ── TaskRun Detail API ──


@pytest.mark.django_db
def test_api_run_detail(api_client, task):
    run = TaskRun.objects.create(task=task)
    response = api_client.get(f"/api/runs/{run.pk}/")
    assert response.status_code == 200
    data = response.json()
    assert data["task"] == task.pk


@pytest.mark.django_db
def test_api_run_detail_404(api_client):
    response = api_client.get("/api/runs/99999/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_api_run_is_read_only(api_client, task):
    """TaskRunDetailView is RetrieveAPIView — should reject POST/PUT/DELETE."""
    run = TaskRun.objects.create(task=task)
    assert api_client.post(f"/api/runs/{run.pk}/", data={}, content_type="application/json").status_code == 405
    assert api_client.put(f"/api/runs/{run.pk}/", data={}, content_type="application/json").status_code == 405
    assert api_client.delete(f"/api/runs/{run.pk}/").status_code == 405
