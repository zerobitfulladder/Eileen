"""The actor: turns a chat message into her spoken reply.

The prompt lives in prompts/actor.md and is re-read for every message, so edits
apply without restarting; {looks} in it becomes the body she's streaming in
(models.toml). Her mind (mind/) adds a short "Right now" note before
each message: how she's acting and what to do with it, as behavior only. The
conversation (chat messages and her replies) is kept in memory for as long as
the server runs and is gone when it stops; the notes are not kept.
"""

import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path

from llm import LLM, Message
from text import SentenceStream, clean_for_speech

_LOGGER = logging.getLogger("eileen")

DEFAULT_PROMPT = Path(__file__).resolve().parent / "prompts" / "actor.md"
QUIET = "(chat is quiet)"  # stands in for a chat message when she speaks first

# Models occasionally run on past the reply into their own role markers
# ("...back here with you. systemThis interaction completes..."); cut it there.
# Where the actor runs past her line: chat-format markers, a "---" divider, or a new line that starts like a
# chat message ("mira: are you in a band?"). Everything from there on is cut, never spoken.
_RUNAWAY = re.compile(r"(?:system|assistant)(?=[A-Z])|\b(?:system|assistant|user)\s*:|<\||\bRight now\s*:|-{3,}"
                      r"|\n\s*[\w.]{2,24}\s*:\s", re.IGNORECASE)
_HOLD_BACK = 12  # don't speak the last few characters yet: a marker may be split across chunks


class ChatResponder:
    def __init__(self, llm: LLM, looks: str, prompt_path: Path = DEFAULT_PROMPT):
        self.llm = llm
        self.looks = looks  # her body's description (models.toml)
        self.prompt_path = prompt_path
        self.history: list[Message] = []  # this stream so far, oldest first
        self.last_reply = ""

    def remember(self, message: str, text: str) -> None:
        """A line she said exactly (no actor call) still belongs to the conversation."""
        self.history += [{"role": "user", "content": message}, {"role": "assistant", "content": text}]

    def reset(self) -> None:
        """Forget the conversation so far (the /reset command)."""
        self.history.clear()
        _LOGGER.info("chat history cleared")

    def system_prompt(self) -> str:
        text = self.prompt_path.read_text(encoding="utf-8")
        if "{looks}" not in text:
            raise ValueError(f"{self.prompt_path} has no {{looks}} (where her body's description goes)")
        return text.replace("{looks}", self.looks)

    def messages(self, message: str, right_now: str = "") -> list[Message]:
        """What the model sees: her prompt, the stream so far, the note, the new message."""
        out = [{"role": "system", "content": self.system_prompt()}, *self.history]
        if right_now:
            out.append({"role": "system", "content": right_now})
        out.append({"role": "user", "content": message})
        return out

    async def reply(self, message: str, right_now: str = "", max_tokens: int | None = None) -> AsyncIterator[str]:
        """Yield her reply sentence by sentence, each as soon as it's complete."""
        _LOGGER.info("chat #%d: %s", len(self.history) // 2 + 1, message)
        if right_now:
            _LOGGER.info("  right now: %s", right_now.replace("\n", " / "))
        stream = SentenceStream()
        raw = ""
        fed = 0  # how much of `raw` has gone to the sentence splitter
        self.last_reply = ""
        try:
            async for chunk in self.llm.stream(self.messages(message, right_now), max_tokens=max_tokens):
                raw += chunk
                runaway = _RUNAWAY.search(raw)
                safe = runaway.start() if runaway else max(fed, len(raw) - _HOLD_BACK)
                for sentence in stream.feed(raw[fed:safe]):
                    if sentence := clean_for_speech(sentence):
                        yield sentence
                fed = safe
                if runaway:
                    _LOGGER.warning("cut off a runaway reply: %r", raw[safe:safe + 80])
                    raw = raw[:safe]
                    break
            rest = stream.feed(raw[fed:]) + stream.flush()
            if max_tokens is not None and rest and not re.search(r"[.!?…\"')\]]\s*$", rest[-1]):
                _LOGGER.info("dropped an unfinished sentence (reply capped): %r", rest[-1])
                raw = raw[: raw.rfind(rest[-1])].rstrip() if rest[-1] in raw else raw
                rest = rest[:-1]
            for sentence in rest:
                if sentence := clean_for_speech(sentence):
                    yield sentence
        except Exception as error:  # network, quota, bad key...
            _LOGGER.error("%s failed: %s", self.llm.name, error)
        finally:
            # Remember the exchange, including a reply cut short by /stop.
            text = raw.strip()
            self.last_reply = text
            if text:
                self.history += [{"role": "user", "content": message}, {"role": "assistant", "content": text}]
            _LOGGER.info("reply: %s", text or "(nothing)")
