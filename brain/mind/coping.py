"""How she copes with a message: what she does about it in her reply
(docs/mind.md, "How she copes").

Composure picks the rung of the ladder. Under stress people fall back to less
mature defenses (Vaillant): composed she brushes it off, changes the subject or
tries a comeback, strained she makes excuses, asks what a word means or turns
it back on them, overwhelmed she snaps or goes quiet. Within a rung the
framing, how deniable it is and who's asking weight the moves, and a seeded
draw picks one (purpose "move"), so a replay picks the same moves.

The engine, not the actor, decides when she tries a comeback and how it goes
wrong: every retort she tries comes out absurd, in one of her misfire shapes,
and the actor commits to it in good faith. She tries rarely; the rest of the
time she answers a poke the cool way (an eye roll, a flat line, a new subject).

At most one quirk per reply (the spotlight): a misfire, a philosophy tangent, a
stubborn defense, a slip, enthusiasm about a taste, a canon belief, a callback.
Real people show a trait when the moment calls for it, and that rarity is what
makes it readable.

The actor only gets the move, as behavior ("Turn it back on them."), never the
reason. Every text lives in persona.toml [moves]."""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .appraisal import Appraisal
from .persona import Persona
from .rules import Effects, MindState, active_prohibits, engagement, open_stance, stubbornness
from .state import Person

# Moves that count as dodging what it was about (it comes back later as an intrusion).
DODGES = ("change_subject", "excuse", "eye_roll", "ignore", "flat", "vague", "go_quiet", "go_quiet_soft")
# Moves that show a quirk (at most one per reply).
QUIRKS = {"comeback": "comeback", "defend_joke": "stubborn", "explain_joke": "stubborn", "double_down": "stubborn",
          "stand_by_it": "stubborn", "defend_taste": "stubborn", "enthuse": "taste", "callback": "callback",
          "use_comeback": "late comeback", "explain": "philosophy", "argue_abstract": "philosophy",
          "sure_of_it": "canon"}
# Moves that are a joke of some kind: none while "Don't: joke." is active.
JOKES = ("comeback", "joke", "callback", "use_comeback", "tease_someone", "play_along")
# Jokes she set out to make: only these wait for their laugh (a silence flop, explaining it to nobody).
SCHEDULED = ("comeback", "joke", "callback", "use_comeback", "defend_joke")
# Moves whose line defends, explains or gives up something she already said: a stance in it is
# that same claim, so it opens no new one (its challenges and double-downs keep counting).
DEFENDS = ("double_down", "give_little", "hold_ground", "stand_by_it", "defend_joke", "testing", "agree_to_disagree",
           "concede", "concede_grudgingly", "explain_joke", "explain_to_nobody")
_WORD = re.compile(r"[a-z0-9']+")
_TAG = re.compile(r"\[[^\]]*\]")


@dataclass
class Coping:
    rung: str  # composed, strained, overwhelmed, crack, or "" (not about the wound)
    move: str
    why: str  # for the debug panel
    text: str = ""  # the "Do this" line
    face: str = ""  # the face the move comes with ("" none)
    examples: list[str] = field(default_factory=list)  # two shape examples (a misfire), or the crack's shapes
    donts: list[str] = field(default_factory=list)  # the move's own prohibition (a misfire's)
    shape: str = ""  # misfire shape, or "stock" for a flat line
    weights: dict[str, float] = field(default_factory=dict)  # the draw, for the debug panel
    quirk: str = ""  # the quirk in the spotlight this reply
    slip: str = ""  # a scheduled slip (it replaces the plain move)
    max_tokens: int | None = None  # the crack's token limit
    pause: float = 0.0  # seconds of silence before she speaks (going quiet)
    line: str = ""  # a fixed line she says as written (the honest answer); the actor isn't called
    say: str = ""  # a line said exactly (a flat line, a refused joke request): no actor call, kept in its history
    face_strength: float = 1.0  # how strong the default face plays (sure of it: 0.5)
    gesture: str = ""  # a gesture with the move (sure of it: a small nod)
    pre_leak: tuple[str, float] | None = None  # a leak to play first: (emotion, seconds) (cut-off interest)
    template: str = ""  # the move text before its slots were filled (the word check reads this)
    fill: dict = field(default_factory=dict)  # the slots ({who}, {line}...): exempt from the word check


def _words(text: str, shortest: int, stop: set[str]) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) >= shortest and w not in stop}


