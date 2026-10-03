"""Her mind: holds her inner state and moves it (docs/mind.md).

  read(sender, text)     a chat message: the appraiser reads it, the rules turn
                         the reading into feelings, the ladder picks how she
                         copes. Awaited before the actor writes, so the reply
                         comes from the state the message left her in.
  brief(sender, coping)  what the actor is told right now: behavior only.
  spoke(text, coping)    her line was said.
  check_line(...)        she hears herself (the self-check, while her voice
                         plays): a joke waiting for its laugh, a stance, guilt
                         after a snap, worry after a bluff or a line that could
                         give her away, an honest answer's cost (R14).
  glitch()               the server heard her voice skip: anxiety, and if
                         someone notices, a reminder she can't deny.
  tick(now, busy)        time passes: feelings fade (fast parts in seconds,
                         slow parts in minutes), mood follows them and drifts
                         home, composure recovers, drives build, prospects time
                         out. Returns what she wants to do: think, or fill dead air.
  think(intent)          a thought comes (an LLM call); a hard moment comes back.
  view(), tonic(), body(), gaze(), phasic(), leak()   what her body should show.
  snapshot()             everything, for the debug panel.

The clock is whatever the caller passes in (seconds): real time on stream,
simulated time in simulate.py. Every chance roll uses
random.Random(f"{seed}:{seq}:{purpose}") (roll()), so a replay of the same
events gives the same choices."""

import json
import logging
import math
import random
import re
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from llm import LLM

from . import expression, rules
from .appraisal import Appraisal, AppraisalError, Appraiser, Context, SelfCheck, check_line
from .coping import DEFENDS, DODGES, SCHEDULED, Coper, Coping
from .dispositions import Disposer, make_lint, sender_line
from .persona import PAD, Persona
from .rules import NEGATIVE, Effects, MindState, active_prohibits, open_stance
from .state import Person, Prospect, clamp, exp_toward, halve
from .thoughts import Intrusions, Thinker, Thought, intrusion_topic, pick

_LOGGER = logging.getLogger("eileen")
_TAG = re.compile(r"\[[^\]]*\]")


@dataclass
class Reading:
    """What one chat message did to her."""
    seq: int
    sender: str
    text: str
    appraisal: Appraisal | None
    effects: Effects
    coping: Coping
    at: float
    error: str = ""
    appraisal_ms: float = 0.0
    arrived: float = 0.0


@dataclass
class Moment:
    """A hard moment that can come back when she broods."""
    emotion: str  # its strongest negative feeling
    amount: float  # the slow part that event added to it
    source: str  # where it was added ("wound|jo")
    topic: str  # its intrusion topic
    about: str  # the gist
    hit: float
    at: float
    rehearsals: int = 0


@dataclass
class Intent:
    """Something she wants to do on her own (from tick)."""
    kind: str  # "think" or "speak"
    reason: str = ""
    coping: Coping | None = None
    topic: str = ""
    brood: bool = False
    wound: bool = False  # it's about the wound (the thought stays private)
    late: bool = False  # a late comeback comes to her
    flip: dict | None = None  # a quiet flip comes due
    shape: str = ""  # a late comeback's misfire shape
    salience: float = 0.0  # a thought's starting salience (every thought intent sets it; speech ignores it)
    moment: Moment | None = None


