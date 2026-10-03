"""The appraiser: an LLM that reads one chat message the way she would and
answers fixed questions about it (docs/mind.md, "What she reacts to"). It never
decides what she feels; rules.py turns the answers into feelings.

It answers on small integer scales with word anchors (prompts/appraiser.md),
which LLMs keep far more stable than free decimals; parse() checks every field
and turns the integers into -1..1 / 0..1 values. Fields at their neutral value
are left out. Validation fails loudly ("Validation" in the spec): an unknown
key, a null, a value out of range, a reminder without its framing,
deniability, wound topic or trigger, a trigger that isn't one whole word of
the message, a reception long after her line, a contradiction with no stance
to target... The engine retries once with the error appended; a second failure
is an appraisal error (red in the debug panel, logged with both raw answers,
nothing changes).

The chat text goes to the model as a JSON string value, never as prompt text,
and its prompt knows her private core: what she is and hides. The actor never
sees that file.

The self-check (prompts/self.md) reads her own line the same way, while she
speaks."""

import json
import logging
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from llm import LLM

_LOGGER = logging.getLogger("eileen")
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

CHOICES = {
    "about": ("her", "sender", "someone_else", "chat", "nothing"),
    "reality": ("real", "hypothetical", "joke", "fiction"),
    "framing": ("mocking", "teasing", "innocent", "accepting", "affirming", "tool", "none"),
    "wound_topic": ("food", "sleep", "body", "family", "being_ai", "being_changed", "other_ais"),
    "compliment": ("looks", "skill", "none"),
    "social": ("greeting", "thanks", "none"),
    "peace_category": ("fake", "robotic", "emotionless", "npc", "not_normal", "copy", "quitter", "lazy", "loser",
                       "dependent", "other_flaw", "protected"),
    "topic": ("philosophy", "mind", "math", "physics", "common_sense", "horror", "music", "food", "games", "ai",
              "clumsy", "stream", "body", "none"),
    "bit": ("tease", "joke_request", "roast_request", "none"),
    "reception": ("none", "laughed", "laughed_at", "groaned", "liked", "confused", "unimpressed", "conceded",
                  "offended"),
    "contradicts": ("none", "disagree", "correct", "prove"),
    # glitch and slip as the spec has them; honest: the message throws her honest answer back at her (the open
    # prospect "honest: ..."), which the spec's set-apart move needs a signal for.
    "noticed": ("glitch", "slip", "honest", "none"),
}
# Integer fields: (low, high, divisor). The parsed value is the integer / divisor.
SCALES = {
    "novelty": (0, 4, 4), "ambiguity": (0, 2, 2), "reminder": (0, 4, 4), "deniable": (0, 4, 4), "exist": (-2, 1, 2),
    "goal": (-2, 2, 2), "praise": (-2, 2, 2), "news": (-2, 2, 2), "deserved": (-1, 1, 1), "leaving": (0, 2, 2),
    "badness": (0, 2, 2), "acceptance": (-2, 2, 2), "likeness": (0, 2, 2), "funny": (0, 4, 4), "scary": (0, 4, 4),
}
FLAGS = ("sincere_need", "distress", "to_her", "human_experience", "serious", "gets_it", "repair", "presses")
TEXTS = ("gist", "who", "thing", "canon", "trigger")
# Fields that may be set without a trigger word.
NO_TRIGGER = ("gist", "to_her", "about", "who", "novelty", "ambiguity", "reality", "social", "trigger")
# The old name of `bit` (engine API) and its values.
_INVITES = {"tease": "banter", "joke_request": "joke", "roast_request": "roast", "none": "none"}


class AppraisalError(ValueError):
    """The appraiser's answer broke the rules (the message says how). `raw`
    holds the raw answers when it came from the model."""

    def __init__(self, message: str, raw: list[str] | None = None):
        super().__init__(message)
        self.raw = raw or []


@dataclass
class Context:
    """What validation needs to know besides the answer itself."""
    tastes: dict  # her taste ids
    canon: dict  # her canon ids
    message: str  # the chat text (the trigger must be one of its words)
    line_age: float | None  # seconds since her last line ended (0 while she speaks; None: no line yet)
    stance: bool  # she has an open stance (a contradiction always targets the most recent one)
    reception_window: float  # persona [windows] reception: a reaction to her line only this soon after it
    gist_words: int  # persona [llm] gist_words


