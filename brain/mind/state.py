"""Her inner state as numbers: emotions, mood, the wound, drives, how she feels
about each person, and what she's waiting to see happen (prospects). Every
value has a range and a resting value it drifts back to at its own speed. The
rules that move them live in rules.py and engine.py; this module holds them,
lets them fade, and describes them for the debug panel.

Emotions (docs/mind.md, "Emotions: a fast spike and a slow tail") are a small
list of sources, written "cause|target" ("wound|xx_dan", "news|ren", "self",
"fiction"): who and what the feeling is about. Each source keeps its own fast
part, which spikes and falls within seconds, and its own slow part, which
lingers for minutes; the emotion's value is their sum, at most 1. An impulse
lands at once and saturates: two impulses of 0.6 make 0.84, never more than 1.
Sources decide which display rule applies (her own sadness is hidden, sadness
for Ren's cat is not), how much she's hiding, and who a "Right now" line is
about."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field


def halve(dt: float, half_life: float) -> float:
    """The factor a value keeps after dt seconds with this half-life."""
    return 0.5 ** (dt / half_life) if half_life > 0.0 else 0.0


def exp_toward(current: float, target: float, dt: float, tau: float) -> float:
    """Move toward target with time constant tau (exact for any dt)."""
    return target + (current - target) * math.exp(-dt / tau) if tau > 0.0 else target


def clamp(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def decayed(pair: tuple[float, float], now: float, half_life: float) -> float:
    """A decaying count (count, when it was last set) as of now."""
    count, at = pair
    return count * halve(max(0.0, now - at), half_life)


@dataclass
class Var:
    """A plain value: mood, wound, drives."""
    key: str
    label: str
    rest: float = 0.0
    lo: float = 0.0
    hi: float = 1.0
    half_life: float | None = None  # seconds to fade halfway back to rest; None: moved only by the rules
    color: str = "#cccccc"
    hint: str = ""
    value: float = math.nan  # starts at rest

    def __post_init__(self) -> None:
        if math.isnan(self.value):
            self.value = self.rest

    def set(self, value: float) -> float:
        """Set (clamped to the range); returns the change that happened."""
        before = self.value
        self.value = clamp(value, self.lo, self.hi)
        return self.value - before

    def add(self, delta: float) -> float:
        return self.set(self.value + delta)

    def fade(self, dt: float, slower: float = 1.0) -> None:
        if self.half_life is None or dt <= 0.0:
            return
        self.value = self.rest + (self.value - self.rest) * halve(dt, self.half_life * slower)


# Causes whose feelings belong to the wound: hidden hardest, and they cost her to hide.
WOUND_CAUSES = ("wound", "change", "exposure", "standard")


def is_wound(source: str) -> bool:
    return source.split("|")[0] in WOUND_CAUSES


@dataclass
class Part:
    """One source's share of a feeling."""
    fast: float = 0.0
    slow: float = 0.0

    @property
    def amount(self) -> float:
        return self.fast + self.slow


@dataclass
class Emotion:
    """One emotion: a small list of sources, each with a fast and a slow part."""
    name: str
    fast_hl: float  # half-life of the fast part
    slow_hl: float  # half-life of the slow part
    share: float  # base share of an impulse that goes to the slow part
    wound_fed: bool = False  # its wound-caused slow parts stretch as doubt grows
    valence: int = 0  # +1 pleasant, -1 unpleasant
    pad: tuple[float, float, float] = (0.0, 0.0, 0.0)  # pull on mood: pleasure, arousal, dominance
    color: str = "#cccccc"
    hint: str = ""
    max_share: float = 0.8  # the slow part of an impulse: min(max_share, share + importance_share x importance)
    importance_share: float = 0.25
    gone: float = 1e-5  # a source below this is dropped
    sources: dict[str, Part] = field(default_factory=dict)
    last_slow: float = 0.0  # the slow amount the last impulse added (a hard moment's tail, for rumination)

    @property
    def value(self) -> float:
        return min(1.0, sum(p.amount for p in self.sources.values()))

    @property
    def target(self) -> float:
        """The value. Kept for the body's API (brain.py reads .target); feelings
        have no rise time, so it's always the same as value."""
        return self.value

    @property
    def fast(self) -> float:
        return sum(p.fast for p in self.sources.values())

    @property
    def slow(self) -> float:
        return sum(p.slow for p in self.sources.values())

    def impulse(self, x: float, importance: float, source: str) -> float:
        """A push of size x (0..1) from one source: adds x x (1 - value), at once.
        Returns the increase."""
        if not source:
            raise ValueError(f"an impulse into {self.name} needs a source")
        x = clamp(x, 0.0, 1.0)
        self.last_slow = 0.0
        if x <= 0.0:
            return 0.0
        inc = x * (1.0 - self.value)
        share = min(self.max_share, self.share + self.importance_share * clamp(importance, 0.0, 1.0))
        part = self.sources.setdefault(source, Part())
        part.fast += inc * (1.0 - share)
        part.slow += inc * share
        self.last_slow = inc * share
        return inc

    def tick(self, dt: float, doubt: float, undo: float, doubt_stretch: float, news_sadness: float) -> None:
        """Advance dt seconds, each source on its own. undo (<= 1) shortens the
        fast half-life of a bad feeling (good feelings undo bad ones)."""
        if dt <= 0.0:
            return
        fast_hl = self.fast_hl * (undo if self.valence < 0 else 1.0)
        for source in list(self.sources):
            part = self.sources[source]
            slow_hl = self.slow_hl
            if self.name == "sadness" and source.split("|")[0] == "news":
                slow_hl = news_sadness  # she feels for Ren; she doesn't grieve for an hour
            elif self.wound_fed and is_wound(source):
                slow_hl *= 1.0 + doubt_stretch * doubt  # a hard stream gets stickier as it goes
            part.fast *= halve(dt, fast_hl)
            part.slow *= halve(dt, slow_hl)
            if part.amount < self.gone:
                del self.sources[source]

    def reduce(self, amount: float, match: Callable[[str], bool]) -> float:
        """Take `amount` from the matching sources, from their fast and slow
        parts in proportion. Returns what it took."""
        keys = [s for s in self.sources if match(s)]
        total = sum(self.sources[s].amount for s in keys)
        if total <= 0.0 or amount <= 0.0:
            return 0.0
        taken = min(amount, total)
        keep = (total - taken) / total
        for s in keys:
            self.sources[s].fast *= keep
            self.sources[s].slow *= keep
        return taken

    def scale(self, factor: float, match: Callable[[str], bool]) -> float:
        """Multiply the matching sources (the emotion stays at most 1). Returns the change."""
        before = self.value
        for s, part in self.sources.items():
            if match(s):
                part.fast *= factor
                part.slow *= factor
        over = sum(p.amount for p in self.sources.values()) - 1.0
        if over > 0.0:
            self.reduce(over, match)
        return self.value - before

    def part_of(self, match: Callable[[str], bool]) -> float:
        """How much of the value comes from sources that match (a predicate on "cause|target")."""
        return min(self.value, sum(p.amount for s, p in self.sources.items() if match(s)))

    def parts(self) -> list[tuple[str, float]]:
        """(source, amount) pairs, biggest first."""
        return sorted(((s, p.amount) for s, p in self.sources.items()), key=lambda sp: -sp[1])

    def wound_part(self) -> float:
        return self.part_of(is_wound)

    def aimed_at(self, name: str) -> float:
        return self.part_of(lambda s: s.endswith(f"|{name}"))

    def top_source(self) -> str:
        parts = self.parts()
        return parts[0][0] if parts and parts[0][1] >= 0.02 else ""


