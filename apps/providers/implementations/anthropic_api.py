from typing import AsyncIterator

from apps.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMChunk,
    ProviderError,
    ProviderAuthError,
)


class AnthropicAPIProvider(LLMProvider):
    """Uses the official Anthropic Python SDK with streaming."""

    def _get_client(self):
        try:
            import anthropic
        except ImportError:
            raise ProviderError("anthropic package not installed: pip install anthropic")

        if not self.config.api_key:
            raise ProviderAuthError("Anthropic API key not configured.")

        return anthropic.AsyncAnthropic(api_key=self.config.api_key)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        client = self._get_client()
        import anthropic

        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("user", "assistant")
        ]

        try:
            response = await client.messages.create(
                model=request.model or self.config.model_name or "claude-opus-4-6",
                max_tokens=request.max_tokens or self.config.max_tokens,
                temperature=request.temperature if request.temperature is not None else self.config.temperature,
                system=request.system or self.config.system_prompt or anthropic.NOT_GIVEN,
                messages=messages,
            )
        except anthropic.AuthenticationError as e:
            raise ProviderAuthError(str(e)) from e
        except anthropic.APIError as e:
            raise ProviderError(str(e)) from e

        return LLMResponse(
            content=response.content[0].text if response.content else "",
            tokens_used=response.usage.output_tokens,
            model=response.model,
            stop_reason=response.stop_reason or "",
            raw=response.model_dump(),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        client = self._get_client()
        import anthropic

        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("user", "assistant")
        ]

        try:
            async with client.messages.stream(
                model=request.model or self.config.model_name or "claude-opus-4-6",
                max_tokens=request.max_tokens or self.config.max_tokens,
                system=request.system or self.config.system_prompt or anthropic.NOT_GIVEN,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield LLMChunk(text=text)

                final = await stream.get_final_message()
                yield LLMChunk(
                    text="",
                    is_final=True,
                    tokens_used=final.usage.output_tokens,
                    stop_reason=final.stop_reason or "",
                )
        except anthropic.AuthenticationError as e:
            raise ProviderAuthError(str(e)) from e
        except anthropic.APIError as e:
            raise ProviderError(str(e)) from e

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            await client.messages.create(
                model=self.config.model_name or "claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except Exception:
            return False
