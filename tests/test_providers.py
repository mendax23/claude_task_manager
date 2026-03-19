import pytest
from apps.providers.base import LLMProvider, LLMRequest, LLMMessage, ProviderError


@pytest.mark.django_db
def test_provider_from_config_claude_max(llm_config):
    from apps.providers.implementations import ClaudeMaxProvider
    provider = LLMProvider.from_config(llm_config)
    assert isinstance(provider, ClaudeMaxProvider)


@pytest.mark.django_db
def test_provider_from_config_unknown_raises(db):
    from apps.providers.models import LLMConfig
    # Create a config with an invalid type by bypassing choices
    cfg = LLMConfig(name="bad", provider_type="unknown_provider")
    with pytest.raises(ProviderError):
        LLMProvider.from_config(cfg)


def test_llm_request_defaults():
    req = LLMRequest(messages=[])
    assert req.max_tokens == 8192
    assert req.temperature == 0.7
    assert req.stream is True


@pytest.mark.django_db
def test_claude_max_health_check_false_when_no_cli(llm_config):
    """Health check returns False when claude CLI is not found."""
    import asyncio
    from apps.providers.implementations import ClaudeMaxProvider
    llm_config.claude_cli_path = "/nonexistent/path/to/claude"
    provider = ClaudeMaxProvider(llm_config)
    result = asyncio.run(provider.health_check())
    assert result is False


@pytest.mark.django_db
async def test_ollama_health_check_false_when_not_running(db):
    from apps.providers.models import LLMConfig, ProviderType
    from apps.providers.implementations import OllamaProvider
    cfg = LLMConfig(
        name="ollama-test",
        provider_type=ProviderType.OLLAMA,
        base_url="http://localhost:19999",  # Nothing running here
    )
    provider = OllamaProvider(cfg)
    result = await provider.health_check()
    assert result is False
