"""What the rest of the app needs from a language model: stream a reply, or
return one whole reply (optionally as a JSON object)."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": "..."}


class LLM(ABC):
    name: str = "llm"

    @abstractmethod
    def stream(self, messages: list[Message], *, max_tokens: int | None = None) -> AsyncIterator[str]:
        """Yield the reply to `messages` (system prompt first) in chunks as it is generated."""

    @abstractmethod
    async def complete(self, messages: list[Message], *, json: bool = False, temperature: float | None = None,
                       max_tokens: int | None = None) -> str:
        """The whole reply at once. json=True asks for a single JSON object (the
        prompt must also say so). temperature / max_tokens override the defaults."""