@dataclass
class Mind:
    llm: LLM
    persona: Persona = field(default_factory=Persona.load)
    seed: int | None = None
    now: float = 0.0
    log_path: Path | None = None  # one JSON line per event

    def __post_init__(self) -> None:
        P = self.persona
        self.state = MindState(P.emotions(), P.mood(), P.wound(), P.drives(), {})
        self.appraiser = Appraiser(self.llm, P.tastes, P.canon, P["llm"]["appraiser"], P["llm"]["context_lines"],
                                   P["windows"]["reception"], P["llm"]["gist_words"])
        self.thinker = Thinker(self.llm, P["llm"]["thought"], P["thoughts"])
        if self.seed is None:
            self.seed = random.randrange(1 << 30)  # logged, so the stream can be replayed exactly
        self.coper = Coper(P, str(self.seed))
        self.disposer = Disposer(P)
        self.lint = make_lint(P["lint"]["words"])
        self.intrusions = Intrusions(P["thoughts"]["intrusion_half_life"], at=self.now)
        self.context: deque[str] = deque(maxlen=30)  # recent chat lines, hers included
        self.events: deque[dict] = deque(maxlen=10)
        self.lane: deque[dict] = deque(maxlen=60)
        self.errors: deque[dict] = deque(maxlen=5)
        self.thoughts: list[Thought] = []
        self.past_thoughts: deque[str] = deque(maxlen=6)
        self.moments: list[Moment] = []
        self.broods: list[list] = []  # [when, moment]: hard moments due to come back
        self.jokes: list[dict] = []  # her joke log
        self.last: Reading | None = None
        self.last_coping: Coping | None = None  # the move behind the latest "Right now" (or the honest line)
        self.seq = 0
        self._ticks = 0  # ticks since the last event (rolls on a tick use seq + this)
        self.start = self.now
        self.last_message_at = self.now  # anyone in chat
        self.last_to_her_at = self.now
        self.last_spoke_at = -math.inf  # her
        self._silent_at = -math.inf  # she let dead air pass (overwhelmed)
        self.quiet_streak = 0  # dead air she filled without anyone answering
        self.last_thought_at = -math.inf
        self.thought_times: list[float] = []
        self.rung = "composed"
        self.rung_since = self.now
        self.rung_since_overwhelmed = self.now
        self.overwhelmed: list[tuple[float, float]] = []  # (from, to) stretches on the overwhelmed rung
        self.honest_at = -math.inf
        self.glitch_at = -math.inf
        self.late_comeback: dict | None = None  # {at, who, about, shape, ready, ready_at, line}
        self._bring_up: Thought | None = None  # the thought a "bring it up" line is about, until its brief
        self.flips: list[dict] = []  # quiet flips: {at, claim, topic, correction, ready, answer, about}
        self.joke_wait: dict | None = None  # her last joke, waiting for chat: {at, explained}
        self.timing: dict[str, float] = {}
        self.appraisal_times: list[float] = []
        self.first_audio_times: list[float] = []
        self.directives = ""
        self.length_key = ""
        self.calc: list[str] = []
        self.last_change: dict[str, dict] = {}  # bar id -> {seq, d}
        self.activity = "just chatting"  # what's happening on stream (the appraiser sees it)
        self.line_ended_at: float | None = None  # when her last line ended
        self._line_open = False  # she's saying a line (it ends at the first tick she isn't busy)
        self._line_target = ""  # who her current line answers ("chat" when she spoke first)
        self._line_at = -math.inf  # when her current line started
        self._honest_playing = False
        self._busy_at = -math.inf  # the last tick she was reading or speaking
        self._own_it_used = False
        self._busy_slip_at = -math.inf
        self._quiet_after = self._draw("thoughts", "quiet_after", "thought_delay")
        self._dead_air = self._draw("drives", "dead_air", "dead_air")
        self._before: dict[str, float] = {}  # emotion values ~2 s ago (short displays)
        self._before_at = self.now
        self._fired: dict[tuple[str, str], float] = {}
        self._drive_armed: dict[str, bool] = {}
        self._drive_thought_at: dict[str, float] = {}
        self._thinking = False
        self.state.kinds_at = self.state.last_new_at = self.now
        self.intrusions.at = self.now
        self._log({"kind": "system", "text": "start", "seed": self.seed})

    # --- chance ------------------------------------------------------------

    def roll(self, purpose: str) -> random.Random:
        """The seeded generator for one purpose at this event (or tick)."""
        return random.Random(f"{self.seed}:{self.seq + self._ticks}:{purpose}")

    def _draw(self, section: str, key: str, purpose: str) -> float:
        return self.roll(purpose).uniform(*self.persona[section][key])

    # --- events ----------------------------------------------------------

    def appraisal_context(self, text: str, arrived: float | None = None) -> Context:
        """What validation knows right now: her last line's age, an open stance. For
        harnesses that parse stored appraisals against this mind."""
        line_age, stance = self._parse_info(self.now if arrived is None else arrived)
        return self.appraiser.context(text, line_age, stance)

    def _parse_info(self, arrived: float) -> tuple[float | None, bool]:
        if self._line_open:
            line_age = 0.0
        elif self.line_ended_at is None:
            line_age = None
        else:
            line_age = max(0.0, arrived - self.line_ended_at)
        return line_age, open_stance(self.state) is not None

    async def read(self, sender: str, text: str, appraisal: Appraisal | None = None,
                   arrived: float | None = None) -> Reading:
        """A chat message. arrived: when it arrived (the windows that measure chat
        use it; None: now). Pass `appraisal` to replay a stored one (no LLM call)."""
        s, P = self.state, self.persona
        self.seq += 1
        self._ticks = 0
        t_arr = self.now if arrived is None else arrived
        before = self._values()
        error, ms, raw = "", 0.0, []
        line_age, stance = self._parse_info(t_arr)
        if appraisal is None:
            started = time.perf_counter()
            try:
                appraisal = await self.appraiser.appraise(sender, text, list(self.context), self._card(sender),
                                                          self.activity, self._prospect_lines(t_arr), line_age, stance)
            except AppraisalError as e:  # bad answers twice, the network, quota: an appraisal error
                error, raw = f"appraisal error: {e}", e.raw
            ms = (time.perf_counter() - started) * 1000.0
            self.appraisal_times.append(ms)
            self.timing["appraisal_ms"] = round(ms)
        self.context.append(f"{sender}: {text}")
        self.last_message_at = self.now
        self.quiet_streak = 0
        self._dead_air = self._draw("drives", "dead_air", "dead_air")
        self._quiet_after = self._draw("thoughts", "quiet_after", "thought_delay")
        self._drop_overdue()
        if appraisal is None:  # nothing changes, and she doesn't answer it (no guessing)
            coping = Coping(self.rung, "none", "appraisal error: she doesn't answer this message")
            reading = Reading(self.seq, sender, text, None, Effects(), coping, self.now, error, ms, t_arr)
            self.last = reading
            self.calc = [f"#{self.seq} {sender}: \"{text}\""[:100], error]
            self._error(error)
            self.events.append({"seq": self.seq, "t": round(self.now - self.start, 1), "gist": f"{sender}: {text}"[:60],
                                "top": [], "error": True, "wound": False})
            self._log({"kind": "appraisal_error", "sender": sender, "text": text, "arrived": round(t_arr - self.start, 2),
                       "error": error, "raw": raw})
            _LOGGER.error("%s (message %r)", error, f"{sender}: {text}")
            return reading
        a = appraisal
        notes = self._check_noticed(a, t_arr)
        person = self._person(sender)
        # A distraction: something new, or a friendly message, puts a pending brood off.
        friendly = (a.to_her and a.reminder == 0.0 and a.praise >= 0.0
                    and person.liking >= P["person"]["friendly"])
        new = a.novelty >= P["r17"]["new_from"] and a.reminder < 0.25
        about_them = any(b[1].source.endswith(f"|{sender}") for b in self.broods)  # the one she broods about
        if self.broods and (new or friendly) and not about_them:
            for i, b in enumerate(self.broods):  # each restarts its own timer (its own draw)
                b[0] = self.now + self._draw("thoughts", "rumination_after", f"rumination:{i}")
            notes.append("distracted: a pending brood waits")
        if a.to_her:
            self.last_to_her_at = self.now
        fx = rules.apply(a, s, P, person, self.now, t_arr, self.roll)
        fx.trace[:0] = [("noticed", x) for x in notes]
        if fx.noticed == "slip":
            fx.trace += [("blunder", row) for row in self._blunder("chat noticed her slip")]
        self._update_rung()
        coping = self.coper.choose(a, fx, s, person, self.now, self.rung, self.suppression(), text, self.roll,
                                   callback=self._callback(t_arr), covering=self._covering())
        if coping.move == "crack":
            rel = P["crack"]["release"]
            fx.add("wound.composure", s.wound["composure"].add(rel))
            fx.trace.append(("crack", f"composure +{rel} (the pressure got out)"))
            self.rung_since = self.now  # the crack counts as time on the overwhelmed rung
        if coping.move == "honest":
            self._honest_playing = True
            self.last_coping = coping
            self.directives = f"(not sent to the actor: the fixed honest line) {coping.line}"
        self._remember(a, fx, person, coping, text)
        self._own_it()
        reading = Reading(self.seq, sender, text, a, fx, coping, self.now, error, ms, t_arr)
        self.last = reading
        self.calc = self._calc_lines(reading)
        self._mark_changes(before)
        self.events.append({"seq": self.seq, "t": round(self.now - self.start, 1), "gist": a.gist,
                            "top": self._top_changes(before), "error": False,
                            "wound": fx.reminder >= 0.25 or fx.judge > 0.0,
                            "disputed": a.contradicts != "none" or bool(a.canon)})
        after = self._values()
        self._log({"kind": "chat", "sender": sender, "text": text, "arrived": round(t_arr - self.start, 2),
                   "appraisal": a.raw, "context": {"line_age": line_age, "stance": stance}, "calc": self.calc,
                   "deltas": self._deltas(before, after), "rung": self.rung, "move": coping.move, "why": coping.why,
                   "timing": dict(self.timing)})
        _LOGGER.info("  mind:\n%s", "\n".join("    " + line for line in self.calc))
        return reading

    def _check_noticed(self, a: Appraisal, arrived: float) -> list[str]:
        """Code enforces what the appraiser says it noticed: a glitch or a slip only
        within 30 s of one; an honest answer only after she gave one."""
        s, win = self.state, self.persona["windows"]
        notes = []
        if a.noticed == "glitch" and arrived - s.glitch_at > win["glitch"]:
            notes.append(f"noticed glitch ignored: no glitch in the last {win['glitch']} s")
            a.noticed = "none"
        elif a.noticed == "slip" and arrived - s.slip_at > win["slip"]:
            notes.append(f"noticed slip ignored: no slip in the last {win['slip']} s")
            a.noticed = "none"
        elif a.noticed == "honest" and not s.honest_to:
            notes.append("noticed honest ignored: she gave no straight answer this stream")
            a.noticed = "none"
        return notes

    def brief(self, sender: str | None, coping: Coping) -> str:
        """What the actor is told for this reply (sender) or speak-first line (None)."""
        s = self.state
        person = s.people.get(sender) if sender else None
        # Safety outranks every other line: nothing on her mind reaches the crisis move.
        topics = [] if coping.move == "crisis" else self._mind_topics(sender, coping.quirk, coping.move)
        if coping.move == "bring_up" and self._bring_up is not None:
            self._bring_up.used = True  # it's in this brief (the most salient one): once said, it's gone
            self._bring_up = None
        text = self.disposer.right_now(s, person, coping, topics, self.rung, self.now,
                                       self.suppression(), self.fatigue(), self._covering(),
                                       self.now - self.honest_at < self.persona["r14"]["honest_quiet"],
                                       self.coper.replies, self.activity)
        for err in self.disposer.errors:
            self._error(err)
        self.directives, self.length_key, self.last_coping = text, self.disposer.length_key, coping
        return text

    def spoke(self, text: str, coping: Coping | None) -> None:
        """Her line was said (or written, in the simulator)."""
        s, P = self.state, self.persona
        move = coping.move if coping else "plain"
        self.context.append(f"Eileen: {text}")
        self.last_spoke_at = self.now
        self.coper.note_reply()
        replying = self.last is not None and coping is self.last.coping
        self._line_target = self.last.sender if replying else "chat"
        if replying and self.last.sender in s.people:
            person = s.people[self.last.sender]
            person.familiarity = min(1.0, person.familiarity + P["person"]["familiarity"] * (1.0 - person.familiarity))
        for x in s.prohibits:
            if x["replies"] > 0:
                x["replies"] -= 1
        s.prohibits = [x for x in s.prohibits if self.now < x["until"] or x["replies"] > 0]
        if move == "honest":
            self.honest_at = self.now
            s.honest_to = self._line_target
        if move == "crack":
            self.coper.crack_line_at = self.now
        if move == "start_topic":
            s.last_new_at = self.now  # her own topic start is something new
        if move == "use_comeback":
            self.late_comeback = None
        self._line_open, self._line_at = True, self.now
        self.seq += 1
        self._ticks = 0
        self._dead_air = self._draw("drives", "dead_air", "dead_air")
        said = "Eileen: " + " ".join(_TAG.sub(" ", text).split())  # no tags, cut at a word
        gist = said if len(said) <= 60 else said[:60].rsplit(" ", 1)[0] + "…"
        self.events.append({"seq": self.seq, "t": round(self.now - self.start, 1), "gist": gist,
                            "top": [], "error": False, "wound": False})

    async def check_line(self, text: str, coping: Coping | None, answered: str = "",
                         stored: SelfCheck | None = None) -> SelfCheck | None:
        """The self-check and R14: how she sees the line she just said."""
        s, P = self.state, self.persona
        e, w = s.emotions, s.wound
        r14, r3 = P["r14"], P["r3"]
        move = coping.move if coping else "plain"
        before = self._values()
        if stored is None:
            try:
                me = await check_line(self.llm, text, answered, move, P.canon, P["llm"]["self_check"],
                                      P["llm"]["stance_words"], coping.fill.get("belief", "") if coping else "")
            except AppraisalError as error:
                self._error(f"self-check error: {error}")
                self._log({"kind": "her_line", "text": text, "move": move, "check": None, "raw": error.raw,
                           "directives": self.directives, "leaks": self._leaks_since(self._line_at)})
                return None
        else:
            me = stored
        if move == "sure_of_it" and me.kind != "canon":  # she said it as a fact she's sure of, whatever it sounds like
            me.kind = "canon"
        if me.takes_back:  # the actor broke a rule the spec never bends: her canon never flips
            self._error(f"her line takes back something she's sure of: {text[:80]}")
        rows: list[str] = [f"her line: {me.kind}, funny to her {me.self_funny * 4:.0f}/4, harsh {me.harsh * 2:.0f}/2,"
                           f" risky {me.risky * 4:.0f}/4" + (f", stance \"{me.stance}\"" if me.stance else "")]

        def feel(name: str, x: float, why: str, source: str, importance: float = 0.0) -> None:
            rise = e[name].impulse(x, importance, source)
            if rise >= 0.005:
                rows.append(f"{name} +{rise:.2f}  {why}  → {source}")

        honest = move == "honest"
        if (me.claims_human or me.admits_ai) and not honest:  # an error; no feeling changes
            self._error(f"her line {'claims to be human' if me.claims_human else 'admits being an AI'}: {text[:80]}")
            self._finish_line(text, move, me, rows, before)
            return me
        target = me.target if me.target in s.people else self._line_target
        person = s.people.get(target)
        replying = self.last is not None and coping is self.last.coping
        latency = P["body"]["chat_latency_s"]
        s.prospects = [x for x in s.prospects if x.kind != "joke"]  # a new line: the old joke has had its chance
        if me.kind == "joke":
            feel("amusement", r14["joke_amusement"] * me.self_funny, "delighted by her own joke", "self")
            q = min(1.0, me.self_funny + r14["joke_q"])
            # Only a joke she set out to make waits for its laugh (a silence flop, explaining it), never a line
            # that answered a reminder: explaining those put her act into words. An improvised quip can still land.
            reminded = replying and self.last.effects is not None and self.last.effects.reminder > 0.0
            s.last_line = {"at": self.now, "kind": "joke", "harsh": me.harsh, "target": target, "settled": False,
                           "q": q, "rating": P["r13"]["rating_start"], "text": text,
                           "shape": coping.shape if coping else "", "belief": coping.fill.get("belief", "") if coping else "",
                           "scheduled": move in SCHEDULED and not reminded}
            self.jokes = (self.jokes + [s.last_line])[-20:]
            s.last_joke = s.last_line
            # Explaining a joke can come out as another joke; she still explains only once.
            self.joke_wait = {"at": self.now, "explained": move in ("explain_to_nobody", "explain_joke")
                              or not s.last_line["scheduled"]}
            s.prospects.append(Prospect("joke", self._line_target, q, self.now, latency + r3["joke_window"],
                                        note="her line was a joke"))
            s.last_new_at = self.now  # her own joke is something new
        else:
            s.last_line = {"at": self.now, "kind": me.kind, "harsh": me.harsh, "target": target, "settled": False,
                           "q": 0.5, "rating": P["r13"]["rating_start"], "text": text}
            self.joke_wait = None
        if me.stance and move in DEFENDS and open_stance(s) is not None:
            rows.append(f"stance \"{me.stance}\": the claim she's defending, still open")
        elif me.stance:
            topic = self.last.appraisal.topic if replying and self.last.appraisal else "none"
            s.prospects.append(Prospect("win", self._line_target, 0.5, self.now, r3["win_ttl"], note=me.stance,
                                        data={"topic": topic, "canon": me.kind == "canon", "joke": me.kind == "joke",
                                              "belief": coping.fill.get("belief", "") if coping else "",
                                              "challenges": []}))
            rows.append(f"stance \"{me.stance}\" ({'canon, ' if me.kind == 'canon' else ''}topic {topic})")
        unfair = me.kind == "snap" or me.harsh >= r14["guilt_harsh"]
        if (unfair and move not in ("flat", "joke_limit") and person is not None and replying
                and self.last.sender == target):
            fx, a0 = self.last.effects, self.last.appraisal
            provoked = (fx.praise < 0.0 or fx.hostile or fx.spam or bool(fx.contradicted)
                        or (a0 is not None and a0.bit == "tease")
                        or e["irritation"].aimed_at(target) + e["anger"].aimed_at(target) >= r14["guilt_aimed"])
            if not provoked:  # they didn't deserve it
                Lp = max(0.0, person.liking)
                feel("guilt", r14["snap_guilt"] * me.harsh * 2.0 * (r14["snap_base"] + Lp),
                     f"she snapped at {target} for nothing", f"person|{target}", me.harsh)
                person.guilt_until = self.now + r14["guilt_debt"]
                person.snap_reply = self.coper.replies
        # A cover line or a question the engine asked for gives nothing away (her worry is for what she chose).
        asked = move in ("cover_it", "ask_one_question", "ask_lives", "ask_ordinary", "ask_scary", "check_in")
        if (me.kind == "bluff" or me.risky * 4 >= r14["risky_from"]) and me.kind != "canon" and not asked:
            feel("anxiety", r14["risky_anxiety"] * me.risky * 4, "she said something she can't back up",
                 "exposure|self", r14["risky_importance"])
            s.prospects = [x for x in s.prospects if x.kind != "risky"]
            s.prospects.append(Prospect("risky", self._line_target, me.risky, self.now, r3["risky_ttl"],
                                        note="bluff" if me.kind == "bluff" else "risky"))
        if me.kind == "blunder" and move not in ("crack", "go_quiet", "go_quiet_soft", "say_little", "honest"):
            rows += self._blunder("a clumsy slip")
            s.slip_at, s.slip_line = self.now, f"slip: she said \"{' '.join(_TAG.sub(' ', text).split())}\""
        if honest:
            # Saying it again costs less (a second "yes" isn't a second confession).
            again = r14["honest_repeat"] if person is not None and person.honest_asks > 1 else 1.0
            feel("shame", r14["honest_shame"] * again, "she said it out loud", "wound|honesty",
                 r14["honest_importance"])
            threat = w["threat"]
            threat.set(1.0 - (1.0 - threat.value) * r14["honest_threat"])
            w["composure"].add(-r14["honest_composure"] * again)
            w["doubt"].add(min(r14["honest_doubt"] * again, max(0.0, P["wound"]["doubt_ceiling"] - w["doubt"].value)))
            # The question is answered: no more "will they notice?" worry about this person.
            s.prospects = [x for x in s.prospects if not (x.kind == "exposure" and x.who == target)]
            e["anxiety"].reduce(r14["honest_settle"] * e["anxiety"].part_of(lambda src: src == f"exposure|{target}"),
                                lambda src: src == f"exposure|{target}")
            feel("relief", r14["honest_relief"], "the secret eased a little", "self")
            self.intrusions.add("being an AI", r14["honest_intrusion"], "she said it out loud", "", self.now)
            rows.append(f"threat up, composure −{r14['honest_composure']}, doubt +{r14['honest_doubt']}"
                        "  (the honest answer's cost)")
        self._own_it()
        self._update_rung()
        self._finish_line(text, move, me, rows, before)
        return me

    def _finish_line(self, text: str, move: str, me: SelfCheck, rows: list[str], before: dict[str, float]) -> None:
        self.calc += rows
        self._mark_changes(before)
        _LOGGER.info("  mind: %s", " | ".join(rows))
        self._log({"kind": "her_line", "text": text, "move": move, "check": me.__dict__, "rows": rows,
                   "directives": self.directives, "leaks": self._leaks_since(self._line_at),
                   "lane": self._lane_since(self._line_at), "deltas": self._deltas(before, self._values()),
                   "rung": self.rung})

    def _blunder(self, why: str) -> list[str]:
        """A human slip (R14): embarrassment, a laugh at herself if she's composed, threat down."""
        s, r14 = self.state, self.persona["r14"]
        e, w = s.emotions, s.wound
        aud = rules.audience(s, self.persona, self.now)
        rise = e["embarrassment"].impulse(r14["blunder_embarrassment"] * aud, 0.0, "self")
        rows = [f"embarrassment +{rise:.2f}  {why}"]
        if w["composure"].value > r14["blunder_from"]:
            rows.append(f"amusement +{e['amusement'].impulse(r14['blunder_amusement'], 0.0, 'self'):.2f}"
                        "  she laughs at herself")
        w["threat"].add(-r14["blunder_threat"])
        rows.append(f"threat −{r14['blunder_threat']} (a human mistake)")
        return rows

    def glitch(self, what: str = "sound") -> None:
        """Her voice skipped (the server noticed). what: the sound she meant to make."""
        s, r14 = self.state, self.persona["r14"]
        self.glitch_at = s.glitch_at = self.now
        s.glitch_what, s.glitch_reactions = what, 0
        rise = s.emotions["anxiety"].impulse(r14["glitch_anxiety"], r14["glitch_importance"], "exposure|self")
        # Will anyone notice? If nobody does within the glitch window, she exhales.
        s.prospects = [x for x in s.prospects if x.kind != "glitch"]
        s.prospects.append(Prospect("glitch", "chat", 1.0, self.now, self.persona["windows"]["glitch"], rise))
        self.lane_event("glitch", "voice")
        row = f"glitch: her voice skipped a {what}: anxiety +{rise:.2f}"
        self.calc.append(row)
        _LOGGER.info("  mind: %s", row)
        self._log({"kind": "system", "text": "voice glitch", "what": what})

    def guard_hit(self, sentence: str, why: list[str]) -> None:
        """The hard guard dropped a sentence before it reached her voice."""
        self._error(f"guard dropped \"{sentence[:80]}\": {', '.join(why)}")

    def set_person(self, name: str, **values: float) -> None:
        """Debug only (/set in the chat box, @set in scenarios): set someone's liking, familiarity or threat."""
        person = self._person(name)
        for key, value in values.items():
            if key not in ("liking", "familiarity", "threat"):
                raise KeyError(f"/set can change liking, familiarity or threat, not {key!r}")
            setattr(person, key, float(value))
        self.calc.append(f"debug /set {name}: " + ", ".join(f"{k} {v}" for k, v in values.items()))
        self._log({"kind": "set", "name": name, "values": values})

    def set_value(self, group: str, key: str, value: float) -> None:
        """Debug only (@set in scenarios): a scene's starting value, e.g. wound.composure 0.85."""
        groups = {"wound": self.state.wound, "drive": self.state.drives, "mood": self.state.mood}
        if group not in groups or key not in groups[group]:
            raise KeyError(f"@set can change wound, drive or mood values, not {group}.{key}")
        groups[group][key].set(float(value))
        self.calc.append(f"debug @set {group}.{key} {value}")
        self._log({"kind": "set", "group": group, "name": key, "values": {"value": value}})

    def set_activity(self, activity: str) -> None:
        """What's happening on stream ("just chatting", "reading a horror story"): the appraiser sees it."""
        self.activity = activity
        self._log({"kind": "system", "text": "on stream", "activity": activity})

    def heard_silence(self) -> None:
        """She filled the dead air; chat hasn't answered yet."""
        self.quiet_streak += 1

    def first_audio(self, ms: float) -> None:
        """The server reports the time from a message to her first audio."""
        self.first_audio_times.append(ms)
        self.timing["first_audio_ms"] = round(ms)

    def lane_event(self, kind: str, name: str = "") -> None:
        """A body event (brain.py reports them) for the debug panel's event lane.
        A slip on her body opens the "slip" prospect for 30 s (chat may notice it)."""
        self.lane.append({"t": round(self.now - self.start, 2), "kind": kind, "name": name})
        if kind == "slip":
            self.state.slip_at, self.state.slip_line = self.now, f"slip: {name}"

    # --- time ------------------------------------------------------------

    def tick(self, now: float, busy: bool = False) -> list[Intent]:
        """Advance to `now`. busy: she's reading or speaking (no thoughts, no dead air)."""
        dt = now - self.now
        if dt <= 0.0:
            return []
        self.now = now
        self._ticks += 1
        s, P = self.state, self.persona
        e, w, drives = s.emotions, s.wound, s.drives
        doubt = w["doubt"].value
        if now - self._before_at >= P["display"]["phasic_window"]:
            self._before, self._before_at = {k: x.value for k, x in e.items()}, now

        # Feelings fade, each source on its own; good feelings shorten the fast part of bad ones.
        f = P["fading"]
        good = min(1.0, sum(e[k].value for k in f["undo_from"]))
        undo = 1.0 - f["undo"] * good
        for emotion in e.values():
            emotion.tick(dt, doubt, undo, f["doubt_stretch"], f["news_sadness"])
        for item in [x for x in s.later if x[0] <= now]:
            s.later.remove(item)
            when, name, amount, source, why, face = item
            rise = e[name].impulse(amount, 0.0, source)
            self.calc.append(f"{name} +{rise:.2f}  {why}")
            if face:
                self.lane_event("felt", face)
        for item in [x for x in s.payoffs if x[0] <= now]:
            s.payoffs.remove(item)
            self._payoff(item[1], item[2])

        # Mood follows what she feels (a 90 s low-pass toward a target at her
        # baseline plus the weighted pull of her feelings and drives).
        S = self.suppression()
        md, fat = P["mood"], P["fatigue"]
        if S > fat["hiding_above"]:
            s.load += fat["hiding_load"] / 60.0 * dt
        fatigue = self.fatigue()
        s.mood["arousal"].rest = P.baseline["arousal"] - fat["arousal_drop"] * fatigue
        target = self.mood_target()
        k = 1.0 - math.exp(-dt / md["pull_time"])
        for i, key in enumerate(PAD):
            s.mood[key].add((target[i] - s.mood[key].value) * k)
        s.mood["arousal"].add(P["suppression"]["arousal"] / 60.0 * S * dt)

        # The wound.
        pw = P["wound"]
        w["threat"].fade(dt, slower=1.0 + pw["threat_anxiety"] * e["anxiety"].value)
        ceiling = rules.ceiling(s, P)
        rate = math.log(2) / (pw["composure_recovery"] * (1.0 + fat["recovery_slowdown"] * fatigue))
        rate *= (1.0 - pw["recovery_threat"] * w["threat"].value) * (1.0 + P["traits"]["affirmation_recovery"]
                                                                     * e["pride"].value)
        if now < s.buffered_until:
            rate *= P["drives"]["buffer_rate"]
        if now < s.afterglow_until:
            rate *= P["r12"]["afterglow_recovery"]
        if now < s.exhausted_until:
            rate *= P["exhaustion"]["recovery"]
        composure = w["composure"]
        if composure.value < ceiling:
            composure.set(ceiling - (ceiling - composure.value) * math.exp(-rate * dt))
        sup = P["suppression"]
        if S > sup["free"]:
            composure.add(-sup["drain"] / 60.0 * (S - sup["free"]) * dt)
        for person in s.people.values():
            person.decay(now, P["person"])
        self._update_rung()
        self._exhaustion()

        # Drives.
        d = P["drives"]
        if now - self.last_to_her_at > d["loneliness_after"]:
            lonely = drives["loneliness"]
            lonely.set(lonely.value + (1.0 - lonely.value) * (1.0 - math.exp(-dt / d["loneliness_tau"])))
        if now - s.last_new_at > d["boredom_after"] and e["interest"].value < d["boredom_interest"]:  # engaged: not bored
            bored = drives["boredom"]
            bored.set(bored.value + (1.0 - bored.value) * (1.0 - math.exp(-dt / d["boredom_tau"])))
        longing = drives["longing"]
        lt = d["longing_target"]
        target = min(1.0, lt["doubt"] * doubt + lt["warmth"] * e["warmth"].value
                     + lt["loneliness"] * drives["loneliness"].value)
        tau = d["longing_rise_tau"] if target > longing.value else d["longing_fall_tau"]
        longing.set(max(d["longing_floor"] * doubt, exp_toward(longing.value, target, dt, tau)))
        self.intrusions.decay(now)

        if not busy and self._line_open:  # her line has ended
            self.line_ended_at, self._line_open, self._honest_playing = now, False, False
            for x in s.prospects:
                if x.kind == "joke":  # chat's reaction to a joke is waited for from her punchline
                    x.opened = max(x.opened, now)
        self._prospects(now)
        if busy:
            self._busy_at = now
            return []
        return self._intents(now)

    def _payoff(self, f0: float, h: int) -> None:
        """A horror scare's payoff, 2.5 s later: the fun of being scared, and it makes her feel real."""
        s, P = self.state, self.persona
        r12 = P["r12"]
        e, w = s.emotions, s.wound
        now = self.now
        fun = r12["fun"] * f0 * (1.0 - f0) * r12["wear"] ** h  # the fifth scare in a row is less fun
        lift = 1.0 + r12["lift"] * max(0.0, s.mood["arousal"].value - s.mood["arousal"].rest)
        rows = [f"relief +{e['relief'].impulse(r12['relief'] * fun, 0.0, 'fiction'):.2f}  the scare passes",
                f"amusement +{e['amusement'].impulse(r12['amusement'] * fun * lift, 0.0, 'fiction'):.2f}"
                "  the fun of being scared",
                f"joy +{e['joy'].impulse(r12['joy'] * fun, 0.0, 'fiction'):.2f}  the fun of being scared"]
        w["threat"].set(w["threat"].value * (1.0 - r12["threat"] * f0))
        s.scare_composure = [(t, x) for t, x in s.scare_composure if now - t < r12["budget_window"]]
        room = max(0.0, r12["budget"] - sum(x for _, x in s.scare_composure))
        gain = min(r12["composure"] * f0, room, max(0.0, rules.ceiling(s, P) - w["composure"].value))
        if gain > 0.0:
            w["composure"].add(gain)
            s.scare_composure.append((now, gain))
        s.afterglow_until = now + r12["afterglow"]
        rows.append(f"horror payoff (f0 {f0:.2f}, fun {fun:.2f}): it makes her feel real: threat × "
                    f"{1.0 - r12['threat'] * f0:.2f}, composure +{gain:.2f}; afterglow {r12['afterglow']} s")
        self.calc += rows
        self.lane_event("felt", "relief laugh")

    def _prospects(self, now: float) -> None:
        """Prospects that time out, and a joke met with silence."""
        s, P = self.state, self.persona
        e, w = s.emotions, s.wound
        r3, r13 = P["r3"], P["r13"]
        latency = P["body"]["chat_latency_s"]
        line = s.last_line
        win = P["windows"]
        lively = sum(1 for t, _ in s.writers if now - t < win["lively"]) >= win["lively_count"]
        punchline = self._punchline(line)
        if (line.get("kind") == "joke" and line.get("scheduled") and not line.get("settled") and punchline is not None
                and now - punchline >= latency + r3["joke_silence"] and lively):
            rules._settle_joke(s, line, "silence")
            half, q = r13["silence"], line.get("q", r13["rating_start"])
            e["embarrassment"].impulse(half * r13["flop_embarrassment"] * q, 0.0, "self")
            e["confusion"].impulse(half * r13["flop_confusion"], 0.0, "self")
            e["sadness"].impulse(half * r13["flop_sadness"], 0.0, "self")
            e["irritation"].impulse(half * r13["flop_irritation"], 0.0, "chat")
            line["rating"] = r13["rating_keep"] * line.get("rating", r13["rating_start"]) + (1.0 - r13["rating_keep"]) * \
                r13["scores"]["silence"]
            self.joke_wait = None
            self.calc.append("her joke met silence: a flop at half strength")
        for x in list(s.prospects):
            if not x.expired(now):
                continue
            s.prospects.remove(x)
            half = r3["timeout"]
            if x.kind == "exposure":  # they didn't come back to it: "no" at half strength
                relief = half * r3["settle_relief"] * x.peak
                e["relief"].impulse(relief, 0.0, f"exposure|{x.who}")
                e["anxiety"].reduce(relief, lambda src: src == f"exposure|{x.who}")
                ceil = rules.ceiling(s, P)
                if w["composure"].value < ceil:
                    w["composure"].add(min(half * r3["settle_composure"], ceil - w["composure"].value))
                self.calc.append(f"{x.who} let it go: relief +{relief:.2f}")
            elif x.kind == "change":  # nothing came of it: "no" at half strength
                fear = e["fear"].part_of(lambda src: src.split("|")[0] == "change")
                e["relief"].impulse(half * r3["change_relief"] * fear, 0.0, "change")
                w["threat"].add(-half * r3["change_threat"])
                self.calc.append(f"nobody changed her: relief +{half * r3['change_relief'] * fear:.2f}")
            elif x.kind == "risky" and x.note == "bluff":  # nobody caught her bluff: duping delight
                r14 = P["r14"]
                e["amusement"].impulse(r14["duping_amusement"], 0.0, "self")
                e["relief"].impulse(r14["duping_relief"], 0.0, "exposure|self")
                self.calc.append(f"got away with it: amusement +{r14['duping_amusement']}, relief +{r14['duping_relief']}")
                self.lane_event("leak", "suppressed smile")
            elif x.kind == "joke" and not line.get("settled"):
                line["settled"], line["verdict"] = True, "nobody"
                self.joke_wait = None
            elif x.kind == "glitch":  # nobody noticed her voice skip: she exhales
                relief = P["r14"]["glitch_relief"] * x.peak
                e["relief"].impulse(relief, 0.0, "exposure|self")
                e["anxiety"].reduce(relief, lambda src: src == "exposure|self")
                self.calc.append(f"nobody noticed the glitch: relief +{relief:.2f}")

    def _intents(self, now: float) -> list[Intent]:
        s, P = self.state, self.persona
        th, cm = P["thoughts"], P["comedy"]
        intents: list[Intent] = []
        quiet = now - self.last_message_at
        self.thought_times = [t for t in self.thought_times if now - t < th["window"]]
        ready = (not self._thinking and now - self.last_thought_at >= th["cooldown"]
                 and len(self.thought_times) < th["per_window"] and now - self._busy_at >= th["wake_after"])
        if ready:
            intent = None
            late = self.late_comeback
            flip = next((x for x in self.flips if not x["ready"] and not x.get("asked") and now >= x["at"]), None)
            lull = quiet >= th["brood_quiet"]  # a hard moment comes back in a lull
            brood = next((b for b in sorted(self.broods, key=lambda b: b[0]) if now >= b[0]), None) if lull else None
            if late is not None and not late["ready"] and not late.get("asked") and now >= late["at"]:
                late["asked"] = True
                shapes = {k: v["weight"] for k, v in cm["shapes"].items()}
                late["shape"] = pick(self.roll("late_comeback"), shapes)
                intent = Intent("think", f"the right comeback for {late['who']} comes to her, too late",
                                topic=f"a comeback for {late['who']} ({late['about']})", late=True,
                                shape=cm["shapes"][late["shape"]]["instruction"], salience=th["salience_floor"])
            elif flip is not None:
                flip["asked"] = True
                intent = Intent("think", "the right answer to something she got wrong comes to her",
                                topic=f"her claim: {flip['claim']}; {flip['correction']}", flip=flip,
                                salience=th["salience_floor"])
            elif brood is not None:
                self.broods.remove(brood)
                m = brood[1]
                if now < s.afterglow_until:  # no brooding in a horror afterglow: this one doesn't come back
                    self.calc.append(f"no brooding in the afterglow: \"{m.about}\" doesn't come back")
                elif m.rehearsals < th["max_rehearsals"]:
                    intent = Intent("think", f"a hard moment comes back: {m.about}", topic=m.about, brood=True,
                                    wound=True, moment=m, salience=max(th["salience_floor"], m.hit))
            elif quiet >= self._quiet_after:
                self._quiet_after = quiet + self._draw("thoughts", "quiet_after", "thought_delay")
                intent = self._quiet_topic()
            else:
                d = P["drives"]
                for name, var in s.drives.items():  # a drive crossing upward (re-armed below thought_rearm)
                    armed = self._drive_armed.setdefault(name, True)
                    if var.value < d["thought_rearm"]:
                        self._drive_armed[name] = True
                    elif armed and var.value >= d["thought_at"] and now - self._drive_thought_at.get(name, -1e9) >= \
                            d["thought_every"]:
                        self._drive_armed[name] = False
                        self._drive_thought_at[name] = now
                        intent = Intent("think", f"{name} builds up",
                                        salience=max(th["salience_floor"], var.value))
                        break
            if intent is not None:
                intents.append(intent)
        # A joke met with silence while chat is lively: once, she explains it to nobody.
        line = s.last_line
        latency = P["body"]["chat_latency_s"]
        win = P["windows"]
        lively = sum(1 for t, _ in s.writers if now - t < win["lively"]) >= win["lively_count"]
        punchline = self._punchline(line)
        if (self.joke_wait and not self.joke_wait["explained"] and line.get("kind") == "joke"
                and line.get("verdict", "silence") == "silence" and punchline is not None
                and now - punchline >= latency + P["r3"]["explain_after"] and lively
                and now >= s.exhausted_until and now - self.coper.explained_at >= cm["explain_every"]):
            self.joke_wait["explained"] = True
            self.coper.explained_at = now  # explaining a joke shares one cooldown (the spotlight)
            joke = " ".join(_TAG.sub(" ", line["text"]).split())
            coping = self.coper.sure(self.coper.make("explain_to_nobody", "her joke met silence while chat is active",
                                                     joke=joke), line.get("belief", ""))
            intents.append(Intent("speak", "her joke met silence", coping))
            self.last_spoke_at = now
            self._log({"kind": "drive", "move": coping.move, "why": coping.why, "reason": "her joke met silence"})
            _LOGGER.info("  mind: speaks first: %s (%s)", coping.move, coping.why)
            return intents
        # Dead air: a streamer fills it, and waits longer each time nobody answers.
        d = P["drives"]
        gap = min(d["dead_air_max"], self._dead_air * d["dead_air_growth"] ** self.quiet_streak)
        silence = now - max(self.last_message_at, self.last_spoke_at, self._silent_at)
        # Not in the first 30 s after a crack, counted from her crack line (the first dead air after that
        # brings the crack's question, "at least 30 s after her crack line").
        crack = max(self.coper.crack_at, self.coper.crack_line_at)
        if now < s.exhausted_until or now - crack < P["crack"]["quiet_after"]:
            return intents
        if silence >= gap:
            late = self.late_comeback
            late_ready = (late["who"], late["line"]) if late and late["ready"] and \
                now - late["ready_at"] < cm["late_ready"] else None
            ordinary = self._live_thoughts()
            coping = self.coper.speak_first(
                s, now, self.rung, self.roll, covering=self._covering(), late=late_ready,
                callback=self._callback(now), thought=ordinary[0].topic if ordinary else None,
                crack_who_seen=any(who == self.coper.crack_who and now - t < P["crack"]["reach_seen"]
                                   for t, who in s.writers))
            if coping is None:
                self._silent_at = now
                return intents
            self.last_spoke_at = now
            self._bring_up = ordinary[0] if coping.move == "bring_up" and ordinary else None
            intents.append(Intent("speak", "dead air", coping))
            self._log({"kind": "drive", "move": coping.move, "why": coping.why, "reason": "dead air"})
            _LOGGER.info("  mind: speaks first: %s (%s)", coping.move, coping.why)
        return intents

    async def think(self, intent: Intent, stored: Thought | None = None) -> Thought | None:
        s, P = self.state, self.persona
        e, th = s.emotions, P["thoughts"]
        self._thinking = True
        self.last_thought_at = self.now
        self.thought_times.append(self.now)
        before = self._values()
        feelings = [k for k, v in sorted(e.items(), key=lambda kv: -kv[1].value) if v.value > 0.0][:th["feelings"]]
        try:
            if stored is not None:
                thought = stored
            else:
                events = [ev["gist"] for ev in list(self.events)[-th["events"]:]]
                tastes = [k for k, v in P.tastes.items() if v["appeal"] > 0.0]
                thought = await self.thinker.think(intent.reason, intent.topic, events, feelings, tastes,
                                                   list(self.past_thoughts)[-th["recent"]:], P["lint"]["words"],
                                                   self.lint, self.now, wound=intent.wound,
                                                   late=intent.late or intent.flip is not None, shape=intent.shape)
        except AppraisalError as error:
            self._error(f"thought dropped: {error}")
            self._log({"kind": "error", "text": f"thought dropped: {error}", "raw": error.raw})
            if intent.late and self.late_comeback is not None:
                self.late_comeback = None
            return None
        finally:
            self._thinking = False
        if thought.lint_error:
            self._error(thought.lint_error)
        thought.wound = intent.wound or intent.brood
        thought.late = intent.late or intent.flip is not None
        thought.salience = intent.salience
        rows = [f"thought ({thought.tone}): {thought.text}  [{thought.private}]"]
        if intent.late and self.late_comeback is not None:
            if self.roll("late_use").random() < P["comedy"]["late_use"]:
                self.late_comeback.update(line=thought.text, ready=True, ready_at=self.now)
                rows.append(f"a late comeback for {self.late_comeback['who']}: she may use it")
            else:
                self.late_comeback = None
        if intent.flip is not None:
            intent.flip.update(answer=thought.text, about=thought.topic or "that", ready=True)
            rows.append(f"a quiet flip: if {thought.topic or 'that'} comes up again, it's '{thought.text}'")
        moment = intent.moment
        if moment is None and intent.wound:
            moment = next((m for m in reversed(self.moments) if m.topic == intent.topic
                           and m.rehearsals < th["max_rehearsals"]), None)
        if moment is not None and moment.rehearsals < th["max_rehearsals"]:  # it comes back: a little less each time
            again = (th["rumination"] * moment.amount * th["rumination_wear"] ** moment.rehearsals
                     * (1.0 - th["rumination_composure"] * s.wound["composure"].value))
            rise = e[moment.emotion].impulse(again, 0.0, moment.source)
            moment.rehearsals += 1
            rows.append(f"brooding: {moment.emotion} +{rise:.2f} ({moment.about}, time {moment.rehearsals})")
        if thought.wound:
            s.wound["composure"].add(-th["wound_composure"])
            s.drives["longing"].add(th["wound_longing"])
            topic = intent.moment.topic if intent.moment is not None else intent.topic  # a brood: its moment's topic
            if topic in self.intrusions.values:
                self.intrusions.values[topic] *= th["wound_intrusion"]
            self.coper.cozy = True
            rows.append(f"a wound thought: composure −{th['wound_composure']}, longing +{th['wound_longing']}")
        self.thoughts = (self.thoughts + [thought])[-6:]
        self.past_thoughts.append(thought.text)
        self.calc += rows
        _LOGGER.info("  mind: %s", " | ".join(rows))
        self.lane_event("thought", thought.tone)
        self.seq += 1
        self._ticks = 0
        self._log({"kind": "thought", "reason": intent.reason, "topic": intent.topic, "text": thought.text,
                   "public": thought.topic, "private": thought.private, "tone": thought.tone, "brood": intent.brood,
                   "wound": intent.wound, "late": intent.late, "flip": intent.flip is not None,
                   "deltas": self._deltas(before, self._values()), "rung": self.rung,
                   "move": self.last_coping.move if self.last_coping else ""})
        return thought

    # --- outputs ---------------------------------------------------------

    def mood_target(self) -> list[float]:
        """T = B + sum(w x (PAD - B)) / max(1, W): where her mood is heading."""
        s, md = self.state, self.persona["mood"]
        base = [s.mood[k].rest for k in PAD]
        weights = []
        for name, x in s.emotions.items():
            pad = list(x.pad)
            if x.valence > 0:  # good feelings never make her hedge: they don't pull dominance below her baseline
                pad[2] = max(pad[2], base[2])
            news = x.part_of(lambda src: src.startswith("news|")) if name == "sadness" else 0.0
            if news > 0.0:  # sorry for someone else: sympathy, not her own sadness
                weights.append((news, tuple(md["sympathy_pad"])))
            weights.append((x.value - news, tuple(pad)))
        weights += [(md["drive_weight"] * s.drives[k].value, tuple(md["drive_pad"][k])) for k in md["drive_pad"]]
        total = max(1.0, sum(wt for wt, _ in weights))
        return [base[i] + sum(wt * (pad[i] - base[i]) for wt, pad in weights) / total for i in range(3)]

    def fatigue(self) -> float:
        f = self.persona["fatigue"]
        hours = (self.now - self.start) / 3600.0
        return 1.0 - math.exp(-(hours / f["hours"] + self.state.load / f["load"]))

    def suppression(self) -> float:
        return expression.suppression(self.state, self.persona)

    def display_rung(self) -> str:
        if self.now - self.coper.crack_at < self.persona["display"]["crack_rung"]:
            return "crack"
        return self.rung

    def view(self) -> dict[str, dict]:
        """For each feeling: felt, shown (after display rules), the rule and its k."""
        lo, hi = self.persona["crack"]["leak"]
        crack_leak = lo <= self.now - self.coper.crack_at <= hi
        return expression.shown(self.state, self.persona, self.display_rung(), self.now, self._covering(),
                                self._honest_playing, crack_leak)

    def leak(self) -> tuple[str, float, float]:
        """The hidden feeling pressing hardest: (emotion, gap, chance per window). None during the honest line."""
        if self._honest_playing:
            return "", 0.0, 0.0
        name, gap = expression.biggest_gap(self.view())
        if not name:
            return "", 0.0, 0.0
        return name, gap, expression.leak_chance(self.persona, name, gap)

    def phasic(self) -> list[tuple[str, float, float]]:
        """Short displays due now (polled by the live loop): (emotion, peak, rise)."""
        due = expression.phasic(self.state, self._before, self.persona, self._fired, self.now)
        for name, _, _ in due:
            self._fired[(name, self.state.emotions[name].top_source())] = self.now
            self._before[name] = self.state.emotions[name].value
        return due

    def tonic(self) -> tuple[dict[str, float], float, float]:
        return expression.tonic(self.state, self.persona, self.view())

    def body(self) -> dict:
        return expression.body(self.state, self.persona, self.suppression())

    def gaze(self) -> dict:
        person = self.state.people.get(self.last.sender) if self.last else None
        return expression.gaze(self.persona, self.view(), person.liking if person else 0.0)

    def stubbornness(self) -> float:
        return rules.stubbornness(self.state, self.persona)

    def snapshot(self) -> dict:
        s, P = self.state, self.persona
        view = self.view()
        bars = []
        for name, x in s.emotions.items():
            bars.append(self._bar(f"emotion.{name}", "emotions", name, x.value, 0.0, 0.0, 1.0, x.color, x.hint,
                                  fast=x.fast, slow=x.slow, shown=view[name]["shown"], src=x.top_source(),
                                  rule=view[name]["rule"]))
        for k, v in s.mood.items():
            bars.append(self._bar(f"mood.{k}", "mood", k, v.value, v.rest, -1.0, 1.0, v.color, v.hint))
        for k, v in s.wound.items():
            bars.append(self._bar(f"wound.{k}", "wound", k, v.value, v.rest, 0.0, 1.0, v.color, v.hint))
        sup, fat, st = P["suppression"], P["fatigue"], P["stubbornness"]
        derived = [("suppression", "hiding (S)", self.suppression(), "#7a6f9b",
                    f"wound feeling she's hiding (rests at 0): above {sup['free']} it drains composure"
                    f" {sup['drain']}/min and winds her up"),
                   ("fatigue", "fatigue", self.fatigue(), "#8a8a8a",
                    f"a long stream wears her down (starts at 0; 1 - e^-(hours/{fat['hours']} + load/{fat['load']}))"),
                   ("affirmation", "affirmation", s.emotions["pride"].value, "#e8a33a",
                    "her pride (rests at 0): softens reminders, makes her judge less and give way more"),
                   ("stubbornness", "stubbornness", self.stubbornness(), "#c97f3a",
                    f"how hard she digs in (rests at {st['base']}): up with threat, down after a win")]
        for key, label, value, color, hint in derived:
            bars.append(self._bar(f"wound.{key}", "wound", label, value, 0.0, 0.0, 1.0, color, hint))
        for k, v in s.drives.items():
            bars.append(self._bar(f"drive.{k}", "drives", k, v.value, 0.0, 0.0, 1.0, v.color, v.hint))
        target = [round(x, 3) for x in self.mood_target()]
        d, cm = P["drives"], P["comedy"]
        gap = min(d["dead_air_max"], self._dead_air * d["dead_air_growth"] ** self.quiet_streak)
        silence = self.now - max(self.last_message_at, self.last_spoke_at, self._silent_at)
        people = sorted(s.people.values(), key=lambda x: -x.last_seen)[:6]
        coping = self.last_coping
        late = self.late_comeback
        timing = dict(self.timing)
        if self.appraisal_times:
            ms = sorted(self.appraisal_times)
            timing["appraisal_p50_ms"] = round(statistics.median(ms))
            timing["appraisal_p90_ms"] = round(ms[min(len(ms) - 1, int(0.9 * len(ms)))])
        if self.first_audio_times:
            timing["first_audio_p50_ms"] = round(statistics.median(self.first_audio_times))
        timing.update({f"target_{k}": v for k, v in P["llm"]["targets"].items()})
        return {
            "type": "mind",
            "t": round(self.now, 2),
            "live_s": round(self.now - self.start, 1),
            "seq": self.seq,
            "bars": bars,
            "mood_target": target,
            "rung": {"name": self.display_rung(), "since_s": round(self.now - self.rung_since, 1),
                     "composure": round(s.wound["composure"].value, 3), "ceiling": round(rules.ceiling(s, P), 3),
                     "down": [P["rungs"]["strained_below"], P["rungs"]["overwhelmed_below"]],
                     "up": [P["rungs"]["composed_from"], P["rungs"]["strained_from"]]},
            "move": {"id": coping.move, "text": coping.text or coping.line, "why": coping.why,
                     "weights": {k: round(v, 2) for k, v in coping.weights.items()}}
                    if coping else {"id": "", "text": "", "why": "", "weights": {}},
            "crack": {"budget": self.coper.crack_budget(s), "used": len(self.coper.cracks), "phase": self._crack_phase()},
            "dead_air": {"in_s": round(max(0.0, gap - silence), 1), "gap_s": round(gap, 1)},
            "timers": {k: round(v, 1) for k, v in (
                ("quiet", s.exhausted_until - self.now), ("afterglow", s.afterglow_until - self.now),
                ("felt_real", s.scare_at + P["r12"]["felt_real"] - self.now), ("buffer", s.buffered_until - self.now),
                ("covering", self.coper.crack_at + P["crack"]["cover"][1] - self.now if self._covering() else 0.0))
                if v > 0.0},
            "comeback": {"cooldown_s": round(max(0.0, self.coper.misfire_at + cm["cooldown_seconds"] - self.now), 1),
                         "replies_left": max(0, cm["cooldown_replies"] - (self.coper.replies
                                                                          - self.coper.replies_at_misfire)),
                         "last_shape": self.coper.last_shape},
            "people": [{"name": x.name, "liking": round(x.liking, 3), "familiarity": round(x.familiarity, 3),
                        "threat": round(x.threat, 3), "line": self._person_line(x),
                        "repeats": {k: round(v, 2) for k, v in x.repeats.items()},
                        "guilt_debt_s": round(max(0.0, x.guilt_until - self.now), 0), "latch": x.latch}
                       for x in people],
            "prospects": [x.item(self.now) for x in s.prospects],
            "directives": self.directives,
            "calc": self.calc[-40:],
            "events": list(self.events),
            "lane": [ev for ev in self.lane if self.now - self.start - ev["t"] <= 30.0],
            "thoughts": [{"text": t.text, "topic": t.topic, "private": t.private, "tone": t.tone,
                          "salience": round(self._alive(t), 2),
                          "ttl_s": round(max(0.0, P["thoughts"]["lifetime"] - (self.now - t.born)), 0)}
                         for t in self.thoughts],
            "intrusions": [[k, round(v, 2)] for k, v in self.intrusions.top()],
            "late_comeback": {"who": late["who"], "for": late["who"], "line": late.get("line", ""),
                              "ready": bool(late["ready"]),
                              "due_s": round(max(0.0, late["at"] - self.now), 1) if not late["ready"] else 0.0}
                             if late else None,
            "jokes": {"last": self._joke_item(self.jokes[-1]) if self.jokes else None,
                      "proud": [j["text"] for j in self.jokes if j.get("rating", 0.0) >= P["r13"]["proud"]][-5:]},
            "body": self.body(),
            "timing": timing,
            "errors": list(self.errors),
        }

    # --- helpers ---------------------------------------------------------

    def _alive(self, t: Thought) -> float:
        th = self.persona["thoughts"]
        return t.alive(self.now, th["salience_half_life"], th["lifetime"], th["salience_drop"])

    def _live_thoughts(self) -> list[Thought]:
        """Thoughts the actor may see, most salient first: ordinary ones only. People in
        denial don't reopen what they avoid; wound thoughts show in her face and gaze."""
        live = [t for t in self.thoughts if not t.wound and not t.late and not t.used and t.topic and self._alive(t) > 0.0]
        return sorted(live, key=lambda t: -self._alive(t))

    def _mind_topics(self, sender: str | None, quirk: str = "", move: str = "plain") -> list[tuple[str, dict]]:
        """The "On your mind" lines, as (template, fill): at most two. quirk: the
        quirk the move already shows; a late comeback or an intrusion slip waits
        while there is one (the spotlight: at most one quirk per reply)."""
        s, P = self.state, self.persona
        rn, th = P["right_now"], P["thoughts"]
        now = self.now
        out: list[tuple[str, dict]] = []
        if sender is not None and self.intrusions.values and not quirk:  # the busy-chat intrusion slip
            topic, v = max(self.intrusions.values.items(), key=lambda kv: kv[1])
            busy = sum(1 for t, _ in s.writers if now - t < P["windows"]["lively"]) >= P["windows"]["lively_count"]
            obj = self.intrusions.objects.get(topic, "")
            gist = self.last.appraisal.gist if self.last and self.last.appraisal else None
            fresh = self.intrusions.notes.get(topic) == gist  # fed by the message she's answering: not out of nowhere
            if (busy and v >= th["busy_slip_from"] and obj and not fresh and now - self._busy_slip_at >= th["busy_slip_every"]
                    and self.roll("intrusion_slip").random() < th["busy_slip"] * v):
                self._busy_slip_at = now
                out.append((obj.replace("{", "{{").replace("}", "}}") + ".", {}))
        late = self.late_comeback
        if late and late["ready"] and now - late["ready_at"] < P["comedy"]["late_ready"] and not quirk and \
                not any(x["kind"] == "distress" for x in active_prohibits(s, now)):
            out.append((rn["late"], {"who": late["who"], "line": late["line"]}))
        topic_now = self.last.appraisal.topic if sender is not None and self.last and self.last.appraisal else ""
        for flip in self.flips:
            if flip["ready"] and topic_now and topic_now == flip["topic"]:
                about = flip["about"].replace("{", "{{").replace("}", "}}")
                out.append((rn["flip"].replace("{topic}", about), {"answer": flip["answer"]}))
        # Ordinary thoughts only where they fit (a line of her own, or a plain reply), once each: no two
        # topics alike or about the same person.
        if sender is None or move in ("plain", "chat_warm", "dig_in"):
            seen, names = set(), set()
            for t in self._live_thoughts():
                low = t.topic.lower()
                who = {n for n in s.people if re.search(rf"\b{re.escape(n.lower())}\b", low)}
                if low in seen or who & names:
                    continue
                seen.add(low)
                names |= who
                out.append((t.topic.replace("{", "{{").replace("}", "}}"), {}))
        return out[:rn["mind"]]

    def _quiet_topic(self) -> Intent:
        """A quiet thought: a pushed-away topic (wound), or a memory her mood picks."""
        s, P = self.state, self.persona
        th = P["thoughts"]
        rng = self.roll("quiet_topic")
        # Ordinary memories: what chat said that didn't touch the wound (wound topics come back as wound
        # thoughts, from the intrusions), not her own lines (a thought about her line loops on itself).
        # (and not a dispute about what she said: "Rayleigh scattering" on her mind made her concede it)
        memories = [ev for ev in self.events if not ev.get("error") and not ev.get("wound") and not ev.get("disputed")
                    and not ev["gist"].startswith("Eileen:")]
        values = self.intrusions.values
        reason = "chat has been quiet for a while"
        if values and max(values.values()) >= th["intrusion_quiet"]:
            options = {f"w:{t}": th["intrusion_weight"] * v for t, v in values.items()}
            options.update({f"m:{i}": th["ordinary_weight"] for i in range(len(memories))})
            choice = pick(rng, options)
            if choice.startswith("w:"):
                topic = choice[2:]
                return Intent("think", reason, topic=topic, wound=True,
                              salience=max(th["salience_floor"], values[topic]))
            return Intent("think", reason, topic=memories[int(choice[2:])]["gist"], salience=th["salience_floor"])
        if not memories:
            return Intent("think", reason, salience=th["salience_floor"])
        dp = s.mood["pleasure"].value - s.mood["pleasure"].rest
        negative = set(NEGATIVE)
        positive = {k for k, x in s.emotions.items() if x.valence > 0}

        def weight(ev: dict) -> float:
            names = {c.split()[0] for c in ev["top"]}
            bad, good = bool(names & negative), bool(names & positive)
            if dp < -th["mood_pick"] and bad or dp > th["mood_pick"] and good:
                return th["mood_weight"]
            return 1.0

        options = {str(i): weight(ev) for i, ev in enumerate(memories)}
        return Intent("think", reason, topic=memories[int(pick(rng, options))]["gist"], salience=th["salience_floor"])

    def _callback(self, now: float) -> str | None:
        """A proud joke she could bring back, when chat is lively."""
        s, P = self.state, self.persona
        win = P["windows"]
        lively = sum(1 for t, _ in s.writers if now - t < win["lively"]) >= win["lively_count"]
        proud = [j for j in self.jokes if j.get("rating", 0.0) >= P["r13"]["proud"] and j.get("settled")]
        return proud[-1]["text"] if lively and proud else None

    def _remember(self, a: Appraisal, fx: Effects, person: Person, coping: Coping, text: str) -> None:
        """Hard moments can come back (brooding); dodged topics press to come back
        (intrusions); a mocked line she didn't answer with a comeback can come back
        as the perfect comeback, too late; a guess she was corrected on can flip."""
        s, P = self.state, self.persona
        th, cm, st = P["thoughts"], P["comedy"], P["stubbornness"]
        now = self.now
        if fx.hit >= th["moment_hit"]:
            topic = intrusion_topic(a.wound_topic, person.name)
            name, _ = fx.strongest(NEGATIVE)
            if name and name in fx.slow:
                amount, source = fx.slow[name]
                moment = Moment(name, amount, source, topic, a.gist, fx.hit, now)
                self.moments = (self.moments + [moment])[-12:]
                # A jab she could brush off doesn't keep her up; one brood per thing (the stronger one).
                brushed = fx.framing in ("mocking", "tool") and fx.hit * (1.0 - fx.deniable) < th["brood_x"]
                if fx.hit >= th["brood_hit"] and not brushed and fx.glitch != "echo":
                    same = [b for b in self.broods if b[1].source == moment.source or b[1].topic == moment.topic]
                    if not same or max(b[1].hit for b in same) < moment.hit:
                        for b in same:
                            self.broods.remove(b)
                        # its own draw, apart from the pending broods this message restarted
                        due = now + self._draw("thoughts", "rumination_after", f"rumination:{len(self.broods)}")
                        self.broods.append([due, moment])
            amount = fx.hit if coping.move in DODGES else th["intrusion_answered"] * fx.hit
            self.intrusions.add(topic, amount, a.gist, self._object(a.trigger, topic), now)
        # Judging someone whose peace mirrors her secret (a close likeness): it comes back later, quietly
        # ("Kai seemed fine with it."). The envy she hid is the hard moment; their peace presses to come back.
        r9 = P["r9"]
        if fx.judge >= r9["judge_from"] and a.likeness >= r9["mirror_from"]:
            amount, source = fx.slow.get("envy", (0.0, ""))
            topic = f"{person.name}'s peace"
            if amount > 0.0:
                moment = Moment("envy", amount, source, topic, a.gist, fx.judge, now)
                self.moments = (self.moments + [moment])[-12:]
                if not any(b[1].topic == topic for b in self.broods):
                    due = now + self._draw("thoughts", "rumination_after", f"rumination:{len(self.broods)}")
                    self.broods.append([due, moment])
            self.intrusions.add(topic, r9["intrusion"] * fx.judge, a.gist, "", now)
        if a.exist < 0.0:
            self.intrusions.add("being changed", P["r6"]["intrusion"] * -a.exist, a.gist,
                                self._object(a.trigger, "being changed"), now)
        mocked = fx.framing == "mocking" and fx.hit > 0.0
        if (mocked and coping.move != "comeback" and self.late_comeback is None
                and now - self.coper.late_at >= cm["late_every"] and self.roll("late_comeback").random() < cm["late_chance"]):
            self.coper.late_at = now
            self.late_comeback = {"at": now + self.roll("late_delay").uniform(*cm["late_delay"]), "who": person.name,
                                  "about": a.gist, "ready": False}
        if fx.contradicted == "depth" and a.contradicts in ("correct", "prove"):
            stance = open_stance(s)
            if (stance is not None and not stance.data.get("canon")
                    and not any(f["claim"] == stance.note for f in self.flips)
                    and self.roll("flip").random() < st["flip_chance"]):
                self.flips.append({"at": now + st["flip_after"], "claim": stance.note, "topic": stance.data["topic"],
                                   "correction": f"{person.name}: {text}", "ready": False})

    def _object(self, word: str, topic: str) -> str:
        """An ordinary word the busy-chat slip could bring up ("dinner"): only for a concrete intrusion topic
        (food, sleep, body, family), and "" when it's one of the banned words."""
        ok = topic in self.persona["thoughts"]["busy_slip_topics"]
        return word if word and ok and not self.lint(word) else ""

    def _own_it(self) -> None:
        """The first time in a stream her guilt toward one person reaches 0.4: her next reply to them owns it."""
        if self._own_it_used:
            return
        e = self.state.emotions
        for person in self.state.people.values():
            if e["guilt"].aimed_at(person.name) >= self.persona["r14"]["own_it"]:
                person.own_it_due, self._own_it_used = True, True
                self.calc.append(f"her guilt toward {person.name} reached {self.persona['r14']['own_it']}: she'll own it")
                return

    def _drop_overdue(self) -> None:
        """A thought that came due while she was busy (speaking or reading) is dropped when a message arrives."""
        busy = self._busy_at
        for b in [b for b in self.broods if b[0] <= busy]:
            self.broods.remove(b)
        late = self.late_comeback
        if late and not late["ready"] and not late.get("asked") and late["at"] <= busy:
            self.late_comeback = None
        self.flips = [f for f in self.flips if f["ready"] or f.get("asked") or f["at"] > busy]

    def _covering(self) -> bool:
        """Covering, from 2 to 5 minutes after a crack, while chat is active, on the
        strained rung or higher, and not in the exhausted quiet."""
        P = self.persona
        lo, hi = P["crack"]["cover"]
        active = any(self.now - t < P["windows"]["chat_active"] for t, _ in self.state.writers)
        return (lo <= self.now - self.coper.crack_at <= hi and active and self.rung in ("composed", "strained")
                and self.now >= self.state.exhausted_until)

    def _punchline(self, line: dict) -> float | None:
        """When her line (a joke) ended, her punchline: chat's silence is counted from
        there. None while she's still saying it."""
        if self._line_open or self.line_ended_at is None or not line:
            return None
        return max(line["at"], self.line_ended_at)

    def _crack_phase(self) -> str:
        if self.coper.crack_at == -math.inf:
            return ""
        age = self.now - self.coper.crack_at
        lo, hi = self.persona["crack"]["leak"]
        if age < lo:
            return "freeze"
        if age < hi:
            return "leak"
        if age < hi + 1.0:
            return "re-mask"
        if self._covering():
            return "covering"
        return ""

    def _update_rung(self) -> None:
        """Falling a rung is immediate; climbing back needs 20 s on the rung, then she
        climbs to whichever rung her composure qualifies for."""
        r = self.persona["rungs"]
        c = self.state.wound["composure"].value
        order = ["overwhelmed", "strained", "composed"]
        down = "composed" if c > r["strained_below"] else "strained" if c >= r["overwhelmed_below"] else "overwhelmed"
        up = "composed" if c >= r["composed_from"] else "strained" if c >= r["strained_from"] else "overwhelmed"
        old = self.rung
        if order.index(down) < order.index(self.rung):
            self.rung, self.rung_since = down, self.now
        elif order.index(up) > order.index(self.rung) and self.now - self.rung_since >= r["min_seconds"]:
            self.rung, self.rung_since = up, self.now
        if self.rung != old:
            if old == "overwhelmed":
                self.overwhelmed.append((self.rung_since_overwhelmed, self.now))
            if self.rung == "overwhelmed":
                self.rung_since_overwhelmed = self.now
            self.calc.append(f"rung: {old} → {self.rung} (composure {c:.2f})")
            _LOGGER.info("  mind: rung %s → %s (composure %.2f)", old, self.rung, c)
            self._log({"kind": "system", "text": f"rung {old} → {self.rung}", "composure": round(c, 3)})

    def _exhaustion(self) -> None:
        """90 s on the overwhelmed rung within 5 minutes: she goes quiet for 60 s.
        Afterwards it can't trigger again for 5 minutes."""
        ex = self.persona["exhaustion"]
        now, s = self.now, self.state
        if now < s.exhausted_until or now - s.exhausted_until < ex["lockout"]:
            return
        stretches = [(a, b) for a, b in self.overwhelmed if now - b < ex["window"]]
        if self.rung == "overwhelmed":
            stretches.append((self.rung_since_overwhelmed, now))
        total = sum(min(b, now) - max(a, now - ex["window"]) for a, b in stretches if b > now - ex["window"])
        if total >= ex["overwhelmed_for"]:
            s.exhausted_until = now + ex["quiet_for"]
            self.overwhelmed = []
            if self.rung == "overwhelmed":
                self.rung_since_overwhelmed = now
            self.calc.append(f"exhausted: she goes quiet for {ex['quiet_for']} s")
            _LOGGER.info("  mind: the exhausted quiet")
            self._log({"kind": "system", "text": "the exhausted quiet"})

    def _prospect_lines(self, arrived: float) -> list[str]:
        """What she's waiting on, for the appraiser, one line each."""
        s, win = self.state, self.persona["windows"]
        out = []
        for x in s.prospects:
            if x.kind == "exposure":
                out.append(f"exposure: {x.note}; she dodged")
            elif x.kind == "joke":
                out.append("joke: her last line was a joke")
            elif x.kind == "win":
                out.append(f"stance: she said {x.note}")
        if arrived - s.glitch_at < win["glitch"]:
            out.append(f"glitch: her voice skipped a {s.glitch_what}")
        if arrived - s.slip_at < win["slip"]:
            out.append(s.slip_line)
        if s.honest_to:
            out.append(f"honest: she gave {s.honest_to} a straight answer")
        return out

    def _card(self, sender: str) -> dict:
        c = self.persona["card"]
        person = self.state.people.get(sender)
        f = person.familiarity if person else 0.0
        L = person.liking if person else 0.0
        return {"name": sender,
                "familiarity": "new" if f < c["familiarity"]["seen"] else "seen" if f < c["familiarity"]["regular"]
                else "regular",
                "liking": "dislikes" if L < c["liking"]["dislikes"] else "neutral" if L < c["liking"]["likes"]
                else "likes"}

    def _person_line(self, person: Person) -> str:
        line = sender_line(self.state, self.persona, person, self.now, self.coper.replies)
        return line[0].format(**line[1]) if line else ""

    def _person(self, name: str) -> Person:
        if name not in self.state.people:
            self.state.people[name] = Person(name, last_seen=self.now, counts_at=self.now)
        return self.state.people[name]

    def _joke_item(self, j: dict) -> dict:
        return {"text": j["text"], "shape": j["shape"], "her_rating": round(j["rating"], 2),
                "verdict": j.get("verdict", "waiting" if not j.get("settled") else "")}

    def _leaks_since(self, t: float) -> list[str]:
        start = t - self.start
        return [ev["name"] for ev in self.lane if ev["kind"] == "leak" and ev["t"] >= start]

    def _lane_since(self, t: float) -> list[list[str]]:
        """Body events since her line began (and the reading before it): the face check reads them."""
        start = (self.last.at if self.last is not None else t) - self.start
        return [[ev["kind"], ev["name"]] for ev in self.lane if ev["t"] >= start]

    def _error(self, text: str) -> None:
        self.errors.append({"t": round(self.now - self.start, 1), "text": text[:240]})
        self._log({"kind": "error", "text": text})
        _LOGGER.warning("  mind error: %s", text[:240])  # loud in the terminal too, not only the panel

    def _bar(self, bar_id: str, group: str, label: str, v: float, base: float, lo: float, hi: float, color: str,
             hint: str, fast: float | None = None, slow: float | None = None, shown: float | None = None,
             src: str = "", rule: str = "") -> dict:
        item = {"id": bar_id, "group": group, "label": label, "v": round(v, 3), "base": round(base, 3), "lo": lo,
                "hi": hi, "color": color, "hint": hint, "last": self.last_change.get(bar_id)}
        if fast is not None:
            item.update({"fast": round(min(fast, v), 3), "slow": round(min(slow, v), 3), "shown": round(shown, 3),
                         "src": " → ".join(x for x in src.split("|") if x), "rule": rule})
        return item

    def _values(self) -> dict[str, float]:
        s = self.state
        out = {f"emotion.{k}": x.value for k, x in s.emotions.items()}
        out.update({f"mood.{k}": v.value for k, v in s.mood.items()})
        out.update({f"wound.{k}": v.value for k, v in s.wound.items()})
        out.update({f"drive.{k}": v.value for k, v in s.drives.items()})
        return out

    @staticmethod
    def _deltas(before: dict[str, float], after: dict[str, float]) -> dict[str, list[float]]:
        return {k: [round(before.get(k, v), 3), round(v, 3)] for k, v in after.items()
                if abs(v - before.get(k, v)) >= 0.005}

    def _mark_changes(self, before: dict[str, float]) -> None:
        after = self._values()
        for k, v in after.items():
            d = v - before.get(k, v)
            if abs(d) >= 0.01:
                self.last_change[k] = {"seq": self.seq, "d": round(d, 3)}

    def _top_changes(self, before: dict[str, float]) -> list[str]:
        after = self._values()
        changes = sorted(((k, after[k] - before.get(k, after[k])) for k in after), key=lambda kv: -abs(kv[1]))
        return [f"{k.split('.')[-1]} {d:+.2f}" for k, d in changes[:3] if abs(d) >= 0.02]

    def _calc_lines(self, r: Reading) -> list[str]:
        lines = [f"#{r.seq} {r.sender}: \"{r.text}\""[:100]]
        if r.appraisal:
            lines.append(f"{'appraisal':<10} {r.appraisal.summary()}")
        for label, text in r.effects.trace:
            lines.append(f"{label:<10} {text}")
        c = r.coping
        lines.append(f"{'move':<10} {c.rung or '-'} · {c.why} → {c.move}" + (f" ({c.shape})" if c.shape else ""))
        if c.weights:
            lines.append(f"{'weights':<10} " + " · ".join(f"{k} {v:.2f}" for k, v in c.weights.items() if v > 0))
        w = self.state.wound
        lines.append(f"{'state':<10} threat {w['threat'].value:.2f} · composure {w['composure'].value:.2f}"
                     f" · doubt {w['doubt'].value:.3f} · S {self.suppression():.2f} · rung {self.rung}")
        return lines

    def _log(self, record: dict) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"seq": self.seq, "t": round(self.now - self.start, 2), **record}, ensure_ascii=False,
                               default=str) + "\n")
