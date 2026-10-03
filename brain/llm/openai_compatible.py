"""Any chat-completions API in the OpenAI format: DeepSeek, OpenAI, OpenRouter,
Ollama, vLLM, LM Studio... Providers are thin presets around this class."""

from collections.abc import AsyncIterator

from openai import AsyncOpenAI, omit

from .base import LLM, Message


class OpenAICompatibleLLM(LLM):
    def __init__(self, name: str, base_url: str, api_key: str, model: str, temperature: float = 1.0,
                 max_tokens: int = 400, extra_body: dict | None = None):
        self.name = name
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = extra_body or {}
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def stream(self, messages: list[Message], *, max_tokens: int | None = None) -> AsyncIterator[str]:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            stream=True,
            extra_body=self.extra_body,
        )
        async for chunk in response:
            if chunk.choices and (text := chunk.choices[0].delta.content):
                yield text

    async def complete(self, messages: list[Message], *, json: bool = False, temperature: float | None = None,
                       max_tokens: int | None = None) -> str:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            response_format={"type": "json_object"} if json else omit,
            extra_body=self.extra_body,
        )
        return response.choices[0].message.content or ""