@dataclass
class Person:
    """How she feels about one person in chat. Lives for this stream (memory comes later)."""
    name: str
    familiarity: float = 0.0  # 0..1, how much they've talked with her
    liking: float = 0.0  # -1..1
    threat: float = 0.0  # 0..1, how much they remind her of what she is
    messages: int = 0
    last_seen: float = 0.0
    repeats: dict[str, float] = field(default_factory=dict)  # kind of poke -> decaying count (h_s)
    kind: float = 0.0  # their kind messages, a decaying count (R8, R16)
    looks: float = 0.0  # their compliments on her looks, a decaying count (compliment spam)
    counts_at: float = 0.0  # when the decaying counts and the threat were last brought up to date
    hurt: dict[str, float] = field(default_factory=lambda: {"hostile": 0.0, "soft": 0.0})  # how they've hurt her
    gains: list[tuple[float, float]] = field(default_factory=list)  # (time, liking gained) for the 10-minute cap
    comebacks: list[float] = field(default_factory=list)  # when she fired a comeback at them
    last_move: str = ""  # the last coping move she used with them
    guilt_until: float = -math.inf  # she owes them: she snapped at them for nothing
    snap_reply: int = 0  # her reply count when that guilt debt opened
    own_it_due: bool = False  # her next reply to them is "Say it came out wrong."
    latch: bool = False  # the honesty latch: they truly needed to know what she is
    honest_asks: int = 0  # how many times she gave them the straight answer
    judged_at: float = -math.inf  # the last time she judged them (never twice within 10 minutes)
    peace_at: float = -math.inf  # the last time they said they're at peace with a "bad" quality
    peace_again_at: float = -math.inf  # the last time they answered her judgment with more peace
    denial: bool = False  # she likes them and their peace is close to her secret (R9): protective denial, not judging
    sorry_until: float = -math.inf  # bad news or distress: she's gentle with them until then
    left_at: float | None = None  # when they said they were leaving
    exposure_at: float = -math.inf  # the last mere-exposure liking gain (at most one per 5 minutes)

    def decay(self, now: float, p: dict) -> None:
        """Repeat counts and kind counts fade with their half-lives; person threat with 20 minutes.
        p: persona [person]."""
        dt = now - self.counts_at
        if dt <= 0.0:
            return
        k = halve(dt, p["repeat_half_life"])
        self.repeats = {kind: n * k for kind, n in self.repeats.items() if n * k > 0.01}
        kh = halve(dt, p["kind_half_life"])
        self.kind *= kh
        self.looks *= kh
        self.threat *= halve(dt, p["threat_half_life"])
        self.counts_at = now


@dataclass
class Prospect:
    """Something that might still happen, and colors her feelings while it's open
    (OCC's prospect emotions). When it settles it turns into relief, pride,
    disappointment or "it happened"."""
    kind: str  # exposure, change, joke, win, leaving, risky, glitch
    who: str  # the person it's about ("chat" for chat)
    q: float  # how strongly it was expected or feared (0..1)
    opened: float
    ttl: float | None  # seconds until it times out (None: never during a stream)
    peak: float = 0.0  # the feeling it opened with (relief and the like scale with it)
    note: str = ""
    data: dict = field(default_factory=dict)  # a stance's claim, topic, challenges...

    def age(self, now: float) -> float:
        return now - self.opened

    def expired(self, now: float) -> bool:
        return self.ttl is not None and now - self.opened >= self.ttl

    def item(self, now: float) -> dict:
        return {"kind": self.kind, "who": self.who, "q": round(self.q, 2), "age_s": round(self.age(now), 1),
                "ttl_s": None if self.ttl is None else round(max(0.0, self.ttl - self.age(now)), 1), "note": self.note}