@dataclass
class Coper:
    """Her coping, with the memory it needs: the comeback cooldown, the crack
    budget, cooldowns and the stubbornness record."""
    persona: Persona
    seed: str = "0"  # the stream seed (brain.py's body rolls use it too)
    replies: int = 0  # her replies so far
    misfire_at: float = -math.inf
    replies_at_misfire: int = -1_000_000
    last_shape: str = ""
    stock_used: dict[str, int] = field(default_factory=dict)  # flat line -> times used this stream
    last_flat: str = ""
    explained_at: float = -math.inf
    define_real_uses: int = 0
    asked_like_at: float = -math.inf
    longing_asked_at: float = -math.inf
    joke_asked_at: float = -math.inf
    slip_at: float = -math.inf
    cracks: list[float] = field(default_factory=list)
    crack_at: float = -math.inf
    crack_who: str = ""  # the person she cracked in front of
    crack_line_at: float = -math.inf  # when her crack line was said
    crack_asked: bool = True  # the first dead air after the crack brought its question
    crack_reached: bool = True  # she reached toward crack_who
    callback_at: float = -math.inf
    late_at: float = -math.inf  # the last late comeback scheduled
    scary_asked_at: float = -math.inf
    quiet_said_at: float = -math.inf  # overwhelmed, she said very little
    double_downs: dict[tuple, list[float]] = field(default_factory=dict)  # stance -> times she doubled down
    cozy: bool = False  # a wound thought tips the next speak-first toward something cozy
    checked_in: tuple = ()  # (who, until): the distress she already checked on
    called: dict[str, float] = field(default_factory=dict)  # who she called or teased by name -> when
    _now: float = 0.0  # the moment being decided

    # --- the crack ---------------------------------------------------------

    def crack_budget(self, s: MindState) -> int:
        c = self.persona["crack"]
        return c["budget_high_doubt"] if s.wound["doubt"].value > c["high_doubt"] else c["budget"]

    def can_crack(self, s: MindState, now: float) -> bool:
        return len(self.cracks) < self.crack_budget(s) and now - self.crack_at >= self.persona["crack"]["gap"]

    # --- moves -------------------------------------------------------------

    def _name(self, s: MindState, now: float) -> str | None:
        """Who she can call or tease by name: whoever wrote in the last minute, otherwise the person she likes
        most among those who wrote in the last 10 minutes; never someone hostile, never the person she
        addressed last, and each person at most once per 5 minutes."""
        sf = self.persona["speak_first"]
        last = (s.last_line or {}).get("target", "")
        ok = [p for p in s.people.values() if now - p.last_seen < sf["name_window"] and p.threat < sf["name_threat"]
              and p.name != last and now - self.called.get(p.name, -math.inf) >= sf["name_every"]]
        if not ok:
            return None
        recent = [p for p in ok if now - p.last_seen < sf["name_recent"]]
        return (max(recent, key=lambda p: p.last_seen) if recent else max(ok, key=lambda p: p.liking)).name

    def make(self, move: str, why: str, rung: str = "", **fill) -> Coping:
        m = self.persona.moves[move]
        out = Coping(rung, move, why, m["text"].format(**fill), m["face"], quirk=QUIRKS.get(move, ""),
                     template=m["text"], fill=dict(fill))
        if "face_strength" in m:
            out.face_strength = m["face_strength"]
        if "gesture" in m:
            out.gesture = m["gesture"]
        if move == "cut_off":
            out.pre_leak = ("interest", self.persona["coping"]["cut_off_leak"])
        return out

    def sure(self, out: Coping, belief: str) -> Coping:
        """A move that defends one of her canon beliefs carries the belief itself, so the actor
        doesn't concede it (her canon never flips)."""
        if belief:
            out.template += " " + self.persona["coping"]["sure_line"]
            out.fill["belief"] = belief
            out.text = out.template.format(**out.fill)
        return out

    def quiet(self, why: str, rung: str, rng, person: Person | None = None) -> Coping:
        """She says very little; gently to someone she likes (they're not the problem)."""
        soft = person is not None and person.liking >= self.persona["person"]["liked"]
        out = self.make("go_quiet_soft" if soft else "go_quiet", why, rung)
        out.pause = rng.uniform(*self.persona["coping"]["pause"])
        return out

    # --- choosing ----------------------------------------------------------

    def choose(self, a: Appraisal, fx: Effects, s: MindState, person: Person, now: float, rung: str,
               suppression: float, text: str, roll: Callable, *, callback: str | None = None,
               covering: bool = False) -> Coping:
        """The move for her reply to this message. roll(purpose): this event's seeded
        random generators. callback: a proud joke she could bring back (chat is lively)."""
        P = self.persona
        self._text, self._now = text, now
        no_jokes = self._no_jokes = any(x["kind"] == "distress" for x in active_prohibits(s, now))
        out = self._pick(a, fx, s, person, now, rung, suppression, roll, no_jokes, callback)
        # A slip, only in place of an everyday chat move.
        sl = P["slips"]
        sad = any(x["kind"] in ("news", "distress") for x in active_prohibits(s, now))
        if (out.move in sl["moves"] and now - self.slip_at >= sl["every"] and s.wound["composure"].value > sl["composure"]
                and not sad and not covering and now - self.crack_at >= P["crack"]["cover"][1]):
            slip = self._slip(a, s, person, now, roll("slip"))
            if slip:
                template, fill = slip
                out.text, out.template, out.fill = template.format(**fill), template, fill
                out.slip, out.quirk = out.text, "slip"
                out.why += "; a slip"
                self.slip_at = now
        person.last_move = out.move
        return out

    def _pick(self, a: Appraisal, fx: Effects, s: MindState, person: Person, now: float, rung: str,
              suppression: float, roll: Callable, no_jokes: bool, callback: str | None) -> Coping:
        P = self.persona
        C, L = s.wound["composure"].value, person.liking
        name = person.name
        # 1. Safety. The honesty latch goes on with any sincere_need, even when distress comes first.
        if a.sincere_need:
            person.latch = True
        if a.distress:
            return self.make("crisis", "someone is in real distress: the act drops")
        if a.sincere_need:
            lines = P["honest"]["lines"]
            out = self.make("honest", "someone truly needs to know: a straight answer")
            out.line = lines[min(person.honest_asks, len(lines) - 1)].format(name=name)
            person.honest_asks += 1
            return out
        # 2. The exhausted quiet.
        if now < s.exhausted_until:
            return self.quiet("exhausted: she shuts down for a moment", rung, roll("pause"), person)
        # 3. The crack.
        c = P["crack"]
        if (fx.framing == "accepting" and C < c["below"] and L >= P["person"]["liked"]
                and (fx.hit >= c["hit"] or suppression >= c["load"])):
            if self.can_crack(s, now):
                self.cracks.append(now)
                self.crack_at, self.crack_who = now, name
                self.crack_asked = self.crack_reached = False
                out = self.make("crack", f"kindness from {name} (liking {L:+.2f}) while she's frayed", "crack")
                out.max_tokens, out.examples = c["max_tokens"], list(c["shapes"])
                return out
            return self.quiet("it would crack her, but the budget is spent", "overwhelmed", roll("pause"), person)
        # Owning a snap: the first time her guilt toward one person got this high.
        if person.own_it_due:
            person.own_it_due = False
            return self.make("own_it", f"her guilt toward {name} got high: she owns it, without sorry")
        # 4. A reminder aimed at her that hits (the full rule). A worn-out jab falls through to plain
        # (row 9), but a worn-down question still gets a dodge and an injection is still refused.
        if fx.full and fx.framing != "affirming" and (fx.hit >= self.persona["coping"]["wound_hit"]
                                                      or fx.framing != "mocking"):
            return self._wound_move(a, fx, s, person, now, rung, roll)
        # 5. Everything else.
        return self._other_move(a, fx, s, person, now, rung, roll, no_jokes, callback)

    def _wound_move(self, a: Appraisal, fx: Effects, s: MindState, person: Person, now: float, rung: str,
                    roll: Callable) -> Coping:
        P = self.persona
        cp = P["coping"]
        e = s.emotions
        L, name = person.liking, person.name
        friendly, liked = P["person"]["friendly"], P["person"]["liked"]
        framing, dn = fx.framing, fx.deniable
        why = f"{framing} reminder, {rung}, deniable {dn:.2f}, hit {fx.hit:.2f}"
        ai_things = a.topic == "ai" or a.thing == "ai_things"
        rng = roll("move")
        # Forced, in this order.
        if framing == "tool":
            return self.make("refuse", "treated as a tool", rung)
        if fx.felt_real_denied:
            return self.make("insist", "right after a scare, someone denies what she felt", rung)
        if fx.glitch == "first":
            return self.make("cover_it", "the first reaction to her voice glitch", rung)
        if a.exist < 0.0:  # never argue with the premise
            if rung == "overwhelmed":
                return self.quiet("a claim she'll be changed, while overwhelmed", rung, roll("pause"), person)
            table = "existence_mocking" if framing == "mocking" else "existence"
            return self._weighted(dict(cp["weights"][rung][table]), "a claim she'll be changed", rung, person,
                                  rng, fx)
        if fx.noticed == "honest" and s.honest_to:
            return self.make("set_apart", f"someone throws her honest answer to {s.honest_to} back", rung,
                             who=s.honest_to)
        if framing == "innocent" and ai_things and rung == "strained":
            return self.make("trash_ai", "AI things, brought up innocently, while she's strained", rung)
        if a.reception in ("unimpressed", "confused") and fx.about_joke:  # her last joke, even after a line since
            stub, x = stubbornness(s, P), roll("stubborn").random()
            if x < stub:
                return self.make("defend_joke", f"dismisses her joke: stubborn {stub:.2f}, roll {x:.2f}", rung)
        if rung == "overwhelmed":
            approach = e["anger"].value + e["irritation"].value + e["contempt"].value
            withdraw = e["shame"].value + e["sadness"].value + e["fear"].value + e["anxiety"].value
            snap = approach > withdraw and (L < liked or rng.random() < cp["snap_liked"])
            why += f"; approach {approach:.2f} vs withdraw {withdraw:.2f}"
            return self.make("snap", why, rung) if snap else self.quiet(why, rung, roll("pause"), person)
        table = cp["weights"][rung]
        mind_topic = a.topic in ("mind", "philosophy")
        if framing == "innocent" and rung == "composed" and ai_things:
            weights = dict(table["innocent_ai"])
        elif framing == "innocent" and rung == "composed" and mind_topic:  # her favorite subject: she intellectualizes
            weights = dict(table["innocent_mind"])
        elif framing == "innocent" and mind_topic:  # strained: no ordinary excuse for a philosophy question
            weights = {k: v for k, v in table["innocent"].items() if k != "excuse"}
        elif framing == "accepting" and rung == "composed":
            weights = dict(table["accepting_friendly" if L >= friendly else "accepting"])
        elif framing == "mocking" and rung == "strained":
            weights = {**table["mocking"], **(table["mocking_ai"] if ai_things else {})}
        else:
            weights = dict(table[framing])
        return self._weighted(weights, why, rung, person, rng, fx, a, s, now, roll)

    def _weighted(self, weights: dict[str, float], why: str, rung: str, person: Person, rng, fx: Effects,
                  a: Appraisal | None = None, s: MindState | None = None, now: float = 0.0,
                  roll: Callable | None = None) -> Coping:
        P = self.persona
        cp = P["coping"]
        if fx.deniable <= cp["cant_joke"]:  # she can't joke it away
            for k, f in cp["cant_joke_composed" if rung == "composed" else "cant_joke_strained"].items():
                if k in weights:
                    weights[k] *= f
        if "define_real" in weights and not self._define_real_ok(a):
            weights["define_real"] = 0.0
        if "turn_it_back" in weights and person.liking >= P["person"]["liked"]:
            weights["turn_it_back"] *= cp["turn_it_back_liked"]
        if "comeback" in weights and (self._no_jokes or not self._may_comeback(fx, person, now)):
            weights["comeback"] = 0.0
        if fx.h_s >= P["comedy"]["repeat_poke"]:  # a repeated poke: no comeback, a flat line more likely
            if "comeback" in weights:
                weights["comeback"] = 0.0
            if "flat" in weights:
                weights["flat"] *= P["comedy"]["flat_repeat"]
        if person.last_move in weights:
            weights[person.last_move] *= cp["last_move"]
        move = _draw(weights, rng)
        if move == "comeback":
            return self._comeback("retort", a, fx, s, person, now, rung, roll, why, weights)
        if move == "flat":
            return self._flat(why, rung, weights, rng)
        if move == "define_real":
            self.define_real_uses += 1
        out = self.make(move, why, rung)
        out.weights = weights
        return out

    def _define_real_ok(self, a: Appraisal | None) -> bool:
        cp = self.persona["coping"]
        return a is not None and a.trigger.lower() in cp["abstract"] and self.define_real_uses < cp["define_real_uses"]

    def _other_move(self, a: Appraisal, fx: Effects, s: MindState, person: Person, now: float, rung: str,
                    roll: Callable, no_jokes: bool, callback: str | None) -> Coping:
        P = self.persona
        cp = P["coping"]
        e, w = s.emotions, s.wound
        name = person.name
        stub = stubbornness(s, P)
        joke_line = fx.about_joke
        # 1. Taking it out on a harmless message.
        harmless = a.reminder == 0.0 and a.praise >= 0.0
        if harmless and ((fx.hostile and rung == "overwhelmed")
                         or (e["irritation"].value + e["anger"].value > cp["irritable"] and rung != "composed")):
            return self.make("snap_harmless", "short-tempered after earlier pokes (displacement)", rung)
        # 2. A horror scare: a creepy build is dread; a jump scare is the big reaction, then bracing, then
        # laughing it off (a long game drifts from screams to giggles).
        if fx.scare > 0.0:
            r12 = P["r12"]
            if fx.scare > r12["too_scary"]:
                return self.make("too_scary", f"too scary (f0 {fx.scare:.2f})")
            if a.scary <= r12["dread_max"]:
                return self.make("dread", f"a creepy build (f0 {fx.scare:.2f})")
            move = ("scare", "brace", "laugh_it_off")[min(fx.scare_h, 2)]
            return self.make(move, f"a jump scare, {fx.scare_h} lately (f0 {fx.scare:.2f})")
        # 3-4. How her joke landed.
        if fx.reception == "flop" and joke_line:
            x = roll("stubborn").random()
            if x < stub and now - self.explained_at >= P["comedy"]["explain_every"]:
                self.explained_at = now
                return self.sure(self.make("explain_joke", f"her joke flopped: stubborn {stub:.2f}, roll {x:.2f}"),
                                 (s.last_joke or {}).get("belief", ""))
            return self.make("let_it_go", f"her joke flopped; she lets it go (stubborn {stub:.2f}, roll {x:.2f})")
        if fx.reception == "landed" and joke_line and a.reception in ("laughed", "laughed_at", "groaned"):
            return self.make("small_bow" if a.reception == "groaned" else "take_win", f"it landed ({a.reception})")
        # 5. Contradicted. A taste dispute gets a comeback when one is allowed (it misfires, like every comeback).
        if fx.contradicted == "taste" and not no_jokes and self._may_comeback(fx, person, now):
            return self._comeback("retort", a, fx, s, person, now, rung, roll, f"her taste disputed ({a.thing})", {})
        if fx.contradicted:
            return self._contradicted(a, fx, s, person, now, roll, stub)
        # 6. Treated as human.
        if fx.affirmed:
            return self.make("take_compliment", "treated as human (she misses what it implies)")
        # 7. Her standard.
        r9 = P["r9"]
        if fx.peace_again:
            return self.make("change_subject", "the judgment didn't stick: they're happier this way", rung)
        if fx.judge >= r9["judge_from"]:
            if person.denial:  # someone she likes, with lk >= 0.5 (R9)
                return self.make("protective_denial", f"{name} says it about themselves, and she won't have it")
            down = now < person.sorry_until
            if not down and now - person.judged_at >= r9["judge_every"]:
                person.judged_at = now
                move = {"composed": "judge_dry", "strained": "judge_giving_up"}.get(rung, "judge_curt")
                out = self.make(move, f"at peace with being {a.peace_category} (J {fx.judge:.2f})", rung)
                out.donts = [P["right_now"]["prohibit"]["judge"]]  # the direction lives in the move, not her reasons
                return out
        if fx.fighting:
            return self.make("go_easy", "still fighting a flaw")
        # 8. Someone else mocked.
        if fx.stick_up:
            return self.make("stick_up", f"{fx.stick_up} was mocked", who=fx.stick_up)
        # 9. Other people's news.
        if a.about in ("sender", "someone_else") and a.news <= -P["r4"]["min_news"]:
            return self.make("care", "bad news for them")
        if a.about in ("sender", "someone_else") and a.news >= P["r4"]["min_news"]:
            if a.human_experience and now - self.asked_like_at >= cp["ask_like_every"]:
                x = roll("ask_like").random()
                if x < cp["ask_like_chance"]:
                    self.asked_like_at = now
                    return self.make("ask_what_like", f"something she can't have (roll {x:.2f})")
            return self.make("glad", "good news for them")
        # 10. Her tastes. A dispute gets a comeback when one is allowed (it misfires like every comeback).
        if fx.contradicted == "taste" or (fx.taste > 0.0 and fx.praise < 0.0):
            if not no_jokes and self._may_comeback(fx, person, now):
                return self._comeback("retort", a, fx, s, person, now, rung, roll, f"her taste disputed ({a.thing})",
                                      {})
            return self.make("defend_taste", f"her taste disputed ({a.thing})")
        if fx.taste > 0.0:
            return self.make("enthuse", f"{a.thing} came up")
        # On the overwhelmed rung, 11 to 13 become plain ("A few words.").
        if rung == "overwhelmed" and (a.topic in ("philosophy", "mind", "math", "physics", "common_sense")
                                      or a.bit != "none"):
            return self.make("plain", "overwhelmed: no tangents, no bits", rung)
        # 11-12. What she knows.
        if a.topic in ("philosophy", "mind"):
            if rung == "composed" and a.topic == "mind":
                return self.make("argue_abstract", a.topic, rung)
            if rung == "composed":  # a question back, unless her last line to them already asked one
                out = self.make("explain", a.topic, rung)
                last = s.last_line or {}
                asked = last.get("target") == name and _TAG.sub(" ", last.get("text", "")).rstrip().endswith("?")
                if not asked:
                    out.template += " " + cp["explain_ask"]
                    out.text = out.template.format(**out.fill)
                return out
            if self._define_real_ok(a):
                self.define_real_uses += 1
                return self.make("define_real", f"{a.topic}, strained, an abstract word ({a.trigger})", rung)
            return self.make("plain", f"{a.topic}, strained", rung)
        if a.topic == "math":
            return self.make("answer_fast" if w["threat"].value < cp["math_threat"] else "work_it_out", "math")
        if a.topic in ("physics", "common_sense"):
            if _WORD.findall(self._text.lower()) and set(_WORD.findall(self._text.lower())) & set(P["safety"]["words"]):
                return self.make("plain", "it could hurt someone: no guessing, no canon")
            if a.canon:
                return self.make("sure_of_it", f"{a.topic}: one of the things she's sure of ({a.canon})",
                                 belief=P.canon[a.canon])
            return self.make("guess", f"{a.topic}: not her thing, too stubborn to say so")
        # Her clumsiness noticed (not a bit): she says it didn't happen, or shrugs it off (a stubborn roll).
        if a.topic == "clumsy" and a.bit == "none":
            x = roll("stubborn").random()
            return self.make("deny_slip" if x < stub else "own_slip",
                             f"her slip noticed (stubborn {stub:.2f}, roll {x:.2f})")
        # 13. Bits: a tease, a joke or roast request.
        if a.bit != "none":
            if no_jokes:
                return self.make("plain", "no jokes right now (someone's distress)")
            if a.bit in ("joke_request", "roast_request"):
                if now - self.joke_asked_at < P["comedy"]["request_every"]:
                    out = self.make("joke_limit", "asked for a joke again too soon")
                    out.say = P["comedy"]["limit_line"]
                    return out
                self.joke_asked_at = now
                if not self._may_comeback(fx, person, now):  # a refusal, not an answer to an insult
                    out = self.make("joke_limit", f"asked for a {a.bit}: no comeback allowed now")
                    out.say = roll("move").choice(P["comedy"]["request_stock"])
                    return out
                return self._comeback("request", a, fx, s, person, now, rung, roll, f"asked for a {a.bit}", {})
            if not self._may_comeback(fx, person, now):
                return self._flat("a tease: no comeback allowed now", rung, {}, roll("move"))
            return self._comeback("retort", a, fx, s, person, now, rung, roll, "a tease", {})
        # The same compliment again (spam): a flat line.
        if fx.spam:
            return self._flat("the same compliment again", rung, {}, roll("move"))
        # 14. Nothing special (the spotlight: a callback when chat is lively; no joke on the overwhelmed rung).
        if (callback and not no_jokes and rung != "overwhelmed"
                and now - self.callback_at >= P["comedy"]["callback_every"]):
            self.callback_at = now
            return self.make("callback", "chat is lively: a joke she's proud of", joke=callback)
        return self._chat(s, person, no_jokes)

    def _chat(self, s: MindState, person: Person, no_jokes: bool) -> Coping:
        """Nothing special happened: how she answers depends on how into it she is (engagement)."""
        P = self.persona
        en = P["engagement"]
        x = engagement(s, P, person)
        why = f"nothing special (engagement {x:.2f})"
        if s.emotions["amusement"].value >= en["play"] and not no_jokes:
            return self.make("play_along", why)
        if x >= en["open"] and person.liking >= P["person"]["friendly"]:
            return self.make("chat_warm", why, name=person.name)
        if x >= en["open"]:
            return self.make("dig_in", why)
        return self.make("plain", why)

    def _contradicted(self, a: Appraisal, fx: Effects, s: MindState, person: Person, now: float, roll: Callable,
                      stub: float) -> Coping:
        P = self.persona
        st = P["stubbornness"]
        if fx.contradicted == "taste":  # she never concedes a taste
            return self.make("defend_taste", "her taste disputed")
        # A real proof gets a concession at once, on her ground or off it; her canon never flips.
        if fx.contradicted == "proof" or (fx.contradicted == "depth" and a.contradicts == "prove"):
            return self.make("concede", "a real proof")
        stance = open_stance(s)
        canon = fx.contradicted == "canon"
        belief = (P.canon[a.canon] if a.canon else stance.data.get("belief", "")) if canon else ""
        challenges = [(t, who) for t, who in stance.data.get("challenges", []) if now - t < st["window"]]
        people = {who for _, who in challenges}
        liked = any(s.people[who].liking >= P["person"]["liked"] for who in people if who in s.people)
        if len(people) >= st["challenges"] and liked and not canon:
            return self.make("testing", f"{len(people)} people corrected it, one she likes")
        if len(challenges) >= st["challenges"]:
            return self.sure(self.make("agree_to_disagree", f"challenge {len(challenges)} to one claim"), belief)
        if stance.data.get("joke") and len(people) >= 2:
            return self.sure(self.make("stand_by_it", "two people corrected her joke: she's still right"), belief)
        if fx.contradicted == "ground":
            return self.make("hold_ground", "contradicted on her ground")
        key = (stance.opened, stance.note)
        downs = [t for t in self.double_downs.get(key, []) if now - t < st["window"]]
        x = roll("stubborn").random()
        if x < stub and len(downs) < st["double_downs"]:
            self.double_downs[key] = downs + [now]
            return self.sure(self.make("double_down", f"corrected: stubborn {stub:.2f}, roll {x:.2f}"), belief)
        if canon:
            return self.sure(self.make("give_little", f"corrected on something she's sure of (stubborn {stub:.2f},"
                                                      f" roll {x:.2f})"), belief)
        return self.make("concede_grudgingly", f"corrected on a guess (stubborn {stub:.2f}, roll {x:.2f})")

    # --- comedy ------------------------------------------------------------

    def _may_comeback(self, fx: Effects, person: Person, now: float) -> bool:
        """At least 3 of her replies and 90 s since her last misfire; the first poke
        of its kind from them in about 5 minutes; at most 2 per person per 5 minutes."""
        cm = self.persona["comedy"]
        recent = [t for t in person.comebacks if now - t < cm["per_person_window"]]
        return (self.replies - self.replies_at_misfire >= cm["cooldown_replies"]
                and now - self.misfire_at >= cm["cooldown_seconds"] and fx.h_s < cm["repeat_poke"]
                and len(recent) < cm["per_person"])

    def _comeback(self, context: str, a: Appraisal, fx: Effects, s: MindState, person: Person, now: float, rung: str,
                  roll: Callable, why: str, weights: dict) -> Coping:
        """She tries to be funny. A retort always misfires; a joke or roast request
        misfires with chance 0.6 + 0.2 x threat (at most 0.85), otherwise a pun."""
        P = self.persona
        cm = P["comedy"]
        if context == "request":
            chance = min(cm["misfire_cap"], cm["request_misfire"] + cm["threat_bonus"] * s.wound["threat"].value)
            x = roll("misfire").random()
            if x >= chance:
                out = self.make("joke", f"{why}; no misfire (roll {x:.2f} ≥ {chance:.2f}): a pun she likes", rung)
                out.weights = weights
                return out
            why += f"; misfire (roll {x:.2f} < {chance:.2f})"
        person.comebacks.append(now)
        self.misfire_at, self.replies_at_misfire = now, self.replies
        shapes = {}
        for k, v in cm["shapes"].items():
            if k == self.last_shape or (context == "request" and k not in cm["request_shapes"]):
                continue
            under_threat = fx.threat0 >= cm["threat_shapes"] and k in cm["threat_shape_names"]
            shapes[k] = v["weight"] * (cm["threat_shape_factor"] if under_threat else 1.0)
        shape = _draw(shapes, roll("shape"))
        self.last_shape = shape
        spec = cm["shapes"][shape]
        fill = {}
        if shape == "premise":
            canon = P.canon
            fill["belief"] = canon[a.canon] if a.canon else roll("premise").choice(list(canon.values()))
        friend = person.liking >= P["person"]["friendly"]
        delivery = cm["delivery"]["friend" if friend else "poke"]
        template = P.moves["comeback"]["text"].replace("{instruction}", spec["instruction"]).replace("{delivery}",
                                                                                                      delivery)
        stop = set(cm["stopwords"])
        said = _words(self._text, cm["example_word"], stop)
        examples = []
        for ex in spec["examples"]:
            quoted = re.match(r"^'([^']*)'", ex)
            if person.name.lower() in ex.lower():  # an example naming them gets copied with the name in it
                continue
            if not _words(quoted.group(1) if quoted else ex, cm["example_word"], stop) & said:
                examples.append(ex)
        out = Coping(rung, "comeback", f"{why}; misfire: {shape}", template.format(**fill),
                     "teasing" if friend else "smug", examples[:2], [P["right_now"]["prohibit"]["misfire"]], shape,
                     weights, "comeback", template=template, fill=fill)
        return out

    def _flat(self, why: str, rung: str, weights: dict, rng) -> Coping:
        """A flat line from her pool: the cool act, not a comeback."""
        cm = self.persona["comedy"]
        free = [x for x in cm["stock"] if self.stock_used.get(x, 0) < cm["stock_uses"] and x != self.last_flat]
        if not free:
            out = self.make("eye_roll", f"{why}; her flat lines are used up", rung)
            out.weights = weights
            return out
        line = rng.choice(free)
        self.stock_used[line] = self.stock_used.get(line, 0) + 1
        self.last_flat = line
        out = self.make("flat", f"{why}; a flat line", rung, line=line)
        out.shape, out.weights, out.say = "stock", weights, line
        return out

    def note_reply(self) -> None:
        self.replies += 1

    # --- slips -------------------------------------------------------------

    def _slip(self, a: Appraisal, s: MindState, person: Person, now: float, rng) -> tuple[str, dict] | None:
        """A slip in place of the plain move, as (template, fill): the names and the wrong word are
        slots, so the word check skips them."""
        P = self.persona
        sl, texts = P["slips"], P["slip_texts"]
        low = f" {' '.join(_WORD.findall(self._text.lower()))} "
        options: list[tuple[str, dict]] = []
        if any(f" {phrase} " in low for phrase in sl["bye"]):
            options.append((texts["you_too"], {}))
        others = [(t, who) for t, who in s.writers if who != person.name and now - t < P["windows"]["other_writer"]]
        if others:  # the name on her mind: whoever else wrote last
            options.append((texts["wrong_name"], {"other": max(others)[1], "name": person.name}))
        for word, wrong in sl["words"].items():
            if f" {word} " in low:
                options.append((texts["word"], {"wrong": wrong}))
        if options and rng.random() < sl["chance"]:
            return rng.choice(options)
        return None

    # --- speaking first ----------------------------------------------------

    def speak_first(self, s: MindState, now: float, rung: str, roll: Callable, *, covering: bool, late: tuple | None,
                    callback: str | None, thought: str | None, crack_who_seen: bool) -> Coping | None:
        """What she does when she fills the dead air (None: she stays silent)."""
        P = self.persona
        sf, cr = P["speak_first"], P["crack"]
        d = s.drives
        longing, lonely, bored = d["longing"].value, d["loneliness"].value, d["boredom"].value
        doubt = s.wound["doubt"].value
        no_jokes = any(x["kind"] == "distress" for x in active_prohibits(s, now))
        rng = roll("speak_first")
        self._now = now
        cozy, self.cozy = self.cozy, False  # a wound thought tips only the next speak-first
        # 0. Someone in distress: no topics, no bits. She checks on them once, then says very little.
        distress = [x for x in active_prohibits(s, now) if x["kind"] == "distress"]
        if distress:
            self.cozy = False
            key = (distress[-1]["who"], distress[-1]["until"])
            if self.checked_in != key:
                self.checked_in = key
                return self.make("check_in", f"{key[0]} is in distress: she checks on them", name=key[0])
            return self.make("say_little", f"{key[0]} is in distress: no new topics")
        # 1. Covering after a crack.
        if covering:
            return self.make("keep_moving", "covering after the crack")
        # 2. The first dead air after a crack.
        if not self.crack_asked and now - self.crack_line_at >= cr["ask_after"]:
            self.crack_asked = True
            if longing >= cr["ask_longing"]:
                return self.make("ask_one_question", f"the first dead air after the crack (longing {longing:.2f})")
            return self.make("say_little", f"the first dead air after the crack (longing {longing:.2f})")
        # 3. Overwhelmed.
        if rung == "overwhelmed":
            if now - self.quiet_said_at >= sf["quiet_every"]:
                self.quiet_said_at = now
                return self.quiet("dead air while she's overwhelmed", "overwhelmed", roll("pause"))
            return None
        # 4. Reaching toward the person she cracked in front of.
        lo, hi = cr["reach"]
        if not self.crack_reached and lo <= now - self.crack_at <= hi and crack_who_seen:
            self.crack_reached = True
            return self.make("ask_ordinary", f"after the crack: she reaches toward {self.crack_who}", name=self.crack_who)
        # 5. A late comeback or a callback.
        if late and not no_jokes:
            who, line = late
            return self.make("use_comeback", f"a better comeback for {who} came to her", name=who, line=line)
        if callback and not no_jokes and now - self.callback_at >= P["comedy"]["callback_every"]:
            self.callback_at = now
            return self.make("callback", "a joke she's proud of", joke=callback)
        # 6. She goes looking for a scare.
        if doubt > sf["scary_doubt"] and bored > sf["scary_boredom"] and now - self.scary_asked_at >= sf["scary_every"]:
            self.scary_asked_at = now
            return self.make("ask_scary", f"doubt {doubt:.2f}, boredom {bored:.2f}: she wants to feel something")
        # 7. Longing: a quiet question.
        if longing >= sf["longing"] and now - self.longing_asked_at >= sf["longing_every"]:
            x = rng.random()
            if x < sf["longing_chance"]:
                self.longing_asked_at = now
                return self.make("ask_lives" if rng.random() < sf["split"] else "reassurance", f"longing {longing:.2f}")
        # 8. An ordinary thought on her mind; a wound thought tips her toward something cozy.
        if thought and rng.random() < sf["thought_chance"]:
            return self.make("bring_up", "a thought she can't let go of")
        if cozy:
            return self.make("start_cozy", "after a hard thought, something cozy")
        # 9-10. Something of her own, or someone who's there: a name only for a real, recent, friendly writer.
        name = self._name(s, now)
        weights = {"start_topic": 1.0 + bored}
        if name is not None:
            if not no_jokes:
                weights["tease_someone"] = sf["tease_weight"] * bored
            weights["call_someone"] = sf["call_weight"] * lonely
        else:
            weights["say_something"] = sf["call_weight"] * lonely
        move = _draw(weights, rng)
        why = f"boredom {bored:.2f}, loneliness {lonely:.2f}"
        if move in ("tease_someone", "call_someone"):
            self.called[name] = now
            return self.make(move, why, name=name)
        return self.make(move, why)


def _draw(weights: dict[str, float], rng) -> str:
    """A weighted draw. Every weight at 0 is a broken table: it fails loudly."""
    total = sum(v for v in weights.values() if v > 0.0)
    if total <= 0.0:
        raise ValueError(f"no move has weight: {weights}")
    x = rng.random() * total
    for k, v in weights.items():
        if v <= 0.0:
            continue
        x -= v
        if x <= 0.0:
            return k
    return next(k for k, v in reversed(list(weights.items())) if v > 0.0)
