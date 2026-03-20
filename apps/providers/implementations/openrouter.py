from typing import AsyncIterator

from apps.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMChunk,
    ProviderError,
    ProviderAuthError,
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter via OpenAI-compatible API.
    Supports 100+ models (OpenAI, Anthropic, Mistral, Gemini, local, etc.)
    behind a single API key.
    """

    def _get_client(self):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ProviderError("openai package not installed: pip install openai")

        if not self.config.api_key:
            raise ProviderAuthError("OpenRouter API key not configured.")

        return AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url or OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": "https://github.com/agentqueue/agentqueue",
                "X-Title": "AgentQueue",
            },
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        client = self._get_client()
        messages = self._build_messages(request)

        try:
            response = await client.chat.completions.create(
                model=request.model or self.config.model_name or "openai/gpt-4o-mini",
                messages=messages,
                max_tokens=request.max_tokens or self.config.max_tokens,
                temperature=request.temperature if request.temperature is not None else self.config.temperature,
                stream=False,
                **request.extra,
            )
        except Exception as e:
            raise ProviderError(str(e)) from e

        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            tokens_used=response.usage.completion_tokens if response.usage else 0,
            model=response.model,
            stop_reason=choice.finish_reason or "",
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        client = self._get_client()
        messages = self._build_messages(request)

        tokens_used = 0
        try:
            stream = await client.chat.completions.create(
                model=request.model or self.config.model_name or "openai/gpt-4o-mini",
                messages=messages,
                max_tokens=request.max_tokens or self.config.max_tokens,
                temperature=request.temperature if request.temperature is not None else self.config.temperature,
                stream=True,
                stream_options={"include_usage": True},
                **request.extra,
            )

            async for chunk in stream:
                if chunk.usage:
                    tokens_used = chunk.usage.completion_tokens or 0
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield LLMChunk(text=delta.content)
                if chunk.choices and chunk.choices[0].finish_reason:
                    yield LLMChunk(text="", is_final=True, tokens_used=tokens_used, stop_reason=chunk.choices[0].finish_reason)
        except Exception as e:
            raise ProviderError(str(e)) from e

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            await client.models.list()
            return True
        except Exception:
            return False

    def _build_messages(self, request: LLMRequest) -> list[dict]:
        messages = []
        if request.system or self.config.system_prompt:
            messages.append({"role": "system", "content": request.system or self.config.system_prompt})
        for m in request.messages:
            messages.append({"role": m.role, "content": m.content})
        return messages
