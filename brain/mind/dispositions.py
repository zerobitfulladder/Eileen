"""What the actor (the LLM writing her lines) is told right now (docs/mind.md,
"Right now").

Only behavior: how she's acting at the moment and what to do with this
message. Never emotion names, numbers, what she wants, or why. The actor
performs the state without knowing it, so when someone asks why she's being
short, she answers the way people do: with a reason that isn't the real one.

Fixed slots, in this order:

    Right now:
    - {energy line, if any}
    - {length line}
    - {a line about the sender, if any}
    - Do this: {the move}
      {two shape examples, only for a scheduled misfire}
    - Don't: {one prohibition}
    - Don't: {another prohibition}
    - On your mind: {an ordinary topic}
    - On your mind: {another}

The word check (lint) runs on every line before use. One leaked word
("because", "real") lets a strong LLM work out the subtext and play it on the
nose, which destroys the irony, so a violation is an error (red in the debug
panel, a failed test), never a silent fix. Exempt: the filled-in slots ({name},
{who}, quoted lines, her canon belief), the shape examples, and the crisis
line. Every text lives in persona.toml."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .coping import Coping
from .persona import PAD, Persona
from .rules import MindState, active_prohibits, engagement
from .state import Person


def make_lint(words: list[str]) -> Callable[[str], list[str]]:
    """The word check: whole words, any case."""
    pattern = re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
                         + r")(?!\w)", re.I)
    return lambda text: sorted({m.group(1).lower() for m in pattern.finditer(text)})


def blank(template: str, fill: dict) -> str:
    """The template with its slots blanked out (the slots are exempt from the word check)."""
    return template.format(**{k: "X" for k in fill}) if fill else template


def sender_line(s: MindState, persona: Persona, person: Person, now: float, replies: int) -> tuple[str, dict] | None:
    """The "Right now" line about the sender (first match), and the panel's line about them.
    replies: her replies so far (the one being written is replies + 1)."""
    rn, pp = persona["right_now"], persona["person"]
    lines = rn["sender"]
    e = s.emotions
    name = person.name
    if person.latch:
        return lines["latch"], {"name": name}
    if now < person.guilt_until:
        lo, hi = rn["make_up"]
        if person.liking >= pp["friendly"] and lo <= replies + 1 - person.snap_reply <= hi:
            return lines["make_up"], {"name": name}
        return lines["nicer"], {"name": name}
    if any(x["who"] == name for x in active_prohibits(s, now) if x["kind"] in ("news", "distress")):
        return lines["rough"], {"name": name}
    if e["irritation"].aimed_at(name) + e["anger"].aimed_at(name) > rn["short_with"]:
        return lines["short"], {"name": name}
    if person.liking >= pp["liked"]:
        return lines["known"], {"name": name}
    return None


@dataclass
class Disposer:
    """Builds "Right now". The energy line is sticky: it changes at most once per
    30 s, and its conditions have a +-0.05 band, so it doesn't flicker."""
    persona: Persona
    energy: str = ""
    energy_at: float = -1e9
    errors: list[str] = field(default_factory=list)
    length_key: str = ""  # the length line of the last "Right now" (the scenario battery checks the reply against it)

    def __post_init__(self) -> None:
        self.lint = make_lint(self.persona["lint"]["words"])

    def _energy(self, s: MindState, now: float, suppression: float, fatigue: float, covering: bool,
                after_honest: bool, person: Person | None = None) -> str:
        P = self.persona
        rn = P["right_now"]
        th, band = rn["thresholds"], rn["energy_band"]
        dp, da, dd = (s.mood[k].value - s.mood[k].rest for k in PAD)
        values = {"hiding": suppression - P["suppression"]["short"], "tired": fatigue - P["fatigue"]["winding_down"],
                  "low": -dp - th["low"], "quick": da - th["quick"], "playful": dp - th["playful"],
                  "slow": -da - th["slow"], "hedge": -dd - th["hedge"]}
        showing = "low" if self.energy == "prickly" else self.energy

        def holds(key: str) -> bool:
            """Entering needs the band past the line; the line showing holds until the band below it."""
            return values[key] > (-band if key == showing else band)

        if covering:
            key = "cover"
        elif after_honest:
            key = "after_honest"
        else:
            key = next((k for k in ("hiding", "tired", "low", "quick", "playful", "slow", "hedge") if holds(k)), "")
            e = s.emotions
            if key == "low" and (e["irritation"].value + e["anger"].value + e["contempt"].value
                                 > e["sadness"].value + e["shame"].value + e["anxiety"].value):
                key = "prickly"  # low mood from pokes, not from sadness
        if key != self.energy and now - self.energy_at >= rn["energy_hold"]:
            self.energy, self.energy_at = key, now
        shown = self.energy
        if shown == "prickly" and person is not None and person.liking >= P["person"]["liked"]:
            e = s.emotions
            if e["irritation"].aimed_at(person.name) + e["anger"].aimed_at(person.name) < rn["prickly_friend"]:
                shown = "low"  # the pokes came from someone else: no shortness with a friend
        return rn["energy"][shown] if shown else ""

    def right_now(self, s: MindState, person: Person | None, coping: Coping, topics: list[tuple[str, dict]], rung: str,
                  now: float, suppression: float, fatigue: float, covering: bool, after_honest: bool,
                  replies: int, on_stream: str = "") -> str:
        """topics: the "On your mind" lines as (template, fill), most salient first."""
        P = self.persona
        rn = P["right_now"]
        lines: list[tuple[str, dict, bool]] = []  # (template, fill, linted)
        move = coping.move
        energy = self._energy(s, now, suppression, fatigue, covering, after_honest, person)
        if energy and move not in rn["own_mood"] and not coping.slip:
            lines.append((energy, {}, True))
        if move == "crack":
            self.length_key = "crack"
        else:
            en = P["engagement"]
            if covering:
                self.length_key = "strained"
            elif move in rn["long"]:
                self.length_key = "long"
            elif move in rn["question"]:
                self.length_key = "question"
            elif rung == "composed" and move in en["moves"]:  # into it, she opens up
                x = engagement(s, P, person)
                self.length_key = "lit" if x >= en["lit"] else "open" if x >= en["open"] else "composed"
            else:
                self.length_key = rung
            lines.append((rn["length"][self.length_key], {}, True))
        if person is not None and move != "crisis":
            line = sender_line(s, P, person, now, replies)
            if line is not None:
                lines.append((*line, True))
        lines.append(("Do this: " + coping.template, coping.fill, move != "crisis"))
        if coping.examples:
            label = rn["crack_examples"] if move == "crack" else rn["examples"]
            lines.append((f"  {label}: " + " / ".join(coping.examples), {}, False))
        active = active_prohibits(s, now)
        distressed = {x["who"] for x in active if x["kind"] == "distress"}  # "Don't: joke." covers their news
        donts = [(rn["prohibit"][x["kind"]], {"who": x["who"]} if x["kind"] == "news" else {})
                 for kind in ("distress", "news") for x in active if x["kind"] == kind
                 and not (kind == "news" and x["who"] in distressed)]
        donts += [(d, {}) for d in coping.donts]
        lines += [("Don't: " + template, fill, True) for template, fill in donts[:rn["donts"]]]
        lines += [("On your mind: " + template, fill, True) for template, fill in topics[:rn["mind"]]]
        if on_stream:  # what chat can see her doing (she invented games she was "playing" without it)
            lines.append((rn["on_stream"], {"activity": on_stream}, True))
        self.errors = []
        for template, fill, linted in lines:
            bad = self.lint(blank(template, fill)) if linted else []
            if bad:
                self.errors.append(f"word check: {', '.join(bad)} in \"{template.format(**fill)}\"")
        out = [template.format(**fill) for template, fill, _ in lines]
        return "Right now:\n" + "\n".join(line if line.startswith("  ") else f"- {line}" for line in out)
