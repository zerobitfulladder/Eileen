"""Thoughts (docs/mind.md, "Thoughts"): short fragments of what's on her mind,
written by an LLM from her state. They come when chat is quiet, 20 to 60 s
after something hit her hard (it comes back), when a drive builds up, or when
a late comeback or a quiet flip is due.

What she pushed away comes back (Wegner's ironic process): every topic she
dodged gets an intrusion value that fades over 12 minutes, and quiet thoughts
pick those topics more often, two or three times, then they fade. Her mood
picks the memory (Bower): low, she remembers the bad moments; up, the good.

The thought itself stays private (the debug panel shows it, and its private
meaning). The actor only sees an ordinary thought's topic, a few words that
pass the word check, as "On your mind: ...", for as long as it's salient."""

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from llm import LLM

from .appraisal import AppraisalError, _ask
from .persona import EMOTIONS
from .state import halve

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "thoughts.md"
TONES = EMOTIONS + ("sincere", "coy", "tender", "intrigued")
# The appraisal's wound_topic -> the intrusion topic.
WOUND_TOPICS = {"food": "food", "sleep": "sleep", "body": "body", "family": "family", "being_ai": "being an AI",
                "being_changed": "being changed", "other_ais": "other AIs"}


@dataclass
class Thought:
    text: str  # what crosses her mind (debug panel; brain.py shows it as a glance)
    topic: str  # what the actor may see: a few words that pass the word check ("" for a wound thought)
    tone: str  # the felt face it brings
    born: float
    reason: str
    private: str = ""  # what it's really about: debug panel only, never the actor
    salience: float = 0.5
    wound: bool = False  # about the wound: shows in her face and gaze, never told to the actor
    late: bool = False  # a late comeback or a quiet flip: only their own mechanisms hand it to the actor
    used: bool = False  # she already brought it up
    lint_error: str = ""  # its topic failed the word check and was dropped

    def alive(self, now: float, half_life: float, lifetime: float, drop: float) -> float:
        """Its salience now (0 once it's gone)."""
        age = now - self.born
        s = self.salience * halve(age, half_life)
        return s if age < lifetime and s >= drop else 0.0


@dataclass
class Intrusions:
    """Topics she pushed away, and how hard they press to come back."""
    half_life: float
    values: dict[str, float] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)  # topic -> what it was (a gist)
    objects: dict[str, str] = field(default_factory=dict)  # topic -> an ordinary word from it (the busy-chat slip)
    at: float = 0.0

    def decay(self, now: float) -> None:
        dt = now - self.at
        if dt > 0.0:
            k = halve(dt, self.half_life)
            self.values = {t: v * k for t, v in self.values.items() if v * k >= 0.01}
            self.at = now

    def add(self, topic: str, amount: float, note: str, obj: str, now: float) -> None:
        self.decay(now)
        self.values[topic] = min(1.0, self.values.get(topic, 0.0) + amount)
        self.notes[topic] = note
        if obj:
            self.objects[topic] = obj

    def top(self, n: int = 3) -> list[tuple[str, float]]:
        return sorted(self.values.items(), key=lambda kv: -kv[1])[:n]


def intrusion_topic(wound_topic: str, sender: str) -> str:
    """Which intrusion topic a hit feeds: the appraisal's wound_topic, or the person's remark
    (a reading-only or philosophy-of-mind reminder carries no wound topic)."""
    return WOUND_TOPICS[wound_topic] if wound_topic else f"{sender}'s remark"


class Thinker:
    def __init__(self, llm: LLM, settings: dict, limits: dict, prompt_path: Path = PROMPT):
        self.llm = llm
        self.settings = settings  # persona [llm] thought: max_tokens, temperature
        self.limits = limits  # persona [thoughts]: words, topic_words, long_words
        self.prompt_path = prompt_path

    async def think(self, reason: str, topic: str, events: list[str], feelings: list[str], tastes: list[str],
                    recent: list[str], banned: list[str], lint, now: float, *, wound: bool = False,
                    late: bool = False, shape: str = "") -> Thought:
        """reason: why a thought comes now. topic: what it's about. events: gists of
        the last few things that happened. feelings: her top emotions (this call is
        private). wound: a wound thought (no topic for the actor). late: a late
        comeback or a quiet flip (its line may be longer). shape: a late comeback's
        misfire shape. One call, no retry: an invalid answer is dropped."""
        data = {"why_now": reason, "about": topic or "whatever is on her mind", "recent_events": events,
                "her_feelings": feelings, "her_tastes": tastes, "her_last_thoughts": recent,
                "wound_thought": wound, "banned_words": banned}
        if shape:
            data["comeback_shape"] = shape
        user = json.dumps(data, ensure_ascii=False) + "\n\nAnswer with the JSON object only."
        lo, hi = self.limits["words"]
        long_words = self.limits["long_words"]

        def parse(text: str) -> Thought:
            try:
                d = json.loads(text)
            except json.JSONDecodeError as e:
                raise AppraisalError(f"not valid JSON ({e.msg})") from None
            if not isinstance(d, dict) or set(d) - {"thought", "private", "tone", "topic"}:
                raise AppraisalError("the answer must be one JSON object with thought, private, tone and topic")
            thought, private, tone, public = (d.get(k, "") for k in ("thought", "private", "tone", "topic"))
            if not all(isinstance(x, str) for x in (thought, private, tone, public)):
                raise AppraisalError("thought, private, tone and topic are text")
            thought, public = " ".join(thought.split()), " ".join(public.split())
            words = len(thought.split())
            if not (lo <= words <= hi or (late and 1 <= words <= long_words)):
                raise AppraisalError(f"the thought must be {lo} to {hi} words, got {words}")
            if tone not in TONES:
                raise AppraisalError(f"tone must be one of {', '.join(TONES)}; got {tone!r}")
            if wound and public:
                raise AppraisalError("a wound thought has no topic")
            if len(public.split()) > (long_words if late else self.limits["topic_words"]):
                raise AppraisalError("the topic is too long")
            said = f"{thought} {public}".lower()
            if re.search(r"\b(he|she|him|his|hers|he's|she's|typing)\b", said):
                raise AppraisalError("no he or she for people in chat, and she can't see anyone typing")
            words_now = set(re.findall(r"[a-z']+", thought.lower()))
            for old in recent:
                before = set(re.findall(r"[a-z']+", old.lower()))
                if words_now and len(words_now & before) >= 0.6 * len(words_now):
                    raise AppraisalError(f"too close to an earlier thought: {old!r}")
            out = Thought(thought, public, tone, now, reason, " ".join(private.split()))
            bad = lint(public)
            if bad:  # the thought stays; its topic is dropped and logged
                out.topic, out.lint_error = "", f"thought topic {public!r} failed the word check: {', '.join(bad)}"
            return out

        return await _ask(self.llm, self.prompt_path.read_text(encoding="utf-8"), user, parse,
                          self.settings["max_tokens"], self.settings["temperature"], retry=False)


def pick(rng: random.Random, options: dict[str, float]) -> str:
    """A weighted draw over topics or memories."""
    total = sum(options.values())
    x = rng.random() * total
    for key, weight in options.items():
        x -= weight
        if x <= 0.0:
            return key
    return next(reversed(options))
