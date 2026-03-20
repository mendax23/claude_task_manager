import asyncio
import json
import logging
import os
import shlex
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

    For claude_max providers: runs Claude Code directly in a tmux window so it
    can use tools, edit files, and run commands as a full agent.

    For API providers (anthropic, openrouter, ollama): streams LLM output via
    the provider's async API and displays via tail -f in tmux.
    """

    def __init__(self):
        self.tmux = TmuxManager()
        self.channel_layer = get_channel_layer()

    def run(self, task: Task, run: TaskRun):
        prefix = settings.AGENTQUEUE.get("TMUX_SESSION_PREFIX", "agentqueue")
        session_window = f"{prefix}:task-{task.pk}"
        output_file = f"/tmp/aq_task_{task.pk}_{run.pk}.txt"

        try:
            # --- Setup ---
            self.tmux.create_window(task.pk)
            run.tmux_session = session_window
            run.save(update_fields=["tmux_session"])
            task.tmux_session = session_window
            task.save(update_fields=["tmux_session"])

            self._broadcast_status(task, "in_progress")

            llm_config = task.get_effective_llm_config()
            if not llm_config:
                raise RuntimeError("No LLM provider configured.")

            # --- Write output file header ---
            with open(output_file, "w") as f:
                f.write(f"AgentQueue · Task #{task.pk}\n")
                f.write(f"{'─' * 60}\n")
                f.write(f"{task.title}\n")
                f.write(f"Provider: {llm_config.name}\n")
                if llm_config.provider_type == "claude_max":
                    f.write("Mode: Direct tmux execution (agent mode)\n")
                f.write(f"{'─' * 60}\n\n")

            # --- Execute based on provider type ---
            if llm_config.provider_type == "claude_max":
                output, tokens_used = self._run_in_tmux(
                    task, run, llm_config, session_window, output_file
                )
            else:
                output, tokens_used = self._run_api_provider(
                    task, llm_config, session_window, output_file
                )

            # --- Completion ---
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

            self._broadcast_status(task, "done", {"tokens_used": tokens_used})

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
            if task.task_type == "evergreen":
                task.reschedule_evergreen()
                logger.info("Evergreen task %s failed but rescheduled for %s", task.pk, task.next_run_at)
            self._broadcast_status(task, "failed")

    # ──────────────────────────────────────────────────────────────
    # Claude Max: run Claude Code directly in tmux
    # ──────────────────────────────────────────────────────────────

    def _run_in_tmux(self, task, run, llm_config, session_window, output_file):
        """
        Run Claude Code directly in a tmux window as a full agent.
        Returns (output_text, tokens_used).
        """
        cli_path = llm_config.claude_cli_path or "claude"
        repo_path = task.project.repo_path or os.path.expanduser("~")
        json_output_file = output_file.replace(".txt", ".json")

        # Write prompt to a temp file to avoid shell escaping issues
        prompt = self._build_tmux_prompt(task, llm_config)
        prompt_file = f"/tmp/aq_prompt_{task.pk}_{run.pk}.txt"
        with open(prompt_file, "w") as f:
            f.write(prompt)

        # Build the command that runs inside tmux
        cmd_parts = [f"cd {shlex.quote(repo_path)}"]

        claude_cmd = f"cat {shlex.quote(prompt_file)} | {shlex.quote(cli_path)} -p --output-format stream-json"
        if llm_config.model_name:
            claude_cmd += f" --model {shlex.quote(llm_config.model_name)}"

        # tee captures JSON for parsing; exit marker signals completion
        full_cmd = (
            f"{' && '.join(cmd_parts)} && {claude_cmd} 2>&1"
            f" | tee {shlex.quote(json_output_file)}"
            f"; echo '___AQ_EXIT_'$?'___'"
        )

        time.sleep(0.3)  # let tmux shell initialise
        self.tmux.send_command(session_window, full_cmd)

        return self._poll_tmux_completion(task, run, session_window, json_output_file)

    def _poll_tmux_completion(self, task, run, session_window, json_output_file):
        """
        Poll tmux for the exit marker while streaming parsed output to WebSocket.
        Returns (output_text, tokens_used).
        """
        from apps.scheduling.models import Schedule
        schedule = Schedule.objects.filter(is_active=True).first()
        max_hours = schedule.max_run_window_hours if schedule else 4

        start_time = time.time()
        max_wait_seconds = max_hours * 3600
        last_file_pos = 0
        collected_text = []
        total_tokens = 0

        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait_seconds:
                raise RuntimeError(f"Task timed out after {max_hours} hours in tmux")

            if not self.tmux.is_alive(session_window):
                raise RuntimeError("tmux window was killed during execution")

            # Read new JSON events from the output file
            try:
                if os.path.exists(json_output_file):
                    with open(json_output_file, "r") as f:
                        f.seek(last_file_pos)
                        new_data = f.read()
                        last_file_pos = f.tell()

                    if new_data:
                        text_chunk, tokens = self._parse_stream_json(new_data)
                        if text_chunk:
                            collected_text.append(text_chunk)
                            self._broadcast_output_chunk_sync(task.pk, text_chunk)
                        if tokens:
                            total_tokens = tokens
            except OSError:
                pass

            # Check for exit marker
            exit_code = self.tmux.check_exit_marker(session_window)
            if exit_code is not None:
                # Read any remaining data
                try:
                    if os.path.exists(json_output_file):
                        with open(json_output_file, "r") as f:
                            f.seek(last_file_pos)
                            remaining = f.read()
                        if remaining:
                            text_chunk, tokens = self._parse_stream_json(remaining)
                            if text_chunk:
                                collected_text.append(text_chunk)
                            if tokens:
                                total_tokens = tokens
                except OSError:
                    pass

                if exit_code != 0:
                    raise RuntimeError(f"Claude CLI exited with code {exit_code}")

                run.exit_code = exit_code
                run.save(update_fields=["exit_code"])
                return "".join(collected_text), total_tokens

            time.sleep(2)

    def _parse_stream_json(self, raw_data: str) -> tuple[str, int]:
        """
        Parse Claude Code stream-json output lines.
        Returns (extracted_text, tokens_used_if_final).
        """
        text_parts = []
        tokens = 0

        for line in raw_data.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "assistant":
                msg = event.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            text_parts.append(text)
                tokens = msg.get("usage", {}).get("output_tokens", tokens)
            elif event_type == "result":
                tokens = event.get("usage", {}).get("output_tokens", tokens)
                result_text = event.get("result", "")
                if result_text and isinstance(result_text, str):
                    text_parts.append(result_text)
            # Fallback: raw Anthropic SSE format
            elif event_type == "content_block_delta":
                text = event.get("delta", {}).get("text", "")
                if text:
                    text_parts.append(text)
            elif event_type == "message_delta":
                tokens = event.get("usage", {}).get("output_tokens", tokens)

        return "".join(text_parts), tokens

    def _build_tmux_prompt(self, task: Task, llm_config) -> str:
        """
        Build prompt for Claude Code running directly in tmux.
        Claude Code reads the repo itself, so we only send the task prompt
        and any system-level instructions.
        """
        parts = []
        if llm_config.system_prompt:
            parts.append(llm_config.system_prompt)
            parts.append("\n\n---\n\n")
        parts.append(task.prompt)
        return "".join(parts)

    # ──────────────────────────────────────────────────────────────
    # API providers: subprocess streaming with tail -f in tmux
    # ──────────────────────────────────────────────────────────────

    def _run_api_provider(self, task, llm_config, session_window, output_file):
        """Run an API-based provider via subprocess streaming."""
        provider = LLMProvider.from_config(llm_config)

        time.sleep(0.3)
        self.tmux.send_command(session_window, f"tail -f {output_file}")

        prompt = self._build_full_prompt(task)
        request = LLMRequest(
            messages=[LLMMessage(role="user", content=prompt)],
            max_tokens=llm_config.max_tokens,
            temperature=llm_config.temperature,
            system=llm_config.system_prompt,
            cwd=task.project.repo_path or None,
        )

        return async_to_sync(self._stream_async)(
            provider, request, output_file, task.pk
        )

    async def _stream_async(self, provider, request, output_file: str, task_id: int):
        """Stream LLM output to file and WebSocket (API providers)."""
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

    # ──────────────────────────────────────────────────────────────
    # Shared helpers
    # ──────────────────────────────────────────────────────────────

    def _broadcast_status(self, task: Task, status: str, extra: dict = None):
        if not self.channel_layer:
            return
        try:
            data = {"status": status, "title": task.title}
            if extra:
                data.update(extra)
            async_to_sync(self.channel_layer.group_send)(
                "dashboard",
                {
                    "type": "task_update",
                    "task_id": task.pk,
                    "data": data,
                },
            )
        except Exception as e:
            logger.debug("broadcast_status skipped: %s", e)

    def _broadcast_output_chunk_sync(self, task_id: int, text: str):
        if not self.channel_layer:
            return
        try:
            async_to_sync(self.channel_layer.group_send)(
                f"task-{task_id}",
                {"type": "output_chunk", "task_id": task_id, "text": text},
            )
        except Exception as e:
            logger.debug("broadcast_output_chunk skipped: %s", e)

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
        """Build prompt with full repo context (for API providers)."""
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
