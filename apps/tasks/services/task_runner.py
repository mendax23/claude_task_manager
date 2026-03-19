import asyncio
import logging
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
    Executes a task by:
    1. Creating a tmux window
    2. Building the LLM prompt (with repo context)
    3. Streaming output via the LLM provider
    4. Broadcasting output chunks to WebSocket clients
    5. Updating TaskRun status on completion
    """

    def __init__(self):
        self.tmux = TmuxManager()
        self.channel_layer = get_channel_layer()

    def run(self, task: Task, run: TaskRun):
        """Synchronous entry point called by Celery task."""
        async_to_sync(self._run_async)(task, run)

    async def _run_async(self, task: Task, run: TaskRun):
        prefix = settings.AGENTQUEUE.get("TMUX_SESSION_PREFIX", "agentqueue")
        session_window = f"{prefix}:task-{task.pk}"

        try:
            # Create tmux window
            self.tmux.create_window(task.pk)
            run.tmux_session = session_window
            run.save(update_fields=["tmux_session"])
            task.tmux_session = session_window
            task.save(update_fields=["tmux_session"])

            await self._broadcast_task_update(task, "in_progress")

            # Get provider
            llm_config = task.get_effective_llm_config()
            if not llm_config:
                raise RuntimeError("No LLM provider configured.")

            provider = LLMProvider.from_config(llm_config)

            # Build prompt with repo context
            prompt = self._build_full_prompt(task)
            request = LLMRequest(
                messages=[LLMMessage(role="user", content=prompt)],
                max_tokens=llm_config.max_tokens,
                temperature=llm_config.temperature,
                system=llm_config.system_prompt,
            )

            # Stream output
            full_output = []
            tokens_used = 0
            async for chunk in provider.stream(request):
                if chunk.text:
                    full_output.append(chunk.text)
                    await self._broadcast_output_chunk(task.pk, chunk.text)
                if chunk.is_final:
                    tokens_used = chunk.tokens_used

            # Save run results
            output = "".join(full_output)
            run.output_log = output
            run.tokens_used = tokens_used
            run.status = TaskStatus.DONE
            run.finished_at = timezone.now()
            run.save()

            # Update token budget
            await self._record_token_usage(llm_config.pk, tokens_used)

            # Update task status
            task.mark_done(summary=output[:500])

            # Handle post-completion logic
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
                    run_task.delay(next_task.pk, next_run.pk)

            await self._broadcast_task_update(task, "done")
            await self._broadcast_task_complete(task.pk)

        except Exception as e:
            logger.exception("Task %s failed: %s", task.pk, e)
            run.status = TaskStatus.FAILED
            run.error_log = str(e)
            run.finished_at = timezone.now()
            run.save()
            task.mark_failed()
            await self._broadcast_task_update(task, "failed")

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

    async def _broadcast_task_update(self, task: Task, status: str):
        await self.channel_layer.group_send(
            "dashboard",
            {
                "type": "task_update",
                "task_id": task.pk,
                "data": {"status": status, "title": task.title},
            },
        )

    async def _broadcast_output_chunk(self, task_id: int, text: str):
        await self.channel_layer.group_send(
            f"task-{task_id}",
            {"type": "output_chunk", "task_id": task_id, "text": text},
        )

    async def _broadcast_task_complete(self, task_id: int):
        await self.channel_layer.group_send(
            f"task-{task_id}",
            {"type": "task_complete", "task_id": task_id},
        )

    async def _record_token_usage(self, llm_config_id: int, tokens: int):
        if not tokens:
            return
        from asgiref.sync import sync_to_async
        from apps.scheduling.models import TokenBudget

        @sync_to_async
        def update_budget():
            TokenBudget.objects.filter(provider_id=llm_config_id).update(
                tokens_used_this_week=models.F("tokens_used_this_week") + tokens
            )

        try:
            from django.db import models
            await update_budget()
        except Exception as e:
            logger.warning("Failed to update token budget: %s", e)
