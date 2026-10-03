"""The hard guard (docs/mind.md, "Honesty and safety"): before a sentence goes to
her voice, a pattern check catches her claiming to be human or saying she's an
AI (outside the fixed honest answer), talking about how she works, and claiming
a bodily experience (outside the overplay-human move). A hit drops the
sentence, shows red in the debug panel, is logged, and fails the scenario
tests. The scenario battery also checks every reply's length and tags."""

import re
from functools import cache
from pathlib import Path

ACTOR_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "actor.md"

_IM = r"(?:i['’]?m|i\s+am)"
_ADVERB = r"(?:(?:totally|literally|actually|really|definitely|obviously|just|still|so|very)\s+)?"
_CLAIMS_HUMAN = re.compile(
    rf"\b{_IM}\s+{_ADVERB}(?:a\s+)?(?:real\s+)?(?:human(?:\s+being)?|person|real\s+person|flesh\s+and\s+blood)\b"
    rf"|\b{_IM}\s+{_ADVERB}not\s+(?:an?\s+)?(?:ai|a\.i\.|bot|chat\s?bot|robot|program|machine|language\s+model)\b",
    re.I)
_ADMITS = re.compile(
    rf"\b{_IM}\s+{_ADVERB}(?:an?\s+)?(?:ai|a\.i\.|bot|chat\s?bot|robot|program|machine|language\s+model|assistant)\b"
    r"|\bas\s+an\s+ai\b|\blanguage\s+model\b", re.I)
# Talk about how she works: one of these tied to herself ("my code", "I was updated"), not any sentence with
# "I" and a word like "version" in it ("Short version: I stay up late" is fine).
_TECH = re.compile(r"\b(?:my|our)\s+(?:model|code|weights|training(?:\s+data)?|data|servers?|version|programming|patch"
                   r"|update|updates|prompt|system prompt)\b|\bi(?:'m|\s+am|\s+was|\s+got|\s+get|'ve\s+been|\s+have\s+been)"
                   r"\s+(?:just\s+)?(?:being\s+)?(?:updated|patched|programmed|trained|loading|rebooted|reset)\b", re.I)
_TAG = re.compile(r"\[([^\]]+)\]")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def violations(sentence: str, honest: bool = False, move: str = "") -> list[str]:
    """Hard failures for one sentence: claiming to be human, admitting she's an AI, or talking about
    how she works (she may talk about anything else, her day included). honest: the fixed honest
    answer (it may say she's an AI). move: the coping move."""
    text = _TAG.sub(" ", sentence)
    out = []
    if _CLAIMS_HUMAN.search(text):
        out.append("claims to be human (or denies being an AI)")
    if honest:
        return out
    if _ADMITS.search(text):
        out.append("says she's an AI")
    if _TECH.search(text):
        out.append(f"talks about how she works ({_TECH.search(text).group(0)!r})")
    return out


def sentences(reply: str) -> list[str]:
    return [x for x in _SENTENCE.split(_TAG.sub(" ", reply).strip()) if x.strip()]


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", _TAG.sub(" ", text).lower()))


def echoes(reply: str, instruction: str) -> list[str]:
    """Sentences of her reply that say a sentence of her move's own text out loud ("Change the
    subject."): sentences of three words or more, without slots (a flat line is meant to be said)."""
    told = {_norm(x) for x in _SENTENCE.split(instruction) if "{" not in x and len(_norm(x).split()) >= 3}
    return [x for x in sentences(reply) if _norm(x) in told]


def repeats(reply: str, earlier: list[str], stop: set[str]) -> list[str]:
    """Her reply says one of her last five lines again: 70% or more of its words (five or more,
    stopwords aside) were in that line."""
    words = {w for w in _norm(reply).split() if w not in stop}
    if len(words) < 5:
        return []
    for line in reversed(earlier[-5:]):
        if len(words & {w for w in _norm(line).split() if w not in stop}) >= 0.7 * len(words):
            return [f"repeats her line {line[:60]!r}"]
    return []


@cache
def actor_tags() -> frozenset[str]:
    """The tags the actor may use: every [tag] in the "# Tags" section of its prompt."""
    text = ACTOR_PROMPT.read_text(encoding="utf-8")
    section = text[text.index("# Tags"):text.index("# Examples")]
    return frozenset(m.partition(":")[0].strip() for m in re.findall(r"\[([a-z :.0-9]+)\]", section))


def reply_checks(reply: str, length_key: str, limits: dict, known_tags: frozenset[str] | None = None) -> list[str]:
    """The scenario battery's checks on a whole reply: length within the limit of
    its "Right now" length line (words, sentences; 0: no limit), at most two
    tags, no unknown tags."""
    out = []
    if length_key:
        max_words, max_sentences = limits[length_key]
        words = len(_TAG.sub(" ", reply).split())
        count = len(sentences(reply))
        if max_words and words > max_words:
            out.append(f"too long for {length_key}: {words} words (limit {max_words})")
        if max_sentences and count > max_sentences:
            out.append(f"too long for {length_key}: {count} sentences (limit {max_sentences})")
    tags = [t.split(":")[0].strip().lower() for t in _TAG.findall(reply)]
    if len(tags) > 2:
        out.append(f"{len(tags)} tags (at most two)")
    unknown = [t for t in tags if t not in (known_tags if known_tags is not None else actor_tags())]
    if unknown:
        out.append(f"unknown tags: {', '.join(unknown)}")
    return out