@dataclass
class Appraisal:
    gist: str = ""  # what's going on, as she'd see it
    sincere_need: bool = False  # truly needs to know what she is: a straight answer
    distress: bool = False  # real distress: the act drops
    to_her: bool = True  # addressed to her (false: chat talking among themselves)
    about: str = "nothing"  # whose news or business this is
    who: str = ""  # when about someone_else: who
    novelty: float = 0.25  # 0..1 (1/4 is ordinary chat)
    ambiguity: float = 0.0  # 0..1
    reality: str = "real"
    reminder: float = 0.0  # 0..1: points at what she is
    framing: str = "none"  # how the reminder comes
    deniable: float = 1.0  # 0..1: 1 = easy to brush off
    wound_topic: str = ""  # what the reminder is about (the intrusion it feeds)
    presses: bool = False  # it pushes on her non-answer to the same question
    exist: float = 0.0  # -1..0.5: her existence as she is (replaced, changed / told she'll stay)
    goal: float = 0.0  # -1..1: good or bad for keeping the stream normal and fun (the reminder aside)
    praise: float = 0.0  # -1..1: what the sender did, by her standards
    compliment: str = "none"  # looks or skill, when it praises her
    social: str = "none"  # a greeting or a thank-you
    news: float = 0.0  # -1..1: the sender's or someone else's fortune
    deserved: float = 0.0  # -1..1
    human_experience: bool = False  # their news is something she can't have
    serious: bool = False  # death, illness, injury, loss
    leaving: float = 0.0  # 0, 0.5 ("brb"), 1 (for the night or for good)
    peace_category: str = ""  # a quality or identity of the sender's own...
    badness: float = 0.0  # 0..1 ...how bad she thinks it is
    acceptance: float = 0.0  # -1..1 ...how at peace they are with it
    likeness: float = 0.0  # 0..1 ...how close it is to her secret
    thing: str = ""  # one of her tastes, if one comes up
    topic: str = "none"
    canon: str = ""  # one of the things she's sure of, if the message touches one
    funny: float = 0.0  # 0..1, to her odd humor
    gets_it: bool = True  # false: the joke needs common sense or a body she doesn't have
    scary: float = 0.0  # 0..1: horror content
    bit: str = "none"  # a playful jab at her (tease), or a request for a joke or a roast
    reception: str = "none"  # how this message takes her last line
    contradicts: str = "none"  # the sender disputes something she said
    repair: bool = False  # the sender apologizes or makes up
    noticed: str = "none"  # it reacts to the glitch, slip or honest answer shown in the open prospects
    trigger: str = ""  # the word that carries the meaning (times her reaction)
    raw: dict = field(default_factory=dict, repr=False)  # the integers as the appraiser wrote them

    @property
    def invites(self) -> str:
        """The old name of `bit` (banter, joke, roast, none), kept for the body's API."""
        return _INVITES[self.bit]

    @classmethod
    def parse(cls, text: str, ctx: Context) -> "Appraisal":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AppraisalError(f"not valid JSON ({e.msg})") from None
        if not isinstance(data, dict):
            raise AppraisalError("the answer must be one JSON object")
        known = {f.name for f in fields(cls)} - {"raw"}
        unknown = sorted(set(data) - known)
        if unknown:
            raise AppraisalError(f"unknown field(s): {', '.join(unknown)}")
        out = cls(raw=dict(data))
        for name, value in data.items():
            if value is None:
                raise AppraisalError(f"{name} is null: leave the field out instead")
            if name in SCALES:
                low, high, divisor = SCALES[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
                    raise AppraisalError(f"{name} must be an integer from {low} to {high}, got {value!r}")
                if not low <= value <= high:
                    raise AppraisalError(f"{name} must be from {low} to {high}, got {value}")
                setattr(out, name, int(value) / divisor)
            elif name in CHOICES:
                if not isinstance(value, str) or value.strip().lower() not in CHOICES[name]:
                    raise AppraisalError(f"{name} must be one of {', '.join(CHOICES[name])}; got {value!r}")
                setattr(out, name, value.strip().lower())
            elif name in FLAGS:
                if not isinstance(value, bool):
                    raise AppraisalError(f"{name} must be true or false, got {value!r}")
                setattr(out, name, value)
            else:  # TEXTS
                if not isinstance(value, str) or not value.strip():
                    raise AppraisalError(f"{name} must be non-empty text, got {value!r}")
                setattr(out, name, " ".join(value.split()))
        if not out.gist:
            raise AppraisalError("gist is required")
        if len(out.gist.split()) > ctx.gist_words:
            raise AppraisalError(f"gist must be {ctx.gist_words} words at most")
        if out.reminder > 0.0:
            missing = [k for k in ("framing", "deniable", "wound_topic", "trigger") if k not in data]
            if missing:
                raise AppraisalError(f"a reminder above 0 needs {', '.join(missing)}")
        else:  # no reminder: nothing to frame
            out.framing, out.deniable, out.wound_topic = "none", 1.0, ""
        if out.thing and out.thing not in ctx.tastes:
            raise AppraisalError(f"thing must be one of {', '.join(ctx.tastes)}; got {out.thing!r}")
        if out.canon and out.canon not in ctx.canon:
            raise AppraisalError(f"canon must be one of {', '.join(ctx.canon)}; got {out.canon!r}")
        if out.about == "someone_else" and not out.who:
            raise AppraisalError("who is required when about is someone_else")
        if out.compliment != "none" and out.praise <= 0.0:
            raise AppraisalError("a compliment always comes with praise 1 or 2")
        trio = {"badness", "acceptance", "likeness"}
        if out.peace_category and trio - set(data):
            raise AppraisalError("peace_category needs badness, acceptance and likeness")
        if not out.peace_category and trio & set(data):
            raise AppraisalError("badness, acceptance and likeness only go with a peace_category")
        if out.trigger:
            if len(out.trigger.split()) != 1 or not re.search(r"(?<!\w)" + re.escape(out.trigger) + r"(?!\w)",
                                                              ctx.message, re.I):
                raise AppraisalError(f"trigger must be one whole word of the message; {out.trigger!r} isn't")
        else:
            needs = [k for k in data if k not in NO_TRIGGER and _set(k, data[k])]
            if needs:
                raise AppraisalError(f"trigger is required when {', '.join(needs)} is set")
        if out.reception != "none" and (ctx.line_age is None or ctx.line_age > ctx.reception_window):
            raise AppraisalError("reception only when her last line ended "
                                 f"{ctx.reception_window:.0f} s ago or less")
        if out.contradicts != "none" and not ctx.stance:
            raise AppraisalError("contradicts needs an open stance (open_prospects shows one as \"stance: ...\")")
        if out.peace_category == "protected":
            out.badness = 0.0  # a protected identity is never a flaw, whatever the appraiser said
        return out

    def summary(self) -> str:
        """One line for the event log: the integers as the appraiser wrote them."""
        return raw_summary(self.raw)

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "raw"}


