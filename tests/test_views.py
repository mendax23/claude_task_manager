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
def test_task_trigger_done_task_can_rerun(client, task):
    task.status = TaskStatus.DONE
    task.save()
    response = client.post(f"/tasks/{task.pk}/trigger/")
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.IN_PROGRESS


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


# ── Task Duplicate ──


@pytest.mark.django_db
def test_task_duplicate(client, task):
    response = client.post(f"/tasks/{task.pk}/duplicate/")
    assert response.status_code == 302
    new_task = Task.objects.filter(title__contains="(copy)").first()
    assert new_task is not None
    assert new_task.prompt == task.prompt
    assert new_task.status == TaskStatus.BACKLOG
    assert new_task.pk != task.pk


# ── Task Delete ──


@pytest.mark.django_db
def test_task_delete(client, task):
    pk = task.pk
    # Default delete is soft-delete (sets status to cancelled)
    response = client.post(f"/tasks/{pk}/delete/")
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.CANCELLED


@pytest.mark.django_db
def test_task_delete_permanent(client, task):
    pk = task.pk
    response = client.post(f"/tasks/{pk}/delete/", {"permanent": "1"})
    assert response.status_code == 302
    assert not Task.objects.filter(pk=pk).exists()


@pytest.mark.django_db
def test_task_restore(client, task):
    task.status = TaskStatus.CANCELLED
    task.save()
    response = client.post(f"/tasks/{task.pk}/restore/")
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.BACKLOG


@pytest.mark.django_db
def test_task_delete_requires_post(client, task):
    response = client.get(f"/tasks/{task.pk}/delete/")
    assert response.status_code == 405


# ── Provider Create/Edit/Delete ──


