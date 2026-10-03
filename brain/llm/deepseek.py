"""DeepSeek, with thinking disabled: fast, direct replies for live chat."""

import os
from pathlib import Path

from .openai_compatible import OpenAICompatibleLLM

KEY_FILE = Path(__file__).resolve().parent.parent / "DEEPSEEK_KEY"


def deepseek(model: str = "deepseek-flash", temperature: float = 1.0, max_tokens: int = 600) -> OpenAICompatibleLLM:
    """temperature: for her lines. DeepSeek suggests 1.3 for conversation, but with
    her long prompt that sometimes falls apart into word salad; 1.0 holds. Her
    mind's calls (appraisal, thoughts) set their own temperatures."""
    api_key = os.environ.get("DEEPSEEK_API_KEY") or (KEY_FILE.read_text().strip() if KEY_FILE.exists() else "")
    if not api_key:
        raise RuntimeError(f"No DeepSeek key: set DEEPSEEK_API_KEY or put it in {KEY_FILE}")
    return OpenAICompatibleLLM(
        name="deepseek",
        base_url="https://api.deepseek.com",
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body={"thinking": {"type": "disabled"}},
    )