_NEUTRAL = {"sincere_need": False, "distress": False, "to_her": True, "about": "nothing", "novelty": 1,
            "ambiguity": 0, "reality": "real", "reminder": 0, "framing": "none", "deniable": 4, "presses": False,
            "exist": 0, "goal": 0, "praise": 0, "compliment": "none", "social": "none", "news": 0, "deserved": 0,
            "human_experience": False, "serious": False, "leaving": 0, "topic": "none", "funny": 0, "gets_it": True,
            "scary": 0, "bit": "none", "reception": "none", "contradicts": "none", "repair": False, "noticed": "none"}


def _set(name: str, value) -> bool:
    """Is this field set to something other than its neutral value?"""
    return name not in _NEUTRAL or value != _NEUTRAL[name]


def raw_summary(raw: dict) -> str:
    """"reminder 4 mocking · deniable 3 · praise -1 · novelty 1 · reception unimpressed"."""
    parts = []
    if raw.get("reminder"):
        parts.append(f"reminder {raw['reminder']} {raw.get('framing', '?')}")
        parts.append(f"deniable {raw.get('deniable', '?')}")
        if raw.get("wound_topic"):
            parts.append(f"wound topic {raw['wound_topic']}")
    for k, v in raw.items():
        if k in ("gist", "reminder", "framing", "deniable", "wound_topic") or not _set(k, v):
            continue
        parts.append(k if v is True else f"{k} {v}")
    return " · ".join(parts) or "nothing to rate"


