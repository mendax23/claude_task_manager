import json
from typing import AsyncIterator

from apps.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMChunk,
    ProviderError,
)

DEFAULT_OLLAMA_URL = "http://localhost:11434"


class OllamaProvider(LLMProvider):
    """
    Local Ollama models via httpx async streaming.
    No API key required — just a running Ollama server.
    """

    @property
    def base_url(self) -> str:
        return (self.config.base_url or DEFAULT_OLLAMA_URL).rstrip("/")

    def _get_client(self):
        try:
            import httpx
            return httpx.AsyncClient(timeout=120.0)
        except ImportError:
            raise ProviderError("httpx not installed: pip install httpx")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        chunks = []
        tokens_used = 0
        async for chunk in self.stream(request):
            if chunk.text:
                chunks.append(chunk.text)
            if chunk.is_final:
                tokens_used = chunk.tokens_used
        return LLMResponse(
            content="".join(chunks),
            tokens_used=tokens_used,
            model=request.model or self.config.model_name or "llama3",
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        model = request.model or self.config.model_name or "llama3"
        prompt = self._build_prompt(request)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": request.temperature if request.temperature is not None else self.config.temperature,
                "num_predict": request.max_tokens or self.config.max_tokens,
            },
        }

        async with self._get_client() as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/generate",
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        raise ProviderError(f"Ollama returned {response.status_code}")

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        text = event.get("response", "")
                        done = event.get("done", False)
                        tokens = event.get("eval_count", 0)

                        if text:
                            yield LLMChunk(text=text)
                        if done:
                            yield LLMChunk(text="", is_final=True, tokens_used=tokens)
            except Exception as e:
                raise ProviderError(f"Ollama error: {e}") from e

    async def health_check(self) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False

    def _build_prompt(self, request: LLMRequest) -> str:
        parts = []
        if request.system or self.config.system_prompt:
            parts.append(f"System: {request.system or self.config.system_prompt}\n\n")
        for msg in request.messages:
            if msg.role == "user":
                parts.append(f"User: {msg.content}\n")
            elif msg.role == "assistant":
                parts.append(f"Assistant: {msg.content}\n")
        parts.append("Assistant: ")
        return "".join(parts)
