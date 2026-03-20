import asyncio
import logging
import time
from django.conf import settings
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.providers.base import LLMProvider, LLMRequest, LLMMessage
from apps.tasks.models import Task, TaskRun, TaskStatus
from .tmux_manager import TmuxManager

logger = logging.getLogger(__name__)


class TaskRunner:
    """
    Executes a task synchronously (safe to call from a thread or Celery worker).
    Only the LLM streaming loop is async — all Django ORM calls stay synchronous.
    """

    def __init__(self):
        self.tmux = TmuxManager()
        self.channel_layer = get_channel_layer()

    def run(self, task: Task, run: TaskRun):
        prefix = settings.AGENTQUEUE.get("TMUX_SESSION_PREFIX", "agentqueue")
        session_window = f"{prefix}:task-{task.pk}"
        output_file = f"/tmp/aq_task_{task.pk}_{run.pk}.txt"

        try:
            # --- Setup (all synchronous) ---
            self.tmux.create_window(task.pk)
            run.tmux_session = session_window
            run.save(update_fields=["tmux_session"])
            task.tmux_session = session_window
            task.save(update_fields=["tmux_session"])

            self._broadcast_status(task, "in_progress")

            llm_config = task.get_effective_llm_config()
            if not llm_config:
                raise RuntimeError("No LLM provider configured.")

            provider = LLMProvider.from_config(llm_config)

            with open(output_file, "w") as f:
                f.write(f"AgentQueue · Task #{task.pk}\n")
                f.write(f"{'─' * 60}\n")
                f.write(f"{task.title}\n")
                f.write(f"Provider: {llm_config.name}\n")
                f.write(f"{'─' * 60}\n\n")

            time.sleep(0.3)  # let tmux shell initialise
            self.tmux.send_command(session_window, f"tail -f {output_file}")

            prompt = self._build_full_prompt(task)
            request = LLMRequest(
                messages=[LLMMessage(role="user", content=prompt)],
                max_tokens=llm_config.max_tokens,
                temperature=llm_config.temperature,
                system=llm_config.system_prompt,
                cwd=task.project.repo_path or None,
            )

            # --- Stream (async, isolated) ---
            output, tokens_used = async_to_sync(self._stream_async)(
                provider, request, output_file, task.pk
            )

            # --- Completion (all synchronous) ---
            with open(output_file, "a") as f:
                f.write(f"\n\n{'─' * 60}\n")
                f.write(f"Done · {tokens_used:,} tokens used\n")

            run.output_log = output
            run.tokens_used = tokens_used
            run.status = TaskStatus.DONE
            run.finished_at = timezone.now()
            run.save()

            self._record_token_usage(llm_config.pk, tokens_used)
            task.mark_done(summary=output[:500])

            if task.task_type == "evergreen":
                task.reschedule_evergreen()
            elif task.task_type == "chained" and task.chain:
                task.chain.advance()
                next_task = task.chain.get_next_task()
                if next_task:
                    from apps.tasks.celery_tasks import run_task
                    next_run = TaskRun.objects.create(task=next_task)
                    next_task.status = TaskStatus.IN_PROGRESS
                    next_task.save(update_fields=["status"])
                    try:
                        run_task.delay(next_task.pk, next_run.pk)
                    except Exception:
                        import threading
                        def _run_next():
                            from django.db import close_old_connections
                            close_old_connections()
                            TaskRunner().run(next_task, next_run)
                        threading.Thread(target=_run_next, daemon=True).start()

            self._broadcast_status(task, "done")

        except Exception as e:
            logger.exception("Task %s failed: %s", task.pk, e)
            try:
                with open(output_file, "a") as f:
                    f.write(f"\n\n{'─' * 60}\n")
                    f.write(f"ERROR: {e}\n")
            except OSError:
                pass
            run.status = TaskStatus.FAILED
            run.error_log = str(e)
            run.finished_at = timezone.now()
            run.save()
            task.mark_failed()
            self._broadcast_status(task, "failed")

    async def _stream_async(self, provider, request, output_file: str, task_id: int):
        """Only async part: stream LLM output to file and WebSocket."""
        full_output = []
        tokens_used = 0
        async for chunk in provider.stream(request):
            if chunk.text:
                full_output.append(chunk.text)
                with open(output_file, "a") as f:
                    f.write(chunk.text)
                await self._broadcast_output_chunk(task_id, chunk.text)
            if chunk.is_final:
                tokens_used = chunk.tokens_used
        return "".join(full_output), tokens_used

    def _broadcast_status(self, task: Task, status: str):
        if not self.channel_layer:
            return
        try:
            async_to_sync(self.channel_layer.group_send)(
                "dashboard",
                {
                    "type": "task_update",
                    "task_id": task.pk,
                    "data": {"status": status, "title": task.title},
                },
            )
        except Exception as e:
            logger.debug("broadcast_status skipped: %s", e)

    async def _broadcast_output_chunk(self, task_id: int, text: str):
        if not self.channel_layer:
            return
        try:
            await self.channel_layer.group_send(
                f"task-{task_id}",
                {"type": "output_chunk", "task_id": task_id, "text": text},
            )
        except Exception as e:
            logger.debug("broadcast_output_chunk skipped: %s", e)

    def _record_token_usage(self, llm_config_id: int, tokens: int):
        if not tokens:
            return
        try:
            from django.db import models
            from apps.scheduling.models import TokenBudget
            TokenBudget.objects.filter(provider_id=llm_config_id).update(
                tokens_used_this_week=models.F("tokens_used_this_week") + tokens
            )
        except Exception as e:
            logger.warning("Failed to update token budget: %s", e)

    def _build_full_prompt(self, task: Task) -> str:
        parts = []
        if task.project.repo_path:
            from apps.projects.services.repo_reader import RepoReader
            try:
                ctx = RepoReader(task.project.repo_path).build_context_prompt()
                parts.append(ctx)
                parts.append("\n\n---\n\n")
            except Exception:
                pass
        parts.append(task.prompt)
        return "".join(parts)