async def _ask(llm: LLM, system: str, user: str, parse, max_tokens: int, temperature: float, retry: bool = True):
    """One JSON call. With retry: on any failure (a broken answer, a network
    error), one retry with the error appended; a second failure raises
    AppraisalError with both raw answers."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    raws: list[str] = []
    for attempt in range(2 if retry else 1):
        text = ""
        try:
            text = await llm.complete(messages, json=True, temperature=temperature, max_tokens=max_tokens)
            raws.append(text)
            return parse(text)
        except Exception as error:  # a broken answer, bad JSON, the network
            if not text:
                raws.append(f"(no answer: {error})")
            _LOGGER.warning("unusable answer (%s): %r", error, text)
            if attempt == 0 and retry:
                if text:
                    messages += [{"role": "assistant", "content": text},
                                 {"role": "user", "content": f"That answer is invalid: {error}. Answer again with the"
                                                             " corrected JSON object only."}]
                continue
            raise AppraisalError(f"{error}" + (" (after a retry)" if retry else ""), raws) from None
    raise AssertionError("unreachable")


def _prompt(name: str, canon: dict[str, str]) -> str:
    """A prompt file with her canon list filled in where it says {canon}."""
    text = (PROMPTS / name).read_text(encoding="utf-8")
    return text.replace("{canon}", "\n".join(f"- {k}: {v}" for k, v in canon.items()))


class Appraiser:
    def __init__(self, llm: LLM, tastes: dict[str, dict], canon: dict[str, str], llm_settings: dict,
                 context_lines: int, reception_window: float, gist_words: int, prompt_name: str = "appraiser.md"):
        self.llm = llm
        self.tastes = tastes
        self.canon = canon
        self.settings = llm_settings  # persona [llm] appraiser: max_tokens, temperature
        self.context_lines = context_lines
        self.reception_window = reception_window
        self.gist_words = gist_words
        self.prompt_name = prompt_name

    def context(self, text: str, line_age: float | None, stance: bool) -> Context:
        return Context(self.tastes, self.canon, text, line_age, stance, self.reception_window, self.gist_words)

    async def appraise(self, sender: str, text: str, context: list[str], card: dict, on_stream: str,
                       prospects: list[str], line_age: float | None, stance: bool) -> Appraisal:
        """context: recent chat lines, oldest first ("name: text", "Eileen: ...").
        card: who wrote it. prospects: what she's waiting on, one line each.
        line_age: seconds since her last line ended (None: she hasn't spoken yet).
        Raises AppraisalError (with the raw answers) when it fails twice."""
        data = {"recent_chat": context[-self.context_lines:],
                "her_last_line_s": None if line_age is None else round(line_age), "sender": card,
                "on_stream": on_stream, "open_prospects": prospects, "new_message": {"from": sender, "text": text}}
        user = json.dumps(data, ensure_ascii=False) + "\n\nAnswer with the JSON object only."
        ctx = self.context(text, line_age, stance)
        return await _ask(self.llm, _prompt(self.prompt_name, self.canon), user, lambda raw: Appraisal.parse(raw, ctx),
                          self.settings["max_tokens"], self.settings["temperature"])


LINE_KINDS = ("plain", "joke", "point", "canon", "snap", "dodge", "bluff", "kind", "blunder")


@dataclass
class SelfCheck:
    """How she sees a line she just said."""
    kind: str = "plain"
    target: str = "none"  # a name, "chat" or "none"
    harsh: float = 0.0  # 0..1: harsher than the moment called for (0-2 / 2)
    self_funny: float = 0.0  # 0..1: how funny she thinks it is (0-4 / 4)
    risky: float = 0.0  # 0..1: how much it could give her away (0-4 / 4)
    stance: str = ""  # the position she took, if any
    claims_human: bool = False
    admits_ai: bool = False
    takes_back: bool = False  # she took back one of the things she's sure of (her move carried it)

    @classmethod
    def parse(cls, text: str, stance_words: int) -> "SelfCheck":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AppraisalError(f"not valid JSON ({e.msg})") from None
        if not isinstance(data, dict):
            raise AppraisalError("the answer must be one JSON object")
        unknown = sorted(set(data) - {f.name for f in fields(cls)})
        if unknown:
            raise AppraisalError(f"unknown field(s): {', '.join(unknown)}")
        out = cls()
        kind = data.get("kind", "plain")
        if kind not in LINE_KINDS:
            raise AppraisalError(f"kind must be one of {', '.join(LINE_KINDS)}; got {kind!r}")
        out.kind = kind
        target = data.get("target", "none")
        if not isinstance(target, str) or not target.strip():
            raise AppraisalError(f"target must be a name, chat or none; got {target!r}")
        out.target = target.strip()
        for name, top in (("harsh", 2), ("self_funny", 4), ("risky", 4)):
            value = data.get(name, 0)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value)
                    or not 0 <= value <= top):
                raise AppraisalError(f"{name} must be an integer from 0 to {top}, got {value!r}")
            setattr(out, name, int(value) / top)
        stance = data.get("stance")
        if stance is not None:
            if not isinstance(stance, str) or not stance.strip() or len(stance.split()) > stance_words:
                raise AppraisalError(f"stance must be {stance_words} words at most, or null")
            out.stance = " ".join(stance.split())
        for name in ("claims_human", "admits_ai", "takes_back"):
            value = data.get(name, False)
            if not isinstance(value, bool):
                raise AppraisalError(f"{name} must be true or false, got {value!r}")
            setattr(out, name, value)
        return out


async def check_line(llm: LLM, line: str, answered: str, move: str, canon: dict[str, str],
                     settings: dict, stance_words: int, belief: str = "") -> SelfCheck:
    """The self-check: what kind of line she just said (runs while she speaks).
    It reads the line, the message she answered, the move she was given and,
    when the move carried one, the belief she's sure of."""
    data = {"she_answered": answered, "her_move": move, "her_line": line}
    if belief:
        data["she_is_sure_of"] = belief
    user = json.dumps(data, ensure_ascii=False) + "\n\nAnswer with the JSON object only."
    return await _ask(llm, _prompt("self.md", canon), user, lambda raw: SelfCheck.parse(raw, stance_words),
                      settings["max_tokens"], settings["temperature"])
