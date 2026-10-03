"""Language models behind her replies. To add one, write a function that returns
an LLM (most providers are an OpenAICompatibleLLM preset, see deepseek.py) and
register it in PROVIDERS."""

from collections.abc import Callable

from .base import LLM, Message
from .deepseek import deepseek
from .openai_compatible import OpenAICompatibleLLM

PROVIDERS: dict[str, Callable[..., LLM]] = {
    "deepseek": deepseek,
}


def create_llm(provider: str, **options) -> LLM:
    """options are passed to the provider, e.g. model="deepseek-flash", temperature=1.0."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider {provider!r}; available: {', '.join(PROVIDERS)}")
    return PROVIDERS[provider](**{k: v for k, v in options.items() if v is not None})


__all__ = ["LLM", "Message", "OpenAICompatibleLLM", "PROVIDERS", "create_llm"]
