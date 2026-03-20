import abc
import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import LLMConfig


@dataclass
class LLMMessage:
    role: str  # 'user' | 'assistant' | 'system'
    content: str


@dataclass
class LLMRequest:
    messages: list[LLMMessage]
    model: str = ""
    max_tokens: int = 8192
    temperature: float = 0.7
    system: str = ""
    stream: bool = True
    cwd: str = ""  # working directory for subprocess providers (claude_max)
    extra: dict = field(default_factory=dict)


@dataclass
class LLMChunk:
    text: str
    is_final: bool = False
    tokens_used: int = 0
    stop_reason: str = ""


@dataclass
class LLMResponse:
    content: str
    tokens_used: int = 0
    model: str = ""
    stop_reason: str = ""
    raw: dict = field(default_factory=dict)


class ProviderError(Exception):
    pass


class ProviderTransientError(ProviderError):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderRateLimitError(ProviderTransientError):
    pass


class LLMProvider(abc.ABC):
    def __init__(self, config: "LLMConfig"):
        self.config = config

    @abc.abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        ...

    @abc.abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        ...

    @abc.abstractmethod
    async def health_check(self) -> bool:
        ...

    def supports_streaming(self) -> bool:
        return True

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    async def complete_with_retry(self, request: LLMRequest, retries: int = 3) -> LLMResponse:
        for attempt in range(retries):
            try:
                return await self.complete(request)
            except ProviderTransientError:
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(2**attempt)

    @classmethod
    def from_config(cls, config: "LLMConfig") -> "LLMProvider":
        from .implementations import (
            ClaudeMaxProvider,
            AnthropicAPIProvider,
            OpenRouterProvider,
            OllamaProvider,
        )

        mapping = {
            "claude_max": ClaudeMaxProvider,
            "anthropic": AnthropicAPIProvider,
            "openrouter": OpenRouterProvider,
            "ollama": OllamaProvider,
        }
        provider_class = mapping.get(config.provider_type)
        if not provider_class:
            raise ProviderError(f"Unknown provider type: {config.provider_type}")
        return provider_class(config)
