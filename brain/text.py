"""Text plumbing between what she should say and the voice: sentence splitting
(also while an LLM reply is still streaming in) and cleanup of LLM output."""

import re
import unicodedata
from pathlib import Path

PRONUNCIATIONS = Path(__file__).resolve().parent / "voices" / "pronunciations.txt"
# Personal names (yours, your regulars'): same format, kept out of git, read when it exists.
LOCAL_PRONUNCIATIONS = PRONUNCIATIONS.with_name("pronunciations.local.txt")

_SENTENCE_END = re.compile(r"(?<=[!?])\s+|(?<=[^.]\.)\s+")  # not after "..."
_TAG = re.compile(r"\[[^\]]*\]")
_WORD = re.compile(r"\w")

# *laughs* style actions some models write anyway -> tags she can perform.
_ACTIONS = {
    r"laugh(s|ing)?|giggl(e|es|ing)": "[laugh]",
    r"chuckl(e|es|ing)": "[chuckle]",
    r"sigh(s|ing)?": "[sigh]",
    r"gasp(s|ing)?": "[gasp]",
    r"smil(e|es|ing)": "[smile]",
    r"grin(s|ning)?": "[grin]",
    r"wink(s|ing)?": "[wink]",
    r"nod(s|ding)?": "[nod]",
    r"shrug(s|ging)?": "[shrug]",
}
_ACTION = re.compile(r"\*([^*]{1,40})\*")


def split_sentences(text: str) -> list[str]:
    """Split on sentence ends; a trailing tag ("Funny! [laugh]") stays with its sentence."""
    sentences: list[str] = []
    for part in _SENTENCE_END.split(text.strip()):
        if sentences and not _TAG.sub("", part).strip(" .,!?"):
            sentences[-1] += " " + part
        elif part:
            sentences.append(part)
    return sentences


class SentenceStream:
    """Collects streamed text and hands out speakable chunks as soon as they're complete.

    Very short sentences ("Hm." "Lonely.") are grouped with what follows until a
    chunk has `min_words`, so the voice keeps its flow instead of saying each
    fragment as a separate clip.
    """

    def __init__(self, min_words: int = 6) -> None:
        self.min_words = min_words
        self._buffer = ""
        self._pending: list[str] = []

    def feed(self, chunk: str) -> list[str]:
        self._buffer += chunk
        # Cut at the last sentence end that real words follow, so a tag right
        # after a sentence ("Funny! [laugh]") isn't cut off from it.
        cut = None
        for m in _SENTENCE_END.finditer(self._buffer):
            if _WORD.search(_TAG.sub("", self._buffer[m.end():])):
                cut = m
        if cut is None:
            return []
        done, self._buffer = self._buffer[: cut.start()], self._buffer[cut.end():]
        return self._group(split_sentences(done))

    def flush(self) -> list[str]:
        parts = self._pending + split_sentences(self._buffer)
        self._buffer, self._pending = "", []
        return [" ".join(parts)] if parts else []

    def _group(self, sentences: list[str]) -> list[str]:
        out = []
        for sentence in sentences:
            self._pending.append(sentence)
            if _word_count(" ".join(self._pending)) >= self.min_words:
                out.append(" ".join(self._pending))
                self._pending = []
        return out


def _word_count(text: str) -> int:
    return len(_TAG.sub(" ", text).split())


_PAUSE = re.compile(r"\[\s*(long\s+)?pause\s*(?::\s*([\d.]+)\s*)?\]", re.IGNORECASE)
PAUSE = (0.7, 1.2)  # seconds of silence for [pause]
LONG_PAUSE = (1.5, 2.2)  # and for [long pause]


def split_pauses(sentence: str) -> list[str | tuple[float, float]]:
    """Cut a sentence at [pause] / [long pause] / [pause:1.5] (seconds): text pieces,
    with the pause ranges between them. "[suspicious] [pause] So?" -> ["[suspicious]", (0.7, 1.2), "So?"]"""
    items: list[str | tuple[float, float]] = []
    last = 0
    for m in _PAUSE.finditer(sentence):
        if piece := sentence[last:m.start()].strip():
            items.append(piece)
        if m.group(2):
            seconds = min(4.0, float(m.group(2)))
            items.append((seconds, seconds))
        else:
            items.append(LONG_PAUSE if m.group(1) else PAUSE)
        last = m.end()
    if piece := sentence[last:].strip():
        items.append(piece)
    return items


def clean_for_speech(text: str) -> str:
    """Make LLM output speakable: actions -> tags, no markdown, no emoji."""
    def action(m: re.Match) -> str:
        words = m.group(1).strip().lower()
        for pattern, tag in _ACTIONS.items():
            if re.fullmatch(pattern, words):
                return tag
        return ""  # other narrated actions are dropped

    text = _ACTION.sub(action, text)
    text = re.sub(r"\[\s*(?:gap|beat|silence)\s*\]", "[pause]", text, flags=re.IGNORECASE)
    text = re.sub(r"[*_#`~>|]", "", text)
    text = "".join(c for c in text if unicodedata.category(c) not in ("So", "Cs", "Co"))
    return " ".join(text.split())


def pronounce(text: str) -> str:
    """Respell words the voice gets wrong (voices/pronunciations.txt, then pronunciations.local.txt if
    there is one; re-read every call)."""
    lines = PRONUNCIATIONS.read_text(encoding="utf-8").splitlines()
    if LOCAL_PRONUNCIATIONS.exists():
        lines += LOCAL_PRONUNCIATIONS.read_text(encoding="utf-8").splitlines()
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        word, spoken = (part.strip() for part in line.split("=", 1))
        text = re.sub(rf"\b{re.escape(word)}\b", spoken, text, flags=re.IGNORECASE)
    return text