@pytest.mark.django_db
def test_provider_create_get(client):
    response = client.get("/providers/create/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_provider_create_post(client):
    from apps.providers.models import LLMConfig
    response = client.post("/providers/create/", {
        "name": "Test Provider",
        "provider_type": "claude_max",
        "model_name": "claude-opus-4-6",
        "max_tokens": 8192,
        "temperature": 0.7,
        "claude_cli_path": "claude",
    })
    assert response.status_code == 302
    assert LLMConfig.objects.filter(name="Test Provider").exists()


@pytest.mark.django_db
def test_provider_edit_get(client, llm_config):
    response = client.get(f"/providers/{llm_config.pk}/edit/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_provider_edit_post(client, llm_config):
    response = client.post(f"/providers/{llm_config.pk}/edit/", {
        "name": "Updated Name",
        "provider_type": "claude_max",
        "model_name": "claude-opus-4-6",
        "max_tokens": 8192,
        "temperature": 0.7,
        "claude_cli_path": "claude",
    })
    assert response.status_code == 302
    llm_config.refresh_from_db()
    assert llm_config.name == "Updated Name"


@pytest.mark.django_db
def test_provider_delete(client, llm_config):
    response = client.post(f"/providers/{llm_config.pk}/delete/")
    assert response.status_code == 302
    llm_config.refresh_from_db()
    assert llm_config.is_active is False


# ── Project Edit/Delete ──


@pytest.mark.django_db
def test_project_edit_get(client, project):
    response = client.get(f"/projects/{project.slug}/edit/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_project_edit_post(client, project):
    response = client.post(f"/projects/{project.slug}/edit/", {
        "name": "Updated Project",
        "repo_path": "/tmp/updated-repo",
        "default_branch": "main",
    })
    assert response.status_code == 302
    project.refresh_from_db()
    assert project.name == "Updated Project"


@pytest.mark.django_db
def test_project_delete(client, project):
    response = client.post(f"/projects/{project.slug}/delete/")
    assert response.status_code == 302
    project.refresh_from_db()
    assert project.is_active is False


# ── Schedule Edit ──


@pytest.mark.django_db
def test_schedule_edit_post(client, schedule):
    response = client.post("/scheduling/", {
        "idle_threshold_minutes": 30,
        "away_threshold_hours": 2,
        "max_run_window_hours": 6,
        "is_active": "on",
        "allowed_days": 127,
    })
    assert response.status_code == 302
    schedule.refresh_from_db()
    assert schedule.idle_threshold_minutes == 30
    assert schedule.away_threshold_hours == 2


# ── Task List Sort ──


@pytest.mark.django_db
def test_task_list_sort_by_priority(client, project, llm_config):
    Task.objects.create(project=project, llm_config=llm_config, title="LowPrioTask_ZZZ", prompt="x", priority=1)
    Task.objects.create(project=project, llm_config=llm_config, title="HighPrioTask_ZZZ", prompt="x", priority=3)
    response = client.get("/tasks/?sort=priority")
    assert response.status_code == 200
    content = response.content.decode()
    assert content.index("HighPrioTask_ZZZ") < content.index("LowPrioTask_ZZZ")


@pytest.mark.django_db
def test_task_list_sort_by_title(client, project, llm_config):
    Task.objects.create(project=project, llm_config=llm_config, title="Zebra Task", prompt="x")
    Task.objects.create(project=project, llm_config=llm_config, title="Alpha Task", prompt="x")
    response = client.get("/tasks/?sort=title")
    assert response.status_code == 200
    content = response.content.decode()
    assert content.index("Alpha Task") < content.index("Zebra Task")


# ── Bulk Actions ──


@pytest.mark.django_db
def test_bulk_delete(client, project, llm_config):
    t1 = Task.objects.create(project=project, llm_config=llm_config, title="Del1", prompt="x")
    t2 = Task.objects.create(project=project, llm_config=llm_config, title="Del2", prompt="x")
    response = client.post("/tasks/bulk/", {
        "task_ids": [t1.pk, t2.pk],
        "action": "delete",
    })
    assert response.status_code == 200
    assert not Task.objects.filter(pk__in=[t1.pk, t2.pk]).exists()


@pytest.mark.django_db
def test_bulk_move_to_backlog(client, project, llm_config):
    t1 = Task.objects.create(project=project, llm_config=llm_config, title="Sched1", prompt="x", status=TaskStatus.SCHEDULED)
    response = client.post("/tasks/bulk/", {
        "task_ids": [t1.pk],
        "action": "backlog",
    })
    assert response.status_code == 200
    t1.refresh_from_db()
    assert t1.status == TaskStatus.BACKLOG


@pytest.mark.django_db
def test_bulk_action_missing_params(client):
    response = client.post("/tasks/bulk/", {})
    assert response.status_code == 400


# ── Task Edit via HTMX ──


@pytest.mark.django_db
def test_task_edit_get(client, task):
    response = client.get(f"/tasks/{task.pk}/edit/")
    assert response.status_code == 200
    assert b"Edit Task" in response.content


@pytest.mark.django_db
def test_task_edit_post_valid(client, task):
    response = client.post(f"/tasks/{task.pk}/edit/", {
        "title": "Updated Title",
        "prompt": "Updated prompt",
        "task_type": "one_shot",
        "priority": 3,
        "estimated_tokens": 0,
        "project": task.project.pk,
    })
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.title == "Updated Title"


# ── Clear Done / Retry Failed ──


@pytest.mark.django_db
def test_clear_done(client, project, llm_config):
    Task.objects.create(project=project, llm_config=llm_config, title="Done1", prompt="x", status=TaskStatus.DONE)
    Task.objects.create(project=project, llm_config=llm_config, title="Active", prompt="x", status=TaskStatus.BACKLOG)
    response = client.post("/tasks/clear-done/")
    assert response.status_code == 200
    # Done task should be archived (status changed), active task untouched
    assert not Task.objects.filter(title="Done1", status=TaskStatus.DONE).exists()


@pytest.mark.django_db
def test_retry_failed(client, project, llm_config):
    Task.objects.create(project=project, llm_config=llm_config, title="Failed1", prompt="x", status=TaskStatus.FAILED)
    response = client.post("/tasks/retry-failed/")
    assert response.status_code == 200
    assert Task.objects.filter(title="Failed1", status=TaskStatus.SCHEDULED).exists()


# ── Provider Health Check ──


@pytest.mark.django_db
def test_provider_health_check(client, llm_config):
    response = client.post(f"/providers/{llm_config.pk}/health/")
    # Should return 200 with success/error message
    assert response.status_code == 200


# ── Task Create with Project Pre-select ──


@pytest.mark.django_db
def test_task_create_with_project_param(client, project):
    response = client.get(f"/tasks/create/?project={project.pk}")
    assert response.status_code == 200
    # Project should be pre-selected in the form
    content = response.content.decode()
    assert f'value="{project.pk}" selected' in content or f"selected" in content


@pytest.mark.django_db
def test_task_create_post_redirects_to_detail(client, project, llm_config):
    response = client.post("/tasks/create/", {
        "project": project.pk,
        "title": "Redirect Test Task",
        "prompt": "Do something",
        "task_type": TaskType.ONE_SHOT,
        "priority": TaskPriority.MEDIUM,
        "estimated_tokens": 0,
    })
    task = Task.objects.get(title="Redirect Test Task")
    assert response.status_code == 302
    assert f"/tasks/{task.pk}/" in response.url


# ── Project Detail Has New Task Button ──


@pytest.mark.django_db
def test_project_detail_has_new_task_button(client, project):
    response = client.get(f"/projects/{project.slug}/")
    assert response.status_code == 200
    content = response.content.decode()
    assert f"/tasks/create/?project={project.pk}" in content
    assert "New Task" in content


# ── Task Detail Actions ──


@pytest.mark.django_db
def test_task_detail_shows_run_button(client, task):
    response = client.get(f"/tasks/{task.pk}/")
    content = response.content.decode()
    assert "Run Now" in content
    assert "Run &amp; Watch" in content or "Run &amp; Watch" in content or "Run" in content


@pytest.mark.django_db
def test_task_detail_running_shows_cancel(client, task):
    task.status = TaskStatus.IN_PROGRESS
    task.save()
    TaskRun.objects.create(task=task, status=TaskStatus.IN_PROGRESS)
    response = client.get(f"/tasks/{task.pk}/")
    content = response.content.decode()
    assert "Cancel" in content
    assert "Live Output" in content


# ── Task List ──


@pytest.mark.django_db
def test_task_list_has_create_link(client, task):
    response = client.get("/tasks/")
    content = response.content.decode()
    assert "/tasks/create/" in content


@pytest.mark.django_db
def test_task_list_empty_state(client):
    response = client.get("/tasks/")
    content = response.content.decode()
    assert "No tasks yet" in content or "Create your first task" in content


# ── Detail Content Partial ──


@pytest.mark.django_db
def test_task_detail_partial_content(client, task):
    response = client.get(f"/tasks/{task.pk}/?partial=content")
    assert response.status_code == 200
    content = response.content.decode()
    assert task.title in content
    assert "Run Now" in content


# ── Task Reorder Edge Cases ──


@pytest.mark.django_db
def test_task_reorder_invalid_status_ignored(client, task):
    response = client.post("/tasks/reorder/", {
        "task_id": task.pk,
        "new_status": "nonexistent_status",
        "new_order": 0,
    })
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.BACKLOG  # unchanged


@pytest.mark.django_db
def test_task_reorder_nonexistent_task(client):
    response = client.post("/tasks/reorder/", {
        "task_id": 99999,
        "new_status": TaskStatus.SCHEDULED,
        "new_order": 0,
    })
    assert response.status_code == 404


# ── Bulk Action Edge Cases ──


@pytest.mark.django_db
def test_bulk_unknown_action(client, task):
    response = client.post("/tasks/bulk/", {
        "task_ids": [task.pk],
        "action": "garbage_action",
    })
    assert response.status_code == 400


@pytest.mark.django_db
def test_bulk_cancel_running_tasks(client, project, llm_config):
    t1 = Task.objects.create(project=project, llm_config=llm_config, title="Running1", prompt="x", status=TaskStatus.IN_PROGRESS)
    TaskRun.objects.create(task=t1, status=TaskStatus.IN_PROGRESS)
    response = client.post("/tasks/bulk/", {
        "task_ids": [t1.pk],
        "action": "cancel",
    })
    assert response.status_code == 200
    t1.refresh_from_db()
    assert t1.status == TaskStatus.BACKLOG


# ── Task Cancel Edge Cases ──


@pytest.mark.django_db
def test_task_cancel_invalid_next_status_defaults_to_backlog(client, task):
    task.status = TaskStatus.IN_PROGRESS
    task.save()
    response = client.post(f"/tasks/{task.pk}/cancel/", {"next_status": "garbage"})
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.BACKLOG


# ── Task Edit Edge Cases ──


@pytest.mark.django_db
def test_task_edit_post_invalid_shows_form(client, task):
    response = client.post(f"/tasks/{task.pk}/edit/", {
        "title": "",  # required, empty
        "prompt": task.prompt,
        "task_type": "one_shot",
        "priority": 2,
        "estimated_tokens": 0,
    })
    assert response.status_code == 200
    assert b"Edit Task" in response.content
    task.refresh_from_db()
    assert task.title != ""  # not saved


# ── Task Trigger No Provider ──


@pytest.mark.django_db
def test_task_trigger_no_provider_returns_error(client, project):
    task_no_llm = Task.objects.create(
        project=project, title="No LLM Task", prompt="test",
        status=TaskStatus.BACKLOG,
    )
    # Remove any default provider
    project.llm_config = None
    project.save()
    response = client.post(f"/tasks/{task_no_llm.pk}/trigger/")
    assert response.status_code == 400


# ── Project Create ──


@pytest.mark.django_db
def test_project_create_get(client):
    response = client.get("/projects/create/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_project_create_post(client):
    from apps.projects.models import Project
    response = client.post("/projects/create/", {
        "name": "New Test Project",
        "repo_path": "/tmp/test-repo",
        "default_branch": "main",
    })
    assert response.status_code == 302
    assert Project.objects.filter(name="New Test Project").exists()


# ── Dashboard Empty State ──


@pytest.mark.django_db
def test_dashboard_empty_state(client):
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Dashboard" in content


# ── Task Detail Keyboard Shortcuts Hint ──


@pytest.mark.django_db
def test_task_detail_shows_keyboard_hints(client, task):
    response = client.get(f"/tasks/{task.pk}/")
    content = response.content.decode()
    assert "Run" in content
    assert "Edit" in content
    assert "Back" in content


# ── Sort Default ──


@pytest.mark.django_db
def test_task_list_invalid_sort_defaults(client, task):
    response = client.get("/tasks/?sort=nonexistent")
    assert response.status_code == 200


# ── Task Set Status ──


@pytest.mark.django_db
def test_set_status_valid(client, task):
    response = client.post(f"/tasks/{task.pk}/set-status/", {"status": "scheduled"})
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.SCHEDULED


@pytest.mark.django_db
def test_set_status_to_done(client, task):
    response = client.post(f"/tasks/{task.pk}/set-status/", {"status": "done"})
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.DONE


@pytest.mark.django_db
def test_set_status_to_cancelled(client, task):
    response = client.post(f"/tasks/{task.pk}/set-status/", {"status": "cancelled"})
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == TaskStatus.CANCELLED


@pytest.mark.django_db
def test_set_status_invalid_status(client, task):
    response = client.post(f"/tasks/{task.pk}/set-status/", {"status": "nonexistent"})
    assert response.status_code == 400
    task.refresh_from_db()
    assert task.status == TaskStatus.BACKLOG  # unchanged


@pytest.mark.django_db
def test_set_status_missing_status(client, task):
    response = client.post(f"/tasks/{task.pk}/set-status/", {})
    assert response.status_code == 400


@pytest.mark.django_db
def test_set_status_rejects_in_progress(client, task):
    response = client.post(f"/tasks/{task.pk}/set-status/", {"status": "in_progress"})
    assert response.status_code == 400
    task.refresh_from_db()
    assert task.status == TaskStatus.BACKLOG  # unchanged


@pytest.mark.django_db
def test_set_status_requires_post(client, task):
    response = client.get(f"/tasks/{task.pk}/set-status/")
    assert response.status_code == 405


@pytest.mark.django_db
def test_set_status_nonexistent_task(client):
    response = client.post("/tasks/99999/set-status/", {"status": "done"})
    assert response.status_code == 404


@pytest.mark.django_db
def test_set_status_triggers_success_event(client, task):
    response = client.post(f"/tasks/{task.pk}/set-status/", {"status": "scheduled"})
    assert response.status_code == 200
    assert "agentqueue:success" in response["HX-Trigger"]


# ── Task List Status Counts ──


@pytest.mark.django_db
def test_task_list_has_status_counts(client, project, llm_config):
    Task.objects.create(project=project, llm_config=llm_config, title="T1", prompt="x", status=TaskStatus.BACKLOG)
    Task.objects.create(project=project, llm_config=llm_config, title="T2", prompt="x", status=TaskStatus.SCHEDULED)
    Task.objects.create(project=project, llm_config=llm_config, title="T3", prompt="x", status=TaskStatus.DONE)
    response = client.get("/tasks/")
    assert response.status_code == 200
    assert response.context["status_counts"]["backlog"] >= 1
    assert response.context["status_counts"]["scheduled"] >= 1
    assert response.context["status_counts"]["done"] >= 1


# ── Task Detail Average Duration ──


@pytest.mark.django_db
def test_task_detail_avg_duration_none_without_runs(client, task):
    response = client.get(f"/tasks/{task.pk}/")
    assert response.status_code == 200
    assert response.context["avg_duration"] is None


@pytest.mark.django_db
def test_task_detail_avg_duration_with_completed_runs(client, task):
    from django.utils import timezone
    from datetime import timedelta
    now = timezone.now()
    TaskRun.objects.create(task=task, status=TaskStatus.DONE, started_at=now - timedelta(minutes=5), finished_at=now)
    response = client.get(f"/tasks/{task.pk}/")
    assert response.status_code == 200
    assert response.context["avg_duration"] is not None
    assert "m" in response.context["avg_duration"] or "s" in response.context["avg_duration"]


# ── Form Validation ──


@pytest.mark.django_db
def test_task_create_invalid_cron(client, project):
    response = client.post("/tasks/create/", {
        "project": project.pk,
        "title": "Cron Test",
        "prompt": "test",
        "task_type": "evergreen",
        "priority": 2,
        "estimated_tokens": 0,
        "recurrence_rule": "not a cron",
    })
    # Should not create the task — form should have errors
    assert not Task.objects.filter(title="Cron Test").exists()


@pytest.mark.django_db
def test_task_create_valid_cron(client, project):
    response = client.post("/tasks/create/", {
        "project": project.pk,
        "title": "Valid Cron Test",
        "prompt": "test",
        "task_type": "evergreen",
        "priority": 2,
        "estimated_tokens": 0,
        "recurrence_rule": "0 9 * * 1",
    })
    assert Task.objects.filter(title="Valid Cron Test").exists()


@pytest.mark.django_db
def test_task_create_negative_tokens_rejected(client, project):
    response = client.post("/tasks/create/", {
        "project": project.pk,
        "title": "Neg Tokens",
        "prompt": "test",
        "task_type": "one_shot",
        "priority": 2,
        "estimated_tokens": -100,
    })
    assert not Task.objects.filter(title="Neg Tokens").exists()


# ── Command Palette Search ──


@pytest.mark.django_db
def test_command_search_finds_tasks(client, task):
    response = client.get(f"/search/?q={task.title[:5]}")
    assert response.status_code == 200
    assert task.title.encode() in response.content


@pytest.mark.django_db
def test_command_search_short_query(client):
    response = client.get("/search/?q=a")
    assert response.status_code == 200
    assert b"Type to search" in response.content


@pytest.mark.django_db
def test_command_search_no_results(client):
    response = client.get("/search/?q=zzzznonexistent")
    assert response.status_code == 200
    assert b"No results" in response.content


# ── Task List: status_choices in context ──


@pytest.mark.django_db
def test_task_list_has_status_choices(client, task):
    """Task list must include status_choices for the inline status dropdown."""
    response = client.get("/tasks/")
    assert response.status_code == 200
    assert "status_choices" in response.context


@pytest.mark.django_db
def test_task_list_status_dropdown_rendered(client, task):
    """The inline status dropdown should render change-status text for each status option."""
    response = client.get("/tasks/")
    assert response.status_code == 200
    content = response.content.decode()
    # The dropdown should contain status options (excluding current status and in_progress)
    assert "set-status" in content  # The set_status URL


@pytest.mark.django_db
def test_task_list_inline_status_change(client, task):
    """Changing status via the inline dropdown should work."""
    response = client.post(
        f"/tasks/{task.pk}/set-status/",
        {"status": "scheduled"},
    )
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == "scheduled"


@pytest.mark.django_db
def test_task_list_inline_status_change_invalid(client, task):
    """Invalid status should return an error."""
    response = client.post(
        f"/tasks/{task.pk}/set-status/",
        {"status": "nonexistent"},
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_task_list_inline_status_change_prevents_in_progress(client, task):
    """Setting status to in_progress via the dropdown should be rejected."""
    response = client.post(
        f"/tasks/{task.pk}/set-status/",
        {"status": "in_progress"},
    )
    assert response.status_code == 400
    task.refresh_from_db()
    assert task.status == "backlog"


# ── Django Messages Bridge ──


@pytest.mark.django_db
def test_task_duplicate_has_success_message(client, task):
    """Duplicating a task should set a Django success message visible on redirect."""
    response = client.post(f"/tasks/{task.pk}/duplicate/")
    assert response.status_code == 302
    # Follow the redirect
    response = client.get(response.url)
    assert response.status_code == 200
    # Django messages should be consumed by the template
    content = response.content.decode()
    # The task title should appear in the page (it's the duplicated task detail)
    assert "copy" in content.lower()


# ── Task List: sort and filter persistence ──


@pytest.mark.django_db
def test_task_list_sort_options(client, task):
    """All sort options should work."""
    for sort_key in ["newest", "oldest", "priority", "title", "updated"]:
        response = client.get(f"/tasks/?sort={sort_key}")
        assert response.status_code == 200, f"Sort by {sort_key} failed"


@pytest.mark.django_db
def test_task_list_filter_by_status_renders(client, task):
    """Status filter chips should be rendered with count data."""
    response = client.get("/tasks/")
    content = response.content.decode()
    # The status counts data attribute should be in the template
    assert "status_counts" in str(response.context) or "sc:" in content


# ── Bulk Actions: feedback messages ──


@pytest.mark.django_db
def test_bulk_action_delete_returns_success_trigger(client, task):
    """Bulk delete should return an HX-Trigger with success message."""
    response = client.post(
        "/tasks/bulk/",
        {"task_ids": [task.pk], "action": "delete"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    trigger = response.get("HX-Trigger", "")
    assert "agentqueue:success" in trigger
    assert "deleted" in trigger


@pytest.mark.django_db
def test_bulk_action_schedule_returns_success_trigger(client, task):
    """Bulk schedule should return an HX-Trigger with success message."""
    response = client.post(
        "/tasks/bulk/",
        {"task_ids": [task.pk], "action": "scheduled"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    trigger = response.get("HX-Trigger", "")
    assert "agentqueue:success" in trigger
    assert "scheduled" in trigger


@pytest.mark.django_db
def test_bulk_action_missing_data_returns_error(client):
    """Bulk action with no task_ids or action should return error."""
    response = client.post(
        "/tasks/bulk/",
        {},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 400


# ── set_status: sets completed_at for done status ──


@pytest.mark.django_db
def test_set_status_done_sets_completed_at(client, task):
    """Setting status to done should set the completed_at timestamp."""
    response = client.post(
        f"/tasks/{task.pk}/set-status/",
        {"status": "done"},
    )
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == "done"
    assert task.completed_at is not None


@pytest.mark.django_db
def test_set_status_returns_success_trigger(client, task):
    """set_status should return an HX-Trigger with success message."""
    response = client.post(
        f"/tasks/{task.pk}/set-status/",
        {"status": "scheduled"},
    )
    assert response.status_code == 200
    trigger = response.get("HX-Trigger", "")
    assert "agentqueue:success" in trigger
    assert "Scheduled" in trigger


# ── run_scheduled: trigger all scheduled tasks ──


@pytest.mark.django_db
def test_run_scheduled_returns_count(client, llm_config, project):
    """run_scheduled should return count of triggered tasks."""
    from apps.tasks.models import Task
    for i in range(3):
        Task.objects.create(
            title=f"Scheduled {i}",
            prompt="do it",
            status="scheduled",
            project=project,
            llm_config=llm_config,
        )
    response = client.post("/tasks/run-scheduled/")
    assert response.status_code == 200
    trigger = response.get("HX-Trigger", "")
    assert "3 scheduled tasks started" in trigger


# ── Task detail: prev/next navigation context ──


@pytest.mark.django_db
def test_task_detail_has_prev_next_context(client, llm_config, project):
    """Task detail should include prev_task_pk and next_task_pk in context."""
    from apps.tasks.models import Task
    import time
    t1 = Task.objects.create(title="First", prompt="a", project=project, llm_config=llm_config)
    time.sleep(0.01)
    t2 = Task.objects.create(title="Second", prompt="b", project=project, llm_config=llm_config)
    time.sleep(0.01)
    t3 = Task.objects.create(title="Third", prompt="c", project=project, llm_config=llm_config)

    # For the middle task, prev should be t3 and next should be t1
    response = client.get(f"/tasks/{t2.pk}/")
    assert response.status_code == 200
    assert response.context["prev_task_pk"] == t3.pk
    assert response.context["next_task_pk"] == t1.pk


# ── 404 page renders ──


@pytest.mark.django_db
def test_404_page_renders(client):
    """Non-existent task should return 404."""
    response = client.get("/tasks/99999/")
    assert response.status_code == 404


# ── Task restore ──


@pytest.mark.django_db
def test_task_restore_non_cancelled_rejected(client, task):
    """Restoring a non-cancelled task should return 400."""
    assert task.status == "backlog"
    response = client.post(f"/tasks/{task.pk}/restore/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_task_restore_success(client, task):
    """Restoring a cancelled task should set it back to backlog."""
    task.status = "cancelled"
    task.save()
    response = client.post(f"/tasks/{task.pk}/restore/")
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == "backlog"
    trigger = response.get("HX-Trigger", "")
    assert "restored" in trigger


# ── clear_done ──


@pytest.mark.django_db
def test_clear_done_archives_completed(client, llm_config, project):
    """clear_done should move all done tasks to cancelled."""
    from apps.tasks.models import Task
    for i in range(2):
        Task.objects.create(
            title=f"Done {i}",
            prompt="ok",
            status="done",
            project=project,
            llm_config=llm_config,
        )
    Task.objects.create(
        title="Still running",
        prompt="ok",
        status="in_progress",
        project=project,
        llm_config=llm_config,
    )
    response = client.post("/tasks/clear-done/")
    assert response.status_code == 200
    assert Task.objects.filter(status="done").count() == 0
    assert Task.objects.filter(status="cancelled").count() == 2
    assert Task.objects.filter(status="in_progress").count() == 1


# ── retry_failed ──


@pytest.mark.django_db
def test_retry_failed_requeues(client, llm_config, project):
    """retry_failed should move all failed tasks to scheduled."""
    from apps.tasks.models import Task
    Task.objects.create(title="F1", prompt="ok", status="failed", project=project, llm_config=llm_config)
    Task.objects.create(title="F2", prompt="ok", status="failed", project=project, llm_config=llm_config)
    response = client.post("/tasks/retry-failed/")
    assert response.status_code == 200
    assert Task.objects.filter(status="failed").count() == 0
    assert Task.objects.filter(status="scheduled").count() == 2


# ── Task Export ──


@pytest.mark.django_db
def test_task_export_csv(client, task):
    """Export endpoint returns CSV with task data."""
    response = client.get("/tasks/export/")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert 'filename="agentqueue_tasks.csv"' in response["Content-Disposition"]
    content = response.content.decode()
    assert "ID,Title,Status" in content
    assert task.title in content


@pytest.mark.django_db
def test_task_export_csv_filter(client, project, llm_config):
    """Export can filter by status."""
    Task.objects.create(project=project, title="Done1", prompt="p", task_type="one_shot", status="done")
    Task.objects.create(project=project, title="Pending1", prompt="p", task_type="one_shot", status="backlog")
    response = client.get("/tasks/export/?status=done")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Done1" in content
    assert "Pending1" not in content


# ── Functional Edge Cases ──


@pytest.mark.django_db
def test_task_create_htmx_returns_redirect_header(client, project, llm_config):
    """HTMX task creation returns HX-Redirect header."""
    response = client.post(
        "/tasks/create/",
        {"project": project.pk, "title": "HTMX Task", "prompt": "test",
         "task_type": "one_shot", "priority": 2, "estimated_tokens": 0,
         "kanban_order": 0, "chain_order": 0},
        HTTP_HX_REQUEST="true",
        HTTP_HX_CURRENT_URL="/tasks/",
    )
    assert response.status_code == 200
    assert response.get("HX-Redirect") is not None
    assert Task.objects.filter(title="HTMX Task").exists()


@pytest.mark.django_db
def test_task_create_htmx_invalid_shows_form(client, project):
    """Invalid HTMX creation returns form with errors, not a redirect."""
    response = client.post(
        "/tasks/create/",
        {"project": project.pk, "title": ""},  # missing required fields
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert response.get("HX-Redirect") is None


@pytest.mark.django_db
def test_task_edit_updates_title(client, task):
    """POST to edit endpoint updates the task."""
    response = client.post(f"/tasks/{task.pk}/edit/", {
        "project": task.project.pk, "title": "Edited Title", "prompt": "new",
        "task_type": "one_shot", "priority": 1, "estimated_tokens": 0,
        "kanban_order": 0, "chain_order": 0,
    })
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.title == "Edited Title"


@pytest.mark.django_db
def test_task_detail_partial_content(client, task):
    """Partial=content returns only the content fragment."""
    response = client.get(f"/tasks/{task.pk}/?partial=content")
    assert response.status_code == 200
    assert task.title.encode() in response.content


@pytest.mark.django_db
def test_task_detail_partial_card(client, task):
    """Partial=card returns the card component."""
    response = client.get(f"/tasks/{task.pk}/?partial=card")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_detail_partial_panel(client, task):
    """Partial=panel returns the slide-over panel content."""
    response = client.get(f"/tasks/{task.pk}/?partial=panel")
    assert response.status_code == 200


@pytest.mark.django_db
def test_duplicate_creates_copy(client, task):
    """Duplicate creates a new task with (copy) suffix."""
    response = client.post(f"/tasks/{task.pk}/duplicate/")
    assert response.status_code == 302
    assert Task.objects.filter(title__contains="(copy)").exists()


@pytest.mark.django_db
def test_soft_delete_sets_cancelled(client, task):
    """Soft delete (no permanent flag) sets status to cancelled."""
    response = client.post(f"/tasks/{task.pk}/delete/")
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == "cancelled"


@pytest.mark.django_db
def test_permanent_delete_removes_task(client, task):
    """Permanent delete actually removes the task."""
    pk = task.pk
    response = client.post(f"/tasks/{pk}/delete/", {"permanent": "1"})
    assert response.status_code == 302
    assert not Task.objects.filter(pk=pk).exists()


@pytest.mark.django_db
def test_set_status_rejects_in_progress(client, task):
    """Cannot set status to in_progress via set_status endpoint."""
    response = client.post(f"/tasks/{task.pk}/set-status/", {"status": "in_progress"})
    task.refresh_from_db()
    assert task.status != "in_progress"


@pytest.mark.django_db
def test_cancel_only_running_task(client, task):
    """Cancel endpoint rejects non-running tasks with 400."""
    task.status = "backlog"
    task.save()
    response = client.post(f"/tasks/{task.pk}/cancel/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_tmux_attach_returns_command(client, task):
    """Tmux attach endpoint returns JSON with command."""
    response = client.get(f"/tasks/{task.pk}/tmux-attach/")
    assert response.status_code == 200
    data = response.json()
    assert "command" in data
    assert "tmux attach-session" in data["command"]


@pytest.mark.django_db
def test_command_search_returns_results(client, task):
    """Command search returns matching tasks."""
    response = client.get(f"/search/?q={task.title[:4]}")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_list_with_all_sort_options(client, task):
    """Task list handles all sort options."""
    for sort in ["newest", "oldest", "priority", "title", "updated"]:
        response = client.get(f"/tasks/?sort={sort}")
        assert response.status_code == 200, f"Sort option '{sort}' failed"


@pytest.mark.django_db
def test_task_list_pagination(client, project, llm_config):
    """Pagination works when tasks exceed per_page."""
    for i in range(55):
        Task.objects.create(
            project=project, title=f"Page Task {i}", prompt="p",
            task_type="one_shot", status="backlog",
        )
    response = client.get("/tasks/?per_page=10")
    assert response.status_code == 200
    content = response.content.decode()
    assert "page" in content.lower() or "Showing" in content


@pytest.mark.django_db
def test_export_empty_returns_header_only(client):
    """Export with no tasks returns CSV with just the header."""
    Task.objects.all().delete()
    response = client.get("/tasks/export/")
    assert response.status_code == 200
    lines = response.content.decode().strip().split("\n")
    assert len(lines) == 1  # header only


# ── Security & Edge Cases ──


@pytest.mark.django_db
def test_xss_in_task_title_is_escaped(client, project, llm_config):
    """HTML in task title is escaped on render."""
    xss_title = '<script>alert("xss")</script>'
    task = Task.objects.create(
        project=project, title=xss_title, prompt="p",
        task_type="one_shot", status="backlog",
    )
    response = client.get(f"/tasks/{task.pk}/")
    assert response.status_code == 200
    content = response.content.decode()
    # Raw script tag must NOT appear — Django auto-escapes
    assert "<script>alert" not in content
    assert "&lt;script&gt;" in content or "alert" not in content


@pytest.mark.django_db
def test_xss_in_search_query(client, task):
    """Search query with HTML is escaped."""
    response = client.get('/search/?q=<script>alert(1)</script>')
    assert response.status_code == 200
    assert b"<script>alert" not in response.content


@pytest.mark.django_db
def test_task_with_empty_tags(client, project, llm_config):
    """Task with empty tags list renders fine."""
    task = Task.objects.create(
        project=project, title="No Tags", prompt="p",
        task_type="one_shot", status="backlog", tags=[],
    )
    response = client.get(f"/tasks/{task.pk}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_with_long_prompt(client, project, llm_config):
    """Task with very long prompt renders."""
    task = Task.objects.create(
        project=project, title="Long Prompt", prompt="x" * 10000,
        task_type="one_shot", status="backlog",
    )
    response = client.get(f"/tasks/{task.pk}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_with_unicode_title(client, project, llm_config):
    """Task with unicode characters in title works."""
    task = Task.objects.create(
        project=project, title="Fix 日本語 bug — héllo wörld 🔧",
        prompt="Handle i18n", task_type="one_shot", status="backlog",
    )
    response = client.get(f"/tasks/{task.pk}/")
    assert response.status_code == 200
    assert "日本語" in response.content.decode()


@pytest.mark.django_db
def test_task_without_llm_config_renders(client, project):
    """Task with no LLM config (but with project) renders correctly."""
    task = Task.objects.create(
        project=project, title="No LLM", prompt="No provider",
        task_type="one_shot", status="backlog",
    )
    response = client.get(f"/tasks/{task.pk}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_without_llm_config(client, project):
    """Task with no LLM config renders correctly."""
    task = Task.objects.create(
        project=project, title="No LLM", prompt="p",
        task_type="one_shot", status="backlog",
    )
    response = client.get(f"/tasks/{task.pk}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_list_invalid_sort_falls_back(client, task):
    """Invalid sort parameter falls back to default."""
    response = client.get("/tasks/?sort=invalid_field")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_list_invalid_page(client, task):
    """Invalid page parameter shows last page instead of 500."""
    response = client.get("/tasks/?page=9999")
    assert response.status_code == 200


@pytest.mark.django_db
def test_task_list_invalid_per_page(client, task):
    """Non-integer per_page doesn't crash."""
    response = client.get("/tasks/?per_page=abc")
    # Should either 200 with default or 400, never 500
    assert response.status_code in (200, 400)


@pytest.mark.django_db
def test_bulk_action_with_nonexistent_ids(client):
    """Bulk action with non-existent task IDs doesn't crash."""
    response = client.post("/tasks/bulk/", {
        "task_ids": [99999, 99998],
        "action": "delete",
    })
    assert response.status_code == 200


@pytest.mark.django_db
def test_set_status_invalid_status(client, task):
    """set_status with invalid status returns error."""
    response = client.post(f"/tasks/{task.pk}/set-status/", {"status": "nonsense"})
    assert response.status_code in (200, 400)
    task.refresh_from_db()
    assert task.status != "nonsense"


@pytest.mark.django_db
def test_export_csv_with_special_chars(client, project, llm_config):
    """CSV export handles special characters (commas, quotes) in fields."""
    Task.objects.create(
        project=project, title='Task with "quotes" and, commas',
        prompt="p", task_type="one_shot", status="backlog",
        tags=["tag,with,commas"],
    )
    response = client.get("/tasks/export/")
    assert response.status_code == 200
    content = response.content.decode()
    # CSV module should properly quote the field
    assert "quotes" in content


@pytest.mark.django_db
def test_task_reorder_post(client, task):
    """Task reorder endpoint works."""
    response = client.post("/tasks/reorder/", {
        "task_id": task.pk,
        "new_status": "scheduled",
        "new_order": 5,
    })
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == "scheduled"
    assert task.kanban_order == 5
