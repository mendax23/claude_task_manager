import json
import logging
import os
from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def run_task(self, task_id: int, run_id: int):
    """Execute a single task via the TaskRunner."""
    from apps.tasks.models import Task, TaskRun, TaskStatus
    from apps.tasks.services.task_runner import TaskRunner

    try:
        task = Task.objects.select_related("project", "llm_config").get(pk=task_id)
        run = TaskRun.objects.get(pk=run_id)

        # Guard: don't re-execute if already finished (e.g. Celery re-delivery)
        if run.status != TaskStatus.IN_PROGRESS:
            logger.warning(
                "Run %s for task %s already %s — skipping",
                run_id, task_id, run.status,
            )
            return

        run.celery_task_id = self.request.id
        run.save(update_fields=["celery_task_id"])

        TaskRunner().run(task, run)

    except Task.DoesNotExist:
        logger.error("Task %s not found", task_id)
    except TaskRun.DoesNotExist:
        logger.error("TaskRun %s not found", run_id)
    except Exception as exc:
        logger.exception("Task %s execution error: %s", task_id, exc)
        # Only retry for infrastructure errors (DB, network).
        # TaskRunner handles its own errors internally, so if we get here
        # it's likely a setup issue worth retrying.
        raise self.retry(exc=exc, countdown=60)


@shared_task
def schedule_evergreen_tasks():
    """Move evergreen tasks whose next_run_at has arrived to SCHEDULED.
    Picks up tasks in BACKLOG, DONE, or FAILED — so completed evergreens
    stay visible in Done until their next cron time arrives."""
    from apps.tasks.models import Task, TaskStatus

    eligible = [TaskStatus.BACKLOG, TaskStatus.DONE, TaskStatus.FAILED]
    tasks = Task.objects.filter(
        task_type="evergreen",
        status__in=eligible,
        next_run_at__lte=timezone.now(),
        recurrence_rule__gt="",
    )
    count = tasks.update(status=TaskStatus.SCHEDULED)
    if count:
        logger.info("Scheduled %d evergreen tasks", count)


@shared_task
def advance_chains():
    """Check for chains where current step is done, trigger next step."""
    from apps.tasks.models import TaskChain, Task, TaskRun, TaskStatus

    chains = TaskChain.objects.filter(status=TaskStatus.IN_PROGRESS)
    for chain in chains:
        with transaction.atomic():
            chain = TaskChain.objects.select_for_update().get(pk=chain.pk)
            if chain.status != TaskStatus.IN_PROGRESS:
                continue
            current_tasks = chain.tasks.filter(chain_order=chain.current_step)
            if current_tasks.exists() and all(t.status == TaskStatus.DONE for t in current_tasks):
                chain.advance()
                next_task = chain.get_next_task()
                if next_task:
                    next_run = TaskRun.objects.create(task=next_task)
                    next_task.status = TaskStatus.IN_PROGRESS
                    next_task.save(update_fields=["status"])
                    run_task.delay(next_task.pk, next_run.pk)
                else:
                    chain.status = TaskStatus.DONE
                    chain.save(update_fields=["status"])


# ──────────────────────────────────────────────────────────────
# Zombie task recovery
# ──────────────────────────────────────────────────────────────

STALE_THRESHOLD_SECONDS = 300  # 5 minutes without tmux = stale


@shared_task
def recover_stale_tasks():
    """
    Periodic watchdog: detects tasks stuck in IN_PROGRESS whose Celery
    worker died, and recovers them by inspecting tmux state and output files.

    Should run every 2-3 minutes via Celery Beat.
    """
    from apps.tasks.models import TaskRun, TaskStatus
    from apps.tasks.services.tmux_manager import TmuxManager

    tmux = TmuxManager()
    stale_runs = TaskRun.objects.filter(
        status=TaskStatus.IN_PROGRESS,
    ).select_related("task", "task__project", "task__llm_config")

    for run in stale_runs:
        try:
            _try_recover_run(run, tmux)
        except Exception:
            logger.exception("Error recovering run %s", run.pk)


