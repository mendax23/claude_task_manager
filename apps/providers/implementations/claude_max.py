import asyncio
import json
from typing import AsyncIterator

from apps.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMChunk,
    ProviderError,
    ProviderTransientError,
)


class ClaudeMaxProvider(LLMProvider):
    """
    Runs `claude --print --output-format stream-json` as a subprocess.
    Requires Claude Code CLI to be installed and authenticated.
    Task execution happens inside a tmux window — this provider just handles
    the actual LLM call for non-interactive completions.
    """

    async def complete(self, request: LLMRequest) -> LLMResponse:
        chunks = []
        tokens_used = 0
        async for chunk in self.stream(request):
            chunks.append(chunk.text)
            if chunk.is_final:
                tokens_used = chunk.tokens_used
        return LLMResponse(
            content="".join(chunks),
            tokens_used=tokens_used,
            model=self.config.model_name or "claude-max",
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        prompt = self._build_prompt(request)
        cli_path = self.config.claude_cli_path or "claude"

        cmd = [cli_path, "--print", "--output-format", "stream-json"]
        if self.config.model_name:
            cmd += ["--model", self.config.model_name]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise ProviderError(
                f"Claude CLI not found at '{cli_path}'. "
                "Install Claude Code and ensure it's in your PATH."
            )

        # Write prompt and close stdin so claude starts processing immediately
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()

        # Drain stderr in background to prevent buffer deadlock
        stderr_task = asyncio.create_task(proc.stderr.read())

        # Read stdout line by line — true streaming, not buffered
        total_tokens = 0
        async for line_bytes in proc.stdout:
            line = line_bytes.decode().strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                yield LLMChunk(text=line)
                continue

            event_type = event.get("type", "")
            if event_type == "content_block_delta":
                text = event.get("delta", {}).get("text", "")
                if text:
                    yield LLMChunk(text=text)
            elif event_type == "message_delta":
                total_tokens = event.get("usage", {}).get("output_tokens", 0)
            elif event_type == "message_stop":
                yield LLMChunk(text="", is_final=True, tokens_used=total_tokens)

        await proc.wait()
        stderr_data = await stderr_task
        if proc.returncode != 0:
            raise ProviderTransientError(
                f"Claude CLI exited with code {proc.returncode}: {stderr_data.decode()[:500]}"
            )

    async def health_check(self) -> bool:
        cli_path = self.config.claude_cli_path or "claude"
        try:
            proc = await asyncio.create_subprocess_exec(
                cli_path, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    def _build_prompt(self, request: LLMRequest) -> str:
        parts = []
        if request.system:
            parts.append(f"[System: {request.system}]\n\n")
        for msg in request.messages:
            if msg.role == "user":
                parts.append(msg.content)
            elif msg.role == "assistant":
                parts.append(f"\nAssistant: {msg.content}\n")
        return "".join(parts)
