import pytest
from django.test import Client
from apps.tasks.models import Task, TaskRun, TaskStatus, TaskType, TaskPriority


@pytest.fixture
def client():
    return Client()


# ── Dashboard ──


@pytest.mark.django_db
def test_dashboard_returns_200(client, task):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Dashboard" in response.content


@pytest.mark.django_db
def test_dashboard_contains_task(client, task):
    response = client.get("/")
    assert task.title.encode() in response.content


@pytest.mark.django_db
def test_dashboard_shows_columns(client, task):
    response = client.get("/")
    assert b"Backlog" in response.content
    assert b"Scheduled" in response.content
    assert b"In Progress" in response.content
    assert b"Done" in response.content


@pytest.mark.django_db
def test_dashboard_shows_failed_count(client, project, llm_config):
    Task.objects.create(
        project=project, llm_config=llm_config,
        title="Failed Task", prompt="test", status=TaskStatus.FAILED,
    )
    response = client.get("/")
    assert b"1 failed" in response.content


# ── Task List ──


@pytest.mark.django_db
def test_task_list_returns_200(client, task):
    response = client.get("/tasks/")
    assert response.status_code == 200


# ── Task Create ──


@pytest.mark.django_db
def test_task_create_get(client, project):
    response = client.get("/tasks/create/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_create_post_valid(client, project, llm_config):
    response = client.post("/tasks/create/", {
        "project": project.pk,
        "title": "New Test Task",
        "prompt": "Do something",
        "task_type": TaskType.ONE_SHOT,
        "priority": TaskPriority.MEDIUM,
        "estimated_tokens": 0,
    })
    assert response.status_code in (200, 302)
    assert Task.objects.filter(title="New Test Task").exists()


@pytest.mark.django_db
def test_task_create_post_invalid(client, project):
    response = client.post("/tasks/create/", {
        "project": project.pk,
        "title": "",  # required
        "prompt": "",  # required
        "task_type": TaskType.ONE_SHOT,
        "priority": TaskPriority.MEDIUM,
    })
    # Form should not create task
    assert Task.objects.filter(project=project).count() == 0


@pytest.mark.django_db
def test_task_create_htmx_redirects(client, project, llm_config):
    response = client.post(
        "/tasks/create/",
        {
            "project": project.pk,
            "title": "HTMX Task",
            "prompt": "Do work",
            "task_type": TaskType.ONE_SHOT,
            "priority": TaskPriority.MEDIUM,
            "estimated_tokens": 0,
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert response.get("HX-Redirect") == "/"


# ── Task Detail ──


@pytest.mark.django_db
def test_task_detail_returns_200(client, task):
    response = client.get(f"/tasks/{task.pk}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_detail_partial_card(client, task):
    response = client.get(f"/tasks/{task.pk}/?partial=card")
    assert response.status_code == 200
    assert task.title.encode() in response.content


@pytest.mark.django_db
def test_task_detail_partial_panel(client, task):
    response = client.get(f"/tasks/{task.pk}/?partial=panel")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_detail_404(client):
    response = client.get("/tasks/99999/")
    assert response.status_code == 404


# ── Task Trigger ──


@pytest.mark.django_db
def test_task_trigger_creates_run(client, task):
    response = client.post(f"/tasks/{task.pk}/trigger/")
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.IN_PROGRESS
    assert TaskRun.objects.filter(task=task).exists()


@pytest.mark.django_db
def test_task_trigger_already_running(client, task):
    task.status = TaskStatus.IN_PROGRESS
    task.save()
    TaskRun.objects.create(task=task, status=TaskStatus.IN_PROGRESS)
    response = client.post(f"/tasks/{task.pk}/trigger/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_task_trigger_done_task_rejected(client, task):
    task.status = TaskStatus.DONE
    task.save()
    response = client.post(f"/tasks/{task.pk}/trigger/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_task_trigger_requires_post(client, task):
    response = client.get(f"/tasks/{task.pk}/trigger/")
    assert response.status_code == 405


# ── Task Cancel ──


@pytest.mark.django_db
def test_task_cancel_running_task(client, task):
    task.status = TaskStatus.IN_PROGRESS
    task.save()
    TaskRun.objects.create(task=task, status=TaskStatus.IN_PROGRESS)
    response = client.post(f"/tasks/{task.pk}/cancel/")
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.BACKLOG


@pytest.mark.django_db
def test_task_cancel_not_running_rejected(client, task):
    response = client.post(f"/tasks/{task.pk}/cancel/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_task_cancel_with_custom_next_status(client, task):
    task.status = TaskStatus.IN_PROGRESS
    task.save()
    response = client.post(f"/tasks/{task.pk}/cancel/", {"next_status": TaskStatus.CANCELLED})
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.CANCELLED


# ── Task Reorder ──


@pytest.mark.django_db
def test_task_reorder(client, task):
    response = client.post("/tasks/reorder/", {
        "task_id": task.pk,
        "new_status": TaskStatus.SCHEDULED,
        "new_order": 3,
    })
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.SCHEDULED
    assert task.kanban_order == 3


# ── Tmux Attach ──


@pytest.mark.django_db
def test_tmux_attach_command(client, task):
    response = client.get(f"/tasks/{task.pk}/tmux-attach/")
    assert response.status_code == 200
    data = response.json()
    assert "command" in data
    assert "tmux attach" in data["command"]


# ── Project Views ──


@pytest.mark.django_db
def test_project_list_returns_200(client, project):
    response = client.get("/projects/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_project_detail_returns_200(client, project):
    response = client.get(f"/projects/{project.slug}/")
    assert response.status_code == 200


# ── Schedule Views ──


@pytest.mark.django_db
def test_schedule_settings_returns_200(client, schedule):
    response = client.get("/scheduling/")
    assert response.status_code == 200


# ── Budget Bar ──


@pytest.mark.django_db
def test_budget_bar_returns_200(client):
    response = client.get("/budget-bar/")
    assert response.status_code == 200


# ── Provider Views ──


@pytest.mark.django_db
def test_provider_list_returns_200(client, llm_config):
    response = client.get("/providers/")
    assert response.status_code == 200