def _try_recover_run(run, tmux):
    """Attempt to recover a single in-progress run."""
    from apps.tasks.models import TaskStatus

    task = run.task
    json_file = f"/tmp/aq_task_{task.pk}_{run.pk}.json"

    # 1. Check JSON output file for a result event (most reliable signal)
    result_event = _find_result_event(json_file)
    if result_event:
        _finish_recovered_run(run, task, result_event)
        logger.info(
            "Recovered task %s (run %s) from output file", task.pk, run.pk
        )
        return

    # 2. Check tmux state
    session_window = run.tmux_session
    if session_window and tmux.is_alive(session_window):
        # Window alive — check exit marker (Claude finished but result not in file yet?)
        exit_code = tmux.check_exit_marker(session_window)
        if exit_code is not None:
            # Re-read file in case it was flushed after marker appeared
            result_event = _find_result_event(json_file)
            if result_event:
                _finish_recovered_run(run, task, result_event)
            elif exit_code == 0:
                _mark_run_done(run, task, "Recovered: completed with exit code 0")
            else:
                _mark_run_failed(
                    run, task, f"Recovered: Claude CLI exited with code {exit_code}"
                )
            logger.info(
                "Recovered task %s via exit marker (code %s)", task.pk, exit_code
            )
            return

        # No exit marker found — check if the pane is idle (shell prompt, no process)
        # This catches the case where exit marker scrolled out of scrollback
        if tmux.is_pane_idle(session_window):
            # Process finished but marker lost — try output file one more time
            result_event = _find_result_event(json_file)
            if result_event:
                _finish_recovered_run(run, task, result_event)
                logger.info("Recovered task %s via idle pane + output file", task.pk)
            else:
                _mark_run_done(run, task, "Recovered: process finished (no output captured)")
                logger.info("Recovered task %s via idle pane detection", task.pk)
            return

        # tmux alive and process running — do nothing
        return

    # 3. tmux dead, no result file — mark as failed if stale enough
    elapsed = (timezone.now() - run.started_at).total_seconds()
    if elapsed > STALE_THRESHOLD_SECONDS:
        _mark_run_failed(
            run, task, "Recovery: tmux session lost, no completion data found"
        )
        logger.warning(
            "Marked stale task %s (run %s) as failed — tmux lost, no output",
            task.pk, run.pk,
        )


def _find_result_event(json_file: str) -> dict | None:
    """Parse a Claude Code stream-json file and return the result event if present."""
    if not os.path.exists(json_file):
        return None
    try:
        with open(json_file, "r") as f:
            content = f.read()
        # Result event is always last — scan from end for efficiency
        for line in reversed(content.strip().split("\n")):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "result":
                    return event
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return None


def _finish_recovered_run(run, task, result_event: dict):
    """Mark a run as completed using data extracted from a result event."""
    from apps.tasks.models import TaskStatus

    is_error = result_event.get("is_error", False)
    result_text = result_event.get("result", "")
    usage = result_event.get("usage", {})
    tokens = usage.get("output_tokens", 0)

    run.finished_at = timezone.now()
    run.output_log = result_text[:5000] if result_text else ""
    run.tokens_used = tokens

    if is_error:
        run.status = TaskStatus.FAILED
        run.error_log = result_text[:2000] if result_text else "Claude Code error"
        run.save()
        task.mark_failed()
    else:
        run.status = TaskStatus.DONE
        run.exit_code = 0
        run.save()
        task.mark_done(summary=result_text[:500] if result_text else "Recovered")

    # Reschedule evergreen tasks even after recovery
    if task.task_type == "evergreen":
        task.reschedule_evergreen()

    _broadcast_recovery(task, "done" if not is_error else "failed", tokens)


def _mark_run_done(run, task, summary: str):
    """Mark a run as done without a result event."""
    from apps.tasks.models import TaskStatus

    run.status = TaskStatus.DONE
    run.exit_code = 0
    run.finished_at = timezone.now()
    run.output_log = summary
    run.save()
    task.mark_done(summary=summary)

    if task.task_type == "evergreen":
        task.reschedule_evergreen()

    _broadcast_recovery(task, "done", 0)


def _mark_run_failed(run, task, error_msg: str):
    """Mark a run as failed."""
    from apps.tasks.models import TaskStatus

    run.status = TaskStatus.FAILED
    run.error_log = error_msg
    run.finished_at = timezone.now()
    run.save()
    task.mark_failed()

    if task.task_type == "evergreen":
        task.reschedule_evergreen()

    _broadcast_recovery(task, "failed", 0)


def _broadcast_recovery(task, status: str, tokens: int):
    """Broadcast status update to dashboard WebSocket after recovery."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if channel_layer:
            data = {"status": status, "title": task.title}
            if tokens:
                data["tokens_used"] = tokens
            async_to_sync(channel_layer.group_send)(
                "dashboard",
                {"type": "task_update", "task_id": task.pk, "data": data},
            )
    except Exception as e:
        logger.debug("Recovery broadcast skipped: %s", e)
