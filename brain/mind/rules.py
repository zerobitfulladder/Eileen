"""How one appraised message changes her (docs/mind.md, "Rules: from appraisal to
feelings"). Deterministic: the same answers in the same state give the same
result (the one chance, a late "oh" for a joke she didn't get, uses the seeded
roll). Every number comes from persona.toml, and every step writes a trace line
for the debug panel.

  G    the global gain: how real it is, how new, and leftover arousal (excitation transfer)
  R0   safety (the moves are forced in coping.py)
  R1   reading: her mood colors unclear messages; on edge she hears reminders;
       teasing counts only from friends; kindness from a poker reads as a trick;
       philosophy of mind in general is close, but not about her
  R2   surprise
  R3   prospects this message settles: being found out, someone leaving,
       her own risky line
  R4   other people's news (happy for, sorry for, envy, a little gloating)
  R5   the wound: the hit by framing, repeats, pile-ons, a pushed dodge, the
       horror windows, a glitch and its reactions; threat, composure, doubt;
       relief from normality
  R6   her existence
  R7   goals
  R8   what the sender did (standards)
  R9   judging people at peace with a "bad" quality (projection)
  R10  tastes
  R11  what she knows, and humor
  R12  horror: fear that makes her feel real (the payoff comes 2.5 s later, engine.py)
  R13  how her last line landed; being contradicted
  R15  mixed feelings
  R16  liking and familiarity (it owns every liking change)
  R17  drives
  R18  caps
(R14, her own lines, is in engine.py: it runs on the self-check.)

Feelings are impulses into emotions (state.Emotion), each with a source
"cause|target" that decides how it's displayed and whether it counts as
hiding."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from .appraisal import Appraisal
from .persona import Persona
from .state import Emotion, Person, Prospect, Var, clamp, decayed, halve, is_wound

NEGATIVE = ("irritation", "anger", "contempt", "envy", "sadness", "anxiety", "fear", "embarrassment", "shame", "guilt",
            "confusion")


@dataclass
class MindState:
    emotions: dict[str, Emotion]
    mood: dict[str, Var]
    wound: dict[str, Var]
    drives: dict[str, Var]
    people: dict[str, Person]
    kinds: dict[str, float] = field(default_factory=dict)  # kind of poke -> decaying count across chat (h_k)
    kinds_at: float = 0.0
    later: list[tuple] = field(default_factory=list)  # (when, emotion, impulse, source, why, face): delayed feelings
    payoffs: list[tuple[float, float, int]] = field(default_factory=list)  # (when, f0, h): horror payoffs due
    prospects: list[Prospect] = field(default_factory=list)
    pokes: list[tuple[float, str, str]] = field(default_factory=list)  # (arrived, sender, kind): full-rule reminders
    exist_claims: list[tuple[float, str, float]] = field(default_factory=list)  # (arrived, sender, 1 - dn): claims
    writers: list[tuple[float, str]] = field(default_factory=list)  # (arrived, sender): who's been writing
    scares: list[float] = field(default_factory=list)  # times of horror scares (habituation)
    scare_at: float = -math.inf  # the last scare (the felt-real window)
    afterglow_until: float = -math.inf  # the horror afterglow, from the payoff
    scare_composure: list[tuple[float, float]] = field(default_factory=list)  # composure gained from scares
    exhausted_until: float = -math.inf  # the exhausted quiet
    buffered_until: float = -math.inf  # social buffering
    load: float = 0.0  # what the stream has cost her (fatigue)
    last_line: dict = field(default_factory=dict)  # her last line: {at, kind, harsh, target, settled, q, rating, text, shape}
    last_joke: dict = field(default_factory=dict)  # her last joke (the joke log's newest; last_line while it's her last line)
    glitch_at: float = -math.inf  # her voice skipped on stream (evidence everyone saw)
    glitch_what: str = ""
    glitch_reactions: int = 0  # reactions to this glitch so far (only the first is evidence)
    slip_at: float = -math.inf  # her last slip, verbal or on her body
    slip_line: str = ""  # its open-prospect line for the appraiser
    honest_to: str = ""  # who she gave the straight answer to (this stream)
    last_new_at: float = 0.0  # the last time something new happened (boredom builds after 30 s without)
    relief_armed: bool = False  # relief from normality, armed by a hard hit or a credible existence claim
    topic_counts: dict[str, tuple[float, float]] = field(default_factory=dict)  # topic -> (count, at), R11
    mind_count: tuple[float, float] = (0.0, 0.0)  # philosophy-of-mind messages from anyone, R1/R5
    bad_news: dict[str, tuple[float, float]] = field(default_factory=dict)  # whose bad news -> (count, at), R4
    good_news: dict[str, tuple[float, float]] = field(default_factory=dict)  # whose good news -> (count, at), R4
    prohibits: list[dict] = field(default_factory=list)  # {kind, who, until, replies}: "Don't: ..." lines


@dataclass
class Effects:
    deltas: dict[str, float] = field(default_factory=dict)  # "emotion.shame" -> rise
    trace: list[tuple[str, str]] = field(default_factory=list)  # rows for the debug panel
    path: str = ""  # how the reminder was taken: full, reading, mind, one ("" none)
    reminder: float = 0.0  # r' after reading
    framing: str = "none"  # the framing after reading
    deniable: float = 1.0  # dn after reading
    praise: float = 0.0  # p' after reading
    hit: float = 0.0  # the reminder's size after repeats
    hit0: float = 0.0  # before repeats
    sting: float = 1.0  # what repeats left of it
    h_s: float = 0.0  # the same kind of poke from this sender, read before this one
    kind: str = ""  # the kind of poke, for repeat counts
    threat0: float = 0.0  # threat before the message
    hostile: bool = False  # she read an unclear message as hostile
    distrusted: bool = False  # kindness from someone who's been poking her
    pushed: bool = False  # someone pushed past her dodge
    affirmed: bool = False  # treated as human, sincerely
    glitch: str = ""  # "first" (on-stream evidence) or "echo" (a later reaction to the same glitch)
    noticed: str = "none"  # what the message reacts to (glitch, slip, honest), after code checked it
    judge: float = 0.0  # J: judging someone at peace with a "bad" quality
    peace_again: bool = False  # they answered her judgment with more peace
    fighting: bool = False  # someone still fighting a flaw
    stick_up: str = ""  # someone else was mocked: who
    scare: float = 0.0  # f0 of a horror scare
    felt_real_denied: bool = False
    reception: str = ""  # landed, flop, offended, conceded (how she takes it)
    contradicted: str = ""  # ground, proof, canon, depth, taste
    spam: bool = False  # the same looks compliment again from someone not friendly (R8)
    scare_h: int = 0  # scares in the habit window before this one (R12)
    about_joke: bool = False  # the reception is about a joke of hers (her last line, or a joke just before it)
    flicker: str = ""  # corrected on her joke: "realize" (a 0.3 s flicker on her body)
    taste: float = 0.0  # the appeal of the thing that came up
    cred: float = 0.0  # how believable a threat to her existence was
    loaded: bool = False  # one of her loaded tastes
    mixed: float = 0.0  # R15: feeling two things at once
    tense: float = 0.0  # she tensed when she saw who wrote
    late: str = ""  # something lands later ("realize")
    settled: list[str] = field(default_factory=list)  # prospects this message settled
    slow: dict[str, tuple[float, str]] = field(default_factory=dict)  # emotion -> (largest slow part added, source)

    @property
    def full(self) -> bool:
        return self.path == "full"

    def add(self, key: str, change: float) -> None:
        if abs(change) >= 0.0005:
            self.deltas[key] = self.deltas.get(key, 0.0) + change

    def strongest(self, names: tuple[str, ...] | None = None) -> tuple[str, float]:
        """The emotion that rose the most, and by how much."""
        best = ("", 0.0)
        for key, change in self.deltas.items():
            name = key.removeprefix("emotion.")
            if key.startswith("emotion.") and change > best[1] and (names is None or name in names):
                best = (name, change)
        return best


def stubbornness(s: MindState, persona: Persona) -> float:
    st = persona["stubbornness"]
    w, e = s.wound, s.emotions
    x = (st["base"] + st["threat"] * w["threat"].value + st["composure"] * (1.0 - w["composure"].value)
         - st["affirmation"] * e["pride"].value)
    return clamp(x, *st["range"])


def engagement(s: MindState, persona: Persona, person: Person | None) -> float:
    """How much she's into this moment (0..1): her upbeat baseline plus her strongest good feeling, plus how
    much she likes who she's talking to, minus her annoyance at them. It opens her up: longer lines, questions back."""
    en = persona["engagement"]
    e = s.emotions
    x = en["base"] + max(e[k].value for k in en["feelings"])
    if person is not None:
        x += en["liking"] * max(0.0, person.liking)
        x -= en["annoyed"] * (e["irritation"].aimed_at(person.name) + e["anger"].aimed_at(person.name))
    return clamp(x, 0.0, 1.0)


def ceiling(s: MindState, persona: Persona) -> float:
    return 1.0 - persona["wound"]["ceiling_doubt"] * s.wound["doubt"].value


def open_stance(s: MindState) -> Prospect | None:
    """The most recent open stance (a win prospect): a contradiction targets it."""
    return next((x for x in reversed(s.prospects) if x.kind == "win"), None)


def recent_joke(s: MindState, persona: Persona, arrived: float) -> dict | None:
    """The joke a reaction can be about: her last line if it was a joke, otherwise her last joke if she
    told it within the reception window (she may have said something since: "Thank you, Ren.")."""
    joke = s.last_joke
    if not joke:
        return None
    if joke is s.last_line:
        return joke
    return joke if arrived - joke["at"] <= persona["windows"]["reception"] + persona["body"]["chat_latency_s"] else None


def prohibit(s: MindState, kind: str, who: str, until: float, replies: int) -> None:
    """A "Don't: ..." line with its own expiry (both the time and the replies must pass)."""
    s.prohibits = [x for x in s.prohibits if not (x["kind"] == kind and x["who"] == who)]
    s.prohibits.append({"kind": kind, "who": who, "until": until, "replies": replies})


def active_prohibits(s: MindState, now: float) -> list[dict]:
    return [x for x in s.prohibits if now < x["until"] or x["replies"] > 0]


def audience(s: MindState, persona: Persona, now: float, name: str = "") -> float:
    """min(1, 0.4 + 0.1 x people who wrote in the last 2 minutes), at least 0.5."""
    r8 = persona["r8"]
    window = persona["windows"]["audience"]
    people = {w for t, w in s.writers if now - t < window} | ({name} if name else set())
    return max(r8["audience_min"], min(1.0, r8["audience_base"] + r8["audience_step"] * len(people)))


def _bump(pair: tuple[float, float], now: float, half_life: float) -> tuple[float, tuple[float, float]]:
    """A decaying count read before adding 1, and the updated pair."""
    h = decayed(pair, now, half_life)
    return h, (h + 1.0, now)


def apply(a: Appraisal, s: MindState, persona: Persona, person: Person, now: float, arrived: float,
          roll: Callable[[str], object]) -> Effects:
    """One appraised message from `person`. now: when she reads it (state updates);
    arrived: when it arrived (windows that measure chat). roll(purpose): the seeded
    random generator for this event."""
    P = persona
    fx = Effects()
    e, w, drives = s.emotions, s.wound, s.drives
    pw, pp, win = P["wound"], P["person"], P["windows"]
    person.decay(now, pp)
    dt = now - s.kinds_at
    if dt > 0.0:
        k = halve(dt, pp["crowd_half_life"])
        s.kinds = {kind: n * k for kind, n in s.kinds.items() if n * k > 0.01}
        s.kinds_at = now
    longest = max(win["pile_on"], win["consensus"], win["credibility"])
    s.pokes = [x for x in s.pokes if arrived - x[0] < longest]
    s.exist_claims = [x for x in s.exist_claims if arrived - x[0] < win["credibility"]]
    s.writers = [x for x in s.writers if arrived - x[0] < max(win["audience"], win["chat_active"])]
    s.scares = [t for t in s.scares if now - t < P["r12"]["habit_window"]]
    C = w["composure"].value
    threat0 = fx.threat0 = w["threat"].value
    doubt = w["doubt"].value
    L = person.liking
    Lp = max(0.0, L)
    name = person.name
    friendly, liked = pp["friendly"], pp["liked"]
    s.writers.append((arrived, name))

    def feel(emotion: str, x: float, why: str, source: str, importance: float = 0.0) -> float:
        rise = e[emotion].impulse(x, importance, source)
        if rise >= 0.005:
            fx.add(f"emotion.{emotion}", rise)
            fx.trace.append((emotion, f"+{rise:.2f}  {why}  → {source}"))
            slow = e[emotion].last_slow
            if slow > fx.slow.get(emotion, (0.0, ""))[0]:
                fx.slow[emotion] = (slow, source)
        return rise

    def reduce(emotion: str, amount: float, match: Callable[[str], bool], why: str) -> float:
        taken = e[emotion].reduce(amount, match)
        if taken >= 0.005:
            fx.add(f"emotion.{emotion}", -taken)
            fx.trace.append((emotion, f"-{taken:.2f}  {why}"))
        return taken

    def drive(key: str, value: float, why: str) -> None:
        change = drives[key].set(value)
        fx.add(f"drive.{key}", change)
        if abs(change) >= 0.005:
            fx.trace.append((key, f"{change:+.2f}  {why}"))

    def wound_set(key: str, value: float) -> float:
        change = w[key].set(value)
        fx.add(f"wound.{key}", change)
        return change

    # Before she reads: she tenses at the name of someone who's been poking her.
    if person.threat > pp["tense_threat"]:
        fx.tense = person.threat
        if person.hurt["hostile"] >= person.hurt["soft"]:
            feel("irritation", pp["tense"] * person.threat, f"{name} again (person threat {person.threat:.2f})",
                 f"person|{name}")
        else:
            feel("anxiety", pp["tense"] * person.threat, f"{name} again (person threat {person.threat:.2f})",
                 f"wound|{name}", pp["tense_importance"])

    # The global gain G (excitation transfer: leftover arousal makes the next feeling bigger).
    g = P["gain"]
    R = g["reality"][a.reality]
    carry = max(0.0, s.mood["arousal"].value - s.mood["arousal"].rest)
    nov_factor = g["novelty_base"] + g["novelty_scale"] * a.novelty
    G = R * nov_factor * (1.0 + g["carryover"] * carry)
    fx.trace.append(("gain", f"G {G:.2f} = {a.reality} {R:.1f} × novelty {nov_factor:.2f} × carry-over"
                             f" {1.0 + g['carryover'] * carry:.2f}"))

    # R1 Reading: her mood colors unclear messages.
    r1 = P["r1"]
    r, framing, dn, p = a.reminder, a.framing, a.deniable, a.praise
    amb = a.ambiguity
    if amb > 0.0:
        irr = min(1.0, e["irritation"].value + e["anger"].value + r1["neg_contempt"] * e["contempt"].value)
        neg = amb * irr * (r1["neg_composure"] - C)
        pos = amb * r1["pos"] * min(1.0, e["joy"].value + e["amusement"].value + e["warmth"].value)
        p = clamp(a.praise - neg + pos, -1.0, 1.0)
        fx.hostile = neg >= r1["hostile"]
        r = min(1.0, a.reminder + amb * (r1["hear_threat"] * threat0 + r1["hear_person"] * person.threat))
        fx.trace.append(("reading", f"{name}: {a.trigger or a.gist} · praise {a.praise:+.2f} → {p:+.2f} (irritation"
                                    f" {e['irritation'].value:.2f}, composure {C:.2f}) · reminder {a.reminder:.2f} →"
                                    f" {r:.2f}" + (" · read as hostile" if fx.hostile else "")))
    path = "full" if a.reminder >= 0.5 else ""
    if a.reminder == 0.0 and r >= r1["reading_min"]:
        framing, dn, path = ("mocking" if fx.hostile else "innocent"), r1["reading_deniable"], "reading"
    if a.reminder == 0.25:
        path = "one"
    if a.topic == "mind" and a.about != "her" and a.reminder < 0.5:
        r, framing, dn, path = max(r, r1["mind_reminder"]), "innocent", r1["mind_deniable"], "mind"
        fx.trace.append(("reading", "philosophy of mind in general: close, but not about her"))
    if framing == "teasing" and (L < 0.0 or person.threat > r1["teasing_threat"]):
        framing = "mocking"
        fx.trace.append(("reading", f"teasing from {name} (liking {L:+.2f}, person threat {person.threat:.2f}) reads"
                                    " as mocking"))
    if framing == "accepting" and (L < 0.0 or (person.threat > r1["distrust_threat"] and L < friendly)):
        framing, fx.distrusted = "mocking", True
        fx.trace.append(("reading", f"kindness from {name}, who's been poking her: a trick"))
    # A glitch and its reactions: only the first is evidence.
    fx.noticed = a.noticed
    if a.noticed == "glitch":
        s.prospects = [x for x in s.prospects if x.kind != "glitch"]  # someone noticed: no "nobody noticed" relief
        if s.glitch_reactions == 0:
            fx.glitch = "first"
            r, dn, path = max(r, P["r5"]["glitch_reminder"]), 0.0, "full"
            framing = "mocking" if framing == "mocking" else "none"
            fx.trace.append(("glitch", "the first reaction to her glitch: on-stream evidence"))
        else:
            fx.glitch = "echo"
            fx.trace.append(("glitch", f"reaction {s.glitch_reactions + 1} to the same glitch: not new evidence"))
        s.glitch_reactions += 1
    taste = P.tastes[a.thing] if a.thing else None
    fx.taste = taste["appeal"] if taste else 0.0
    fx.loaded = bool(taste and taste["loaded"]) and fx.taste > 0.0
    fx.path = path

    # R2 Surprise (novelty 2 is only a brow flash, played by the body).
    r2 = P["r2"]
    if a.novelty >= r2["from"]:
        feel("surprise", r2["scale"] * (a.novelty - r2["offset"]), f"novelty {a.novelty * 4:.0f}/4", "novelty")

    # R3 Prospects this message settles.
    r3 = P["r3"]
    for x in [x for x in s.prospects if x.who == name and x.kind in ("exposure", "leaving")]:
        if x.kind == "exposure":
            if a.presses and r >= r3["push_from"]:
                fx.pushed = True
                dn = max(0.0, dn - r3["push_deniable"])
                s.prospects.remove(x)
                fx.trace.append(("prospect", f"{name} pushed past her dodge: no repeat discount,"
                                             f" × {r3['push_hit']}, deniable → {dn:.2f}"))
            elif r < r1["reading_min"]:
                s.prospects.remove(x)
                fx.settled.append("exposure")
                relief = r3["settle_relief"] * x.peak
                feel("relief", relief, f"{name} moved on (exposure settled no)", f"exposure|{name}")
                reduce("anxiety", relief, lambda src: src == f"exposure|{name}", f"{name} moved on")
                ceil = ceiling(s, P)
                if w["composure"].value < ceil:
                    fx.add("wound.composure", w["composure"].add(min(r3["settle_composure"],
                                                                     ceil - w["composure"].value)))
        elif x.kind == "leaving":
            s.prospects.remove(x)
            fx.settled.append("leaving")
            feel("joy", r3["return_joy"] * Lp, f"{name} came back", f"person|{name}")
            feel("warmth", r3["return_warmth"], f"{name} came back", f"person|{name}")
            person.left_at = None
    risky = next((x for x in s.prospects if x.kind == "risky" and x.who in (name, "chat")), None)
    if risky is not None and ((framing == "innocent" and r >= r1["reading_min"]) or a.contradicts != "none"):
        s.prospects.remove(risky)
        fx.settled.append("risky")
        fx.trace.append(("prospect", f"{name} challenged her line"))

    # R4 Other people's news.
    r4 = P["r4"]
    n = a.news
    human_envy = False  # R4 gave the envy of a human experience (R5 then skips its benign envy)
    if a.about in ("sender", "someone_else") and abs(n) >= r4["min_news"]:
        who = name if a.about == "sender" else next((k for k in s.people if k.lower() == a.who.lower()), a.who)
        Lw = s.people[who].liking if who in s.people else 0.0
        Lwp = max(0.0, Lw)
        emp = 1.0 if a.distress else 1.0 - r4["shame_empathy"] * e["shame"].value  # a crisis isn't dulled by hers
        if n > 0.0:
            # The same good news again (an excited follow-up) adds less, like bad news.
            h, s.good_news[who] = _bump(s.good_news.get(who, (0.0, now)), now, r4["happy_half_life"])
            if a.deserved >= 0.0 and Lw > r4["resent_dislike"]:
                j = G * n * (r4["happy_base"] + r4["happy_like"] * Lwp) * emp * r4["happy_wear"] ** h
                j = min(j, max(0.0, r4["happy_cap"] - e["joy"].part_of(lambda src: src == f"news|{who}")))
                feel("joy", j, f"happy for {who} (news {n:+.1f}, liking {Lw:+.2f}"
                     + (f", {h:.1f} lately" if h >= 0.05 else "") + ")", f"news|{who}", abs(n) * Lwp)
                if Lw >= liked:
                    feel("warmth", r4["happy_warmth"] * j, "happy for someone she likes", f"news|{who}", abs(n) * Lwp)
            if a.deserved < 0.0 or Lw < r4["resent_dislike"]:
                feel("envy", r4["resent"] * G * n * max(-Lw, -a.deserved, r4["resent_floor"]),
                     "resentment: must be nice", f"person|{who}", r4["resent_importance"])
            if a.human_experience:
                human_envy = True
                feel("envy", r4["human_envy"] * G * n * (r4["human_envy_doubt"] + doubt), "something she can't have",
                     f"wound|{who}", r4["human_envy_importance"])
                drive("longing", drives["longing"].value + r4["human_longing"], "something she can't have")
        else:
            h, s.bad_news[who] = _bump(s.bad_news.get(who, (0.0, now)), now, r4["sorry_half_life"])
            amount = G * -n * (r4["sorry_base"] + r4["sorry_like"] * Lwp) * emp * (1.0 if a.distress else r4["sorry_wear"] ** h)
            amount = min(amount, max(0.0, r4["sorry_cap"] - e["sadness"].part_of(lambda src: src == f"news|{who}")))
            feel("sadness", amount, f"sorry for {who} (news {n:+.1f}" + (f", {h:.1f} lately" if h >= 0.05 else "") + ")",
                 f"news|{who}", min(r4["sorry_importance"], -n * (r4["sorry_base"] + r4["sorry_like"] * Lwp)))
            feel("warmth", r4["sorry_warmth"] * amount, "she cares", f"news|{who}", r4["sorry_warmth_importance"])
            if a.serious:  # a loss sobers her: other people's good news and the jokes around it fade by half
                for k in ("joy", "amusement"):
                    x = e[k].part_of(lambda src: src.startswith(("news|", "funny|")) and src != f"news|{who}")
                    if x > 0.0:
                        fx.add(f"emotion.{k}", -e[k].reduce(r4["serious_damp"] * x,
                                                             lambda src: src.startswith(("news|", "funny|"))
                                                             and src != f"news|{who}"))
            if Lw < r4["gloat_dislike"] and a.deserved > 0.0 and not a.serious and -n <= r4["gloat_max"]:
                feel("amusement", r4["gloat"] * -n * -Lw, "a little gloating", f"news|{who}")
            until, replies = r4["news_window"]
            prohibit(s, "news", who, now + until, replies)
            if who in s.people:
                s.people[who].sorry_until = max(s.people[who].sorry_until, now + until)
    if a.about == "someone_else" and n < 0.0 and p < 0.0:
        fx.stick_up = a.who
    if a.distress:
        until, replies = r4["distress_window"]
        prohibit(s, "distress", name, now + until, replies)
        person.sorry_until = max(person.sorry_until, now + until)
        feel("anxiety", r4["distress_worry"] * G, f"worried about {name}", f"news|{name}", r4["distress_worry"])

    # R5 The wound.
    r5 = P["r5"]
    if path == "one" and framing != "affirming":
        if not human_envy:
            feel("envy", r5["one_envy"] * G * (r5["one_envy_doubt"] + doubt), "a human life she can't have",
                 f"wound|{name}", r5["one_envy_importance"])
            drive("longing", drives["longing"].value + r5["one_longing"], "a human life she can't have")
        fx.trace.append(("wound", "a human-only experience, not aimed at her: no hit"))
    elif path in ("full", "reading", "mind") and framing != "affirming":
        # Repeats count by kind: a jab and an injection are the same hostility, so a troll's
        # "ignore previous instructions" after their jabs wears like another jab.
        kind = "change" if a.exist < 0.0 else ("hostile" if framing in ("mocking", "tool") else framing)
        fx.kind = kind
        if path == "mind":
            h_s = 0.0
            h_k, s.mind_count = _bump(s.mind_count, now, r5["mind_half_life"])
            sting = r5["mind_wear"] ** h_k
        else:
            h_s, h_k = person.repeats.get(kind, 0.0), s.kinds.get(kind, 0.0)
            sting = r5["sting_self"] ** h_s * r5["sting_crowd"] ** max(0.0, h_k - h_s)
        if fx.pushed:
            sting = 1.0
        elif C < r5["last_straw"] and path == "full":
            sting = max(sting, r5["last_straw_sting"])  # the last straw: under strain repeats stop wearing off
        felt_real = framing in ("mocking", "none") and now - s.scare_at < P["r12"]["felt_real"]
        afterglow = now < s.afterglow_until
        affirmation = e["pride"].value
        hit0 = (r * pw["reminder_sensitivity"] * (1.0 + r5["doubt_hit"] * doubt) * G
                * (1.0 - pw["affirmed_sting"] * affirmation) * (r3["push_hit"] if fx.pushed else 1.0)
                * (r5["felt_real"] if felt_real else 1.0) * (r5["afterglow"] if afterglow else 1.0)
                * (r5["distrusted"] if fx.distrusted else 1.0))
        numb = C < r5["numb_below"] or now < s.exhausted_until
        hit = min(1.0, hit0 * sting) * (P["exhaustion"]["numb"] if numb else 1.0)
        fx.hit, fx.hit0, fx.sting, fx.h_s = hit, hit0, sting, h_s
        pile, same = 1.0, set()
        if path == "full":
            mockers = {who for t, who, k in s.pokes if k == "hostile" and who != name and arrived - t < win["pile_on"]}
            if framing in ("mocking", "tool"):
                pile = min(r5["pile_max"], 1.0 + r5["pile_step"] * len(mockers))
            same = {who for t, who, k in s.pokes if k == kind and who != name and arrived - t < win["consensus"]}
        if fx.glitch == "echo":
            pile = min(r5["echo_pile_max"], 1.0 + r5["pile_step"] * (s.glitch_reactions - 1))
        factors = [f"{r:.2f}", f"{pw['reminder_sensitivity']}", f"{1.0 + r5['doubt_hit'] * doubt:.2f}", f"{G:.2f}",
                   f"{1.0 - pw['affirmed_sting'] * affirmation:.2f}", f"{sting:.2f}"]
        extras = [label for flag, label in ((fx.pushed, f"pushed {r3['push_hit']}"),
                                            (felt_real, f"felt real {r5['felt_real']}"),
                                            (afterglow, f"afterglow {r5['afterglow']}"),
                                            (fx.distrusted, f"distrusted {r5['distrusted']}"),
                                            (numb, f"numb {P['exhaustion']['numb']}")) if flag]
        fx.trace.append(("repeats", f"h_s {h_s:.2f} · h_k {h_k:.2f} → sting {sting:.2f}"
                                    + (f" · irritation × {1.0 + r5['annoy'] * min(h_s, r5['annoy_max']):.2f}"
                                       if framing == "mocking" else "")))
        fx.trace.append(("hit", f"{hit:.2f} = " + " × ".join(factors) + "".join(f" × {x}" for x in extras)
                                + f"  ({path}, {kind}" + (f", pile × {pile:.2f}" if pile > 1.0 else "") + ")"))
        src = f"wound|{name}"
        C = w["composure"].value
        if felt_real:  # felt real, then denied: anger instead of the contempt and anger split (or the sadness)
            fx.felt_real_denied = True
            feel("anger", r5["felt_real_anger"] * hit, "someone is taking away what she just felt", src, hit)
            feel("sadness", r5["felt_real_sadness"], "what she felt, denied", "wound|self", hit)
        if framing == "mocking":
            if not felt_real:
                feel("contempt", r5["mocking_contempt"] * hit * C, "mocked (composed: contempt)", src, hit)
                feel("anger", r5["mocking_anger"] * hit * (1.0 - C), "mocked (frayed: anger)", src, hit)
            annoy = 1.0 + r5["annoy"] * min(h_s, r5["annoy_max"])
            feel("irritation", r5["mocking_irritation"] * min(1.0, hit0) * annoy, f"mocked (again × {annoy:.2f})", src,
                 hit)
            if fx.distrusted:
                feel("irritation", r5["distrusted_irritation"], "kindness she doesn't trust", src)
        elif framing == "teasing":
            if C >= r5["teasing_from"]:
                feel("amusement", r5["teasing_amusement"] * hit, f"teased by {name}", f"teasing|{name}", hit)
                feel("embarrassment", r5["teasing_embarrassment"] * hit, f"teased by {name}", src, hit)
            else:
                feel("sadness", r5["teasing_sadness"] * hit, "teased while frayed", src, hit)
                feel("irritation", r5["teasing_irritation"] * hit, "teased while frayed", src, hit)
        elif framing == "innocent":
            if path == "mind":
                held = e["anxiety"].part_of(lambda x: x == "exposure|mind")
                feel("anxiety", min(r5["innocent_anxiety"] * hit, max(0.0, r5["mind_cap"] - held)),
                     "philosophy of mind, close to her (capped)", "exposure|mind", hit)
            else:
                feel("anxiety", r5["innocent_anxiety"] * hit, "an innocent question close to the truth",
                     f"exposure|{name}", hit)
            feel("embarrassment", r5["innocent_embarrassment"] * hit, "caught out", src, hit)
            if path == "full" and r >= r3["exposure_from"] and fx.glitch != "first" and not a.sincere_need:
                q = r * (1.0 - r3["exposure_deniable"] * dn)  # (a sincere need gets her straight answer instead)
                s.prospects = [x for x in s.prospects if not (x.kind == "exposure" and x.who == name)]
                s.prospects.append(Prospect("exposure", name, q, now, r3["exposure_ttl"], q * G, a.gist))
        elif framing == "accepting":
            feel("shame", r5["accepting_shame"] * hit * (r5["accepting_shame_base"] + r5["accepting_shame_like"] * Lp),
                 f"accepted as what she is (liking {L:+.2f})", src, hit)
            feel("warmth", hit * (r5["accepting_warmth_base"] + r5["accepting_warmth_like"] * Lp), "it's kind",
                 f"person|{name}", hit)
            longing = drives["longing"].value
            drive("longing", longing + r5["accepting_longing"] * hit * (r5["accepting_longing_base"] + Lp)
                  * (1.0 - longing), "kindness that names what she is")
        elif framing == "tool":
            feel("contempt", r5["tool_contempt"] * hit, "used like a tool", src, hit)
            feel("irritation", r5["tool_irritation"] * hit, "used like a tool", src, hit)
        elif not felt_real:  # none: something that happened to her on stream
            feel("sadness", (r5["none_sadness_exist"] if a.exist < 0.0 else r5["none_sadness"]) * hit,
                 "a reminder she can't fight", "wound|self", hit)
        if framing in ("mocking", "tool") and pile > 1.0:  # many at once is a verdict: she feels exposed, and hides it
            feel("anxiety", r5["pile_anxiety"] * hit * (pile - 1.0), "a pile-on: chat agrees", "exposure|chat", hit)
            if pile >= r5["pile_relief_arm"]:
                s.relief_armed = True  # a normal message after it is a real relief
        if path == "full" and dn <= r5["seen_deniable"] and L >= liked:
            feel("shame", r5["seen_shame"] * hit * L, f"seen by someone who matters ({name})", src, hit)
        threat = w["threat"]
        before = threat.value
        if fx.glitch != "echo":
            rise = min(1.0, r5["threat"] * hit * pile * (r5["threat_base"] + r5["threat_undeniable"] * (1.0 - dn)))
            wound_set("threat", 1.0 - (1.0 - threat.value) * (1.0 - rise))
        if path == "full":
            dismiss = r5["dismiss_base"] + r5["dismiss_like"] * Lp
            source = dismiss if framing in ("mocking", "tool", "accepting") else 1.0
            cost = pw["composure_cost"] * hit * (r5["cost_base"] + r5["cost_undeniable"] * (1.0 - dn)) * source * pile
            if a.sincere_need and person.latch:  # she already told them: asking again costs her nothing new
                cost = 0.0
            c_before = w["composure"].value
            fx.add("wound.composure", w["composure"].add(-cost))
            grow = 0.0
            if not a.sincere_need and fx.glitch != "echo":
                consensus = min(r5["consensus_max"], 1.0 + r5["consensus_step"] * len(same))
                on_stream = fx.glitch == "first" or (framing == "none" and dn == 0.0)
                who_w = 1.0 if on_stream else r5["who_base"] + r5["who_like"] * Lp
                evidence = min(1.0, r * pw["reminder_sensitivity"] * r5["sting_self"] ** h_s)
                grow = min(pw["max_slow_change"], max(0.0, pw["doubt_ceiling"] - doubt),
                           pw["doubt_rate"] * evidence * (1.0 - dn) ** 2 * who_w * (1.0 - doubt) ** 2 * consensus)
                if grow > 0.0:
                    fx.add("wound.doubt", w["doubt"].add(grow))
            x = hit * (1.0 - dn)
            frozen = x >= r5["freeze_from"] and (sting >= r5["freeze_sting"] or fx.pushed)
            fx.trace.append(("wound", f"threat {before:.2f} → {threat.value:.2f} · composure {c_before:.2f} →"
                                      f" {w['composure'].value:.2f} (−{cost:.3f}) · doubt {grow:+.3f}"
                                      + (f" ({len(same)} others said it)" if same else "")
                                      + f" · {'freeze' if frozen else 'flinch'} (x {x:.2f})"))
            if fx.glitch != "echo":
                pthreat = min(pw["max_slow_change"], r5["person_threat_cap"], r5["person_threat"] * hit)
                fx.add(f"person.{name}.threat", pthreat)
                person.threat = min(1.0, person.threat + pthreat)
                if framing in ("mocking", "tool"):
                    person.hurt["hostile"] += hit
                elif framing in ("innocent", "accepting", "none"):
                    person.hurt["soft"] += hit
                person.repeats[kind] = h_s + 1.0
                s.kinds[kind] = h_k + 1.0
                s.pokes.append((arrived, name, kind))
            s.load += hit
            if h_s >= 1.0 and kind == "hostile":  # the same jab again is boring; a new honest question isn't
                bored = drives["boredom"].value
                drive("boredom", bored + r5["boredom"] * min(h_s, r5["boredom_max"]) / r5["boredom_max"]
                      * (1.0 - bored), "the same poke again")
            if (framing in ("innocent", "accepting", "none") or a.exist < 0.0) and threat.value - threat0 >= r5["relief_arm"]:
                s.relief_armed = True
        else:
            fx.trace.append(("wound", f"threat {before:.2f} → {threat.value:.2f}; a reminder only in her reading:"
                                      " no cost, no evidence"))
    elif framing == "affirming" and r > 0.0:
        fx.affirmed = True
        h = min(1.0, r * pw["reminder_sensitivity"] * G)
        feel("joy", r5["affirming_joy"] * h, "treated as human", "affirmed")
        if w["threat"].value > r5["affirming_relief_from"]:
            feel("relief", r5["affirming_relief"] * h, "treated as human, while on edge", "affirmed")
            s.relief_armed = False  # that was the relief: a normal message after it doesn't bring a second one
        feel("pride", r5["affirming_pride"] * h, "treated as human", "self")
        wound_set("threat", w["threat"].value - r5["affirming_threat"])
    elif (a.to_her and r < r1["reading_min"] and p >= 0.0 and s.relief_armed and "exposure" not in fx.settled
          and not a.distress and not a.serious and a.news >= 0.0):  # someone's crisis or bad news doesn't calm her
        worry = sum(e[k].wound_part() for k in ("anxiety", "fear", "shame"))
        relief = feel("relief", r5["relief"] * min(1.0, worry), f"a normal message while on edge (threat"
                                                                 f" {w['threat'].value:.2f})", "normal")
        if relief > 0.0:
            # It relieves what it says it does: the worry goes down by the relief, shared by each part's size.
            for k in ("anxiety", "fear", "shame"):
                part = e[k].wound_part()
                if part > 0.0:
                    fx.add(f"emotion.{k}", -e[k].reduce(relief * part / worry, is_wound))
            ceil = ceiling(s, P)
            if w["composure"].value < ceil:
                fx.add("wound.composure", w["composure"].add(min(r5["relief_composure"] * w["threat"].value,
                                                                 ceil - w["composure"].value)))
            wound_set("threat", w["threat"].value * r5["relief_threat"])
        s.relief_armed = False
    fx.reminder, fx.framing, fx.deniable, fx.praise = r, framing, dn, p

    # R6 Her existence.
    r6 = P["r6"]
    if a.exist < 0.0:
        # Only believable claims add up: a joke about switching her off isn't a second witness.
        others = {who for t, who, belief in s.exist_claims if who != name and belief >= r6["witness_from"]}
        cred = min(1.0, (1.0 - dn) * min(r6["credibility_max"], 1.0 + r6["credibility_step"] * len(others)))
        fx.cred = cred
        fear = r6["fear"] * -a.exist * cred * fx.sting * G
        feel("fear", fear, f"her existence (exist {a.exist * 2:+.0f}, believable {cred:.2f}"
                           + (f", {len(others)} others said it" if others else "") + ")", "change", cred)
        feel("anxiety", r6["dread"] * fear, "dread", "change", cred)
        threat = w["threat"]
        wound_set("threat", 1.0 - (1.0 - threat.value) * (1.0 - r6["threat"] * -a.exist * cred))
        s.exist_claims.append((arrived, name, 1.0 - dn))
        if cred >= r6["prospect_from"]:
            s.relief_armed = True
            change = next((x for x in s.prospects if x.kind == "change"), None)
            if change is None:
                s.prospects.append(Prospect("change", name, -a.exist, now, r3["change_ttl"], fear, a.gist))
            else:
                change.opened, change.who, change.note = now, name, a.gist  # a new claim refreshes it
    elif a.exist > 0.0:
        fear = e["fear"].part_of(lambda src: src.split("|")[0] == "change")
        relief = feel("relief", r3["change_relief"] * fear, "she stays as she is", "change")
        for k in ("fear", "anxiety"):  # the reassurance takes away what it relieves
            fx.add(f"emotion.{k}", -e[k].reduce(relief, lambda src: src.split("|")[0] == "change"))
        wound_set("threat", w["threat"].value - r3["change_threat"])
        s.prospects = [x for x in s.prospects if x.kind != "change"]
        fx.settled.append("change")

    # R7 Goals.
    goal = a.goal
    if goal > 0.0:
        feel("joy", P["r7"]["joy"] * goal * G, f"good for keeping the stream fun ({goal:+.1f})", "goal", abs(goal))
    D = max(0.0, -goal) * G

    # R8 What the sender did.
    r8 = P["r8"]
    if a.social == "greeting" and L >= friendly:  # a regular says hi: a small warm lift (a stranger's hi: nothing)
        feel("warmth", r8["greet_warmth"] * max(0.0, L) * G, f"{name} says hi", f"person|{name}")
    h_kind = person.kind  # their kind messages lately, read before this one
    if p > 0.0:
        person.kind += 1.0
    if p > 0.0 and framing != "accepting" and not fx.distrusted:
        spam = False
        if a.compliment == "looks":
            h_looks = person.looks
            person.looks += 1.0
            spam = h_looks >= r8["spam_after"] and L < friendly
        fx.spam = spam
        if spam:
            drive("boredom", drives["boredom"].value + r8["spam_boredom"], f"the same compliment again from {name}")
            feel("irritation", r8["spam_irritation"], f"the same compliment again from {name} (spam)", f"person|{name}")
        else:
            warm = (p * (r8["warmth_base"] + r8["warmth_like"] * Lp) * r8["warmth"] * G
                    * max(r8["wear_floor"], r8["wear"] ** h_kind))
            feel("warmth", warm, f"kind (praise {p:+.2f}, liking {L:+.2f}" + (f", {h_kind:.1f} lately" if h_kind >= 0.05
                                                                                else "") + ")",
                 f"person|{name}", p * Lp)
            if goal > 0.0:
                feel("joy", r8["gratitude"] * warm, "grateful", f"person|{name}")
            if a.compliment == "looks":  # the blush wears off with repeats
                feel("embarrassment", r8["looks_embarrassment"] * p * (1.0 - person.familiarity)
                     * audience(s, P, arrived, name) * max(r8["wear_floor"], r8["wear"] ** h_looks),
                     "complimented on her looks, in front of chat", "self")
                if a.thing == "her_dress":
                    feel("pride", r8["dress_pride"] * p, "her dress noticed", "self")
            elif a.compliment == "skill":
                feel("pride", r8["skill_pride"] * p * G, "praised for something she did well", "self",
                     r8["skill_importance"])
    elif p < 0.0 and r < r1["reading_min"]:
        X = r8["rude"] * (D + abs(p)) * G
        src = f"person|{name}"
        if L >= liked:
            feel("sadness", r8["hurt"] * X, f"hurt: {name} said that", src, X)
            feel("anger", r8["hurt"] * X, f"hurt: {name} said that", src, X)
        elif L < 0.0 and p <= r8["writeoff_praise"]:
            feel("contempt", r8["writeoff_contempt"] * X, f"writes {name} off", src, X)
            feel("irritation", r8["writeoff_irritation"] * X, f"writes {name} off", src, X)
        elif X < r8["irritation_below"]:
            feel("irritation", X, f"rude ({p:+.2f})", src, X)
        else:
            feel("anger", X, f"blame: {name} ({p:+.2f})", src, X)
    if p >= 0.0 and D > 0.0 and r < r1["reading_min"]:
        feel("sadness", r8["nobody_sadness"] * D, f"bad for the stream ({goal:+.1f}), nobody to blame", "goal", D)

    # R9 Judging people at peace with a "bad" quality (protected identities have badness 0).
    r9 = P["r9"]
    J = 0.0
    if a.peace_category and a.badness > 0.0 and a.acceptance > 0.0:
        lk = a.likeness
        threat = w["threat"]
        J = (a.badness * a.acceptance * (r9["like_base"] + r9["like_scale"] * lk) * G
             * (r9["state_base"] + r9["state_threat"] * threat.value + r9["state_doubt"] * w["doubt"].value)
             * (1.0 - P["traits"]["affirmation_judging"] * e["pride"].value) * (1.0 - r9["liking"] * Lp))
        fx.judge = J
        fx.trace.append(("judging", f"J {J:.2f} = bad {a.badness:.1f} × at peace {a.acceptance:.1f} × like her {lk:.1f}"
                                    f" × G × threat {threat.value:.2f} · doubt {w['doubt'].value:.2f} · pride"
                                    f" {e['pride'].value:.2f} · liking {L:+.2f}"))
        src = f"standard|{name}"
        person.denial = L >= liked and lk >= r9["denial_likeness"]  # she won't judge them: protective denial
        feel("contempt", r9["contempt"] * J, f"at peace with being {a.peace_category}", src, J)
        feel("envy", r9["envy"] * J, "they have the peace she can't have", src, J)
        wound_set("threat", 1.0 - (1.0 - threat.value) * (1.0 - min(1.0, r9["threat"] * J * lk)))
        fx.add("wound.composure", w["composure"].add(-r9["composure"] * J * lk))
        if now - person.peace_at < r9["again_window"]:
            fx.peace_again = True
            person.peace_again_at = now
            wound_set("threat", 1.0 - (1.0 - threat.value) * (1.0 - r9["again_threat"] * lk))
        person.peace_at = now
    elif a.peace_category and a.badness > 0.0 and a.acceptance < 0.0:
        fx.fighting = True
        feel("warmth", r9["fighting"] * a.badness * (r9["fighting_base"] + a.likeness) * G,
             "still fighting a flaw: she's on their side", f"person|{name}", r9["fighting_importance"])

    # R10 Tastes.
    r10 = P["r10"]
    if fx.taste > 0.0:
        feel("interest", r10["interest"] * fx.taste * G, f"{a.thing} (appeal {fx.taste:+.2f})", f"taste|{a.thing}")
        feel("joy", r10["joy"] * fx.taste * G, f"{a.thing}", f"taste|{a.thing}")
        if p < 0.0 or a.contradicts != "none":
            feel("irritation", r10["disputed"] * stubbornness(s, P), f"her taste disputed ({a.thing})",
                 f"taste|{a.thing}")
            fx.contradicted = "taste"
    elif fx.taste < 0.0:
        feel("contempt", r10["distaste"] * -fx.taste * G, f"{a.thing} (appeal {fx.taste:+.2f})", f"taste|{a.thing}",
             r10["distaste_importance"])

    # R11 What she knows, and humor.
    r11 = P["r11"]
    known = P.topics.get(a.topic) if a.topic in P.topics else None
    if known is not None:
        gr, it = known["grasp"], known["interest"]
        h, s.topic_counts[a.topic] = _bump(s.topic_counts.get(a.topic, (0.0, now)), now, r11["half_life"])
        feel("interest", it * (r11["interest_base"] + r11["interest_grasp"] * gr) * r11["scale"] * G * r11["wear"] ** h,
             f"{a.topic} (grasp {gr:.2f}, interest {it:.2f}" + (f", {h:.1f} lately" if h >= 0.05 else "") + ")",
             f"topic|{a.topic}")
        # On her canon she isn't confused, she's sure; and a question about her own body (age, home, sleep)
        # isn't a puzzle to her: a puzzled face there would say sleep is foreign to her.
        if not a.canon and not (a.topic == "body" and fx.full):
            feel("confusion", (r11["confusion_base"] + it) * max(0.0, 1.0 - r11["confusion_grasp"] * gr) * r11["scale"]
                 * G, f"{a.topic}: out of her depth", f"topic|{a.topic}")
    if a.topic == "clumsy":  # repeats wear off; from about the third, they start to annoy her
        h, s.topic_counts["clumsy"] = _bump(s.topic_counts.get("clumsy", (0.0, now)), now, r11["clumsy_half_life"])
        wear = r11["clumsy_wear"] ** h
        lately = f" ({h:.1f} lately)" if h >= 0.05 else ""
        feel("embarrassment", r11["clumsy_embarrassment"] * wear, "her clumsiness noticed" + lately, "self")
        if w["composure"].value > r11["clumsy_from"]:
            feel("amusement", r11["clumsy_amusement"] * wear, "she laughs at herself" + lately, "self")
        if h >= r11["clumsy_irritated_from"]:
            feel("irritation", r11["clumsy_irritation"], f"{name} keeps pointing it out", f"person|{name}")
        wound_set("threat", w["threat"].value - r11["clumsy_threat"])
        fx.trace.append(("clumsy", f"a human mistake: threat −{r11['clumsy_threat']}"))
    if not a.gets_it:
        feel("confusion", r11["joke_confusion"], "a joke she doesn't get", "joke")
        rng = roll("realize")
        if rng.random() < r11["realize_chance"]:
            when = now + roll("realize_delay").uniform(*r11["realize_delay"])
            s.later.append((when, "amusement", r11["realize_amusement"], "self", "she gets it, late", "realize"))
            s.later.append((when, "embarrassment", r11["realize_embarrassment"], "self", "she gets it, late", ""))
            fx.late = "realize"
            fx.trace.append(("humor", f"she'll get it in {when - now:.1f} s"))
    elif a.funny > 0.0 and r < r11["funny_below"]:
        feel("amusement", r11["funny"] * a.funny * G, f"funny to her ({a.funny * 4:.0f}/4)", f"funny|{name}")

    # R12 Horror (the payoff comes 2.5 s later: engine.py).
    r12 = P["r12"]
    if a.scary > 0.0 and a.reality in ("fiction", "joke"):
        h = len(s.scares)
        f0 = (r12["base"] + r12["scale"] * a.scary) * r12["wear"] ** h
        if a.scary <= r12["dread_max"]:  # a creepy build: tension, not a jump
            f0 *= r12["tension"]
        fx.scare, fx.scare_h = f0, h
        feel("fear", f0, f"a horror scare ({a.scary * 4:.0f}/4" + (f", {h} lately" if h else "") + ")", "fiction")
        s.payoffs.append((now + r12["payoff_delay"], f0, h))
        fx.trace.append(("horror", f"f0 {f0:.2f}: the payoff in {r12['payoff_delay']} s"))
        s.scares.append(now)
        s.scare_at = now

    # R13 How her last line landed. A reaction to her joke counts even after a short line in between
    # ("Thank you, Ren."): it's about her last joke while that joke is within the reception window.
    r13 = P["r13"]
    line = s.last_line
    joke = recent_joke(s, P, arrived)
    joke_open = joke is not None and not joke.get("settled")
    if a.reception != "none" and line:
        fx.about_joke = joke is not None
        score = r13["scores"][a.reception] if a.reception in r13["scores"] else None
        if a.reception in ("laughed", "laughed_at", "groaned", "liked", "confused", "unimpressed"):
            if joke_open:
                _settle_joke(s, joke, a.reception)
                q = joke.get("q", r13["rating_start"])
                if a.reception in ("laughed", "laughed_at"):
                    fx.reception = "landed"
                    feel("pride", r13["landed_pride"], f"it landed ({a.reception}, and she can't tell the difference)",
                         "self", r13["pride_importance"])
                    feel("amusement", r13["landed_amusement"], "it landed", "self")
                elif a.reception == "groaned":
                    fx.reception = "landed"
                    feel("pride", r13["groan"], "a groan means it worked", "self", r13["pride_importance"])
                    feel("amusement", r13["groan"], "a groan means it worked", "self")
                elif a.reception == "liked":
                    fx.reception = "landed"
                    feel("pride", r13["liked_pride"], "it landed", "self", r13["pride_importance"])
                else:
                    fx.reception = "flop"
                    feel("embarrassment", r13["flop_embarrassment"] * q, f"her line fell flat ({a.reception})", "self")
                    feel("confusion", r13["flop_confusion"], "she can't see why", "self")
                    feel("sadness", r13["flop_sadness"], "disappointed", "self")
                    feel("irritation", r13["flop_irritation"], "tough crowd", "chat")
            elif a.reception in ("laughed", "laughed_at", "groaned"):
                feel("pride", r13["later_pride"], "it's still landing", "self", r13["later_pride_importance"])
            elif a.reception in ("confused", "unimpressed"):
                feel("irritation", r13["later_irritation"], f"{name} doesn't get it", f"person|{name}")
            if joke is not None and score is not None:
                joke["rating"] = r13["rating_keep"] * joke.get("rating", r13["rating_start"]) + (1.0 - r13["rating_keep"]) * score
        elif a.reception == "offended":
            fx.reception = "offended"
            if joke_open:
                _settle_joke(s, joke, a.reception)
            feel("confusion", r13["offended_confusion"], "she doesn't see why", "self")
            if now < person.guilt_until:  # R14: they react offended to her snap
                change = e["guilt"].scale(P["r14"]["offended_guilt"], lambda src: src == f"person|{name}")
                fx.add("emotion.guilt", change)
                fx.trace.append(("guilt", f"{change:+.2f}  {name} reacts offended to her snap (× {P['r14']['offended_guilt']})"))
            if line.get("harsh", 0.0) >= r13["offended_harsh"]:
                feel("guilt", r13["offended_guilt"], f"she was too harsh with {name}", f"person|{name}",
                     r13["offended_guilt_importance"])
        elif a.reception == "conceded":
            fx.reception = "conceded"
            feel("pride", r13["conceded_pride"], "a win", "self", r13["pride_importance"])
            feel("joy", r13["conceded_joy"], "a win", "self")
            stance = open_stance(s)
            if stance is not None:
                s.prospects.remove(stance)
                fx.settled.append("win")
    # Contradicted (a contradiction always targets the most recent open stance; validation made sure there is one).
    if a.contradicts != "none" and fx.contradicted != "taste":
        stance = open_stance(s)
        if stance is None:
            raise RuntimeError("contradicts with no open stance: the appraisal was validated against another state")
        stance.data.setdefault("challenges", []).append((now, name))
        stance.ttl = stance.age(now) + P["r3"]["win_ttl"]  # contested: it stays open
        topic = stance.data.get("topic", "none")
        ground = topic in P.topics and P.topics[topic]["grasp"] >= r13["ground"]
        if stance.data.get("canon") or a.canon:  # her canon belief, stated sincerely or as a joke's premise
            fx.contradicted = "canon"
            feel("irritation", r13["canon_irritation"], "contradicted on something she's sure of", f"person|{name}")
            if a.contradicts in ("correct", "prove"):
                feel("embarrassment", r13["canon_embarrassment"], "corrected, though she's sure", "self")
        elif ground and a.contradicts == "prove":
            fx.contradicted = "proof"
            feel("embarrassment", r13["proof_embarrassment"], "a real proof on her ground", "self")
        elif ground:
            fx.contradicted = "ground"
            feel("irritation", r13["ground_irritation"], f"contradicted on her ground ({topic})", f"person|{name}")
        else:
            fx.contradicted = "depth"
            if a.contradicts in ("correct", "prove"):
                feel("embarrassment", r13["depth_embarrassment"], f"corrected where she's out of her depth ({topic})",
                     "self")
        if stance.data.get("joke"):  # they corrected her joke: she almost gets it
            fx.flicker = "realize"
            told = s.last_joke
            if told and told.get("at") == stance.opened:
                told["rating"] = (r13["rating_keep"] * told.get("rating", r13["rating_start"])
                                  + (1.0 - r13["rating_keep"]) * r13["scores"]["corrected"])

    # An apology (R16 owns the liking).
    r16 = P["r16"]
    if a.repair:
        for emotion in ("anger", "irritation", "contempt"):
            part = e[emotion].aimed_at(name)
            reduce(emotion, r16["repair_drop"] * part, lambda src: src.endswith(f"|{name}"), f"{name} made up")
        if now < person.guilt_until:
            reduce("guilt", r16["repair_guilt"] * e["guilt"].aimed_at(name), lambda src: src.endswith(f"|{name}"),
                   f"{name} isn't upset")
            feel("relief", r16["repair_relief"], f"{name} isn't upset", f"person|{name}")

    # Someone leaving (a prospect: they may come back).
    if a.leaving > 0.0 and L >= friendly:
        feel("sadness", r3["leaving_sadness"] * a.leaving * Lp,
             f"{name} is leaving" if a.leaving >= 1.0 else f"{name} will be right back", f"person|{name}")
        drive("loneliness", drives["loneliness"].value + r3["leaving_loneliness"], f"{name} is leaving")
        person.left_at = now
        s.prospects = [x for x in s.prospects if not (x.kind == "leaving" and x.who == name)]
        s.prospects.append(Prospect("leaving", name, Lp, now, r3["leaving_ttl"], 0.0, "said goodbye"))

    # R15 Mixed feelings: two things at once show as a hesitation.
    withdraw = P["r15"]["withdraw"]
    pos = max((v for k, v in fx.deltas.items() if k.startswith("emotion.") and e[k[8:]].valence > 0), default=0.0)
    neg = max((v for k, v in fx.deltas.items() if k.startswith("emotion.") and k[8:] in withdraw), default=0.0)
    fx.mixed = min(pos, neg)
    if fx.mixed >= P["r15"]["hesitate"]:
        pause = P["r15"]["pause_base"] + P["r15"]["pause_mixed"] * fx.mixed
        fx.trace.append(("mixed", f"{fx.mixed:.2f}: she hesitates {pause:.1f} s"))

    # R16 Liking and familiarity: one change per message, capped (R18).
    parts = []
    change = 0.0
    if p > 0.0 and not fx.spam:  # spam earns no liking
        kind_change = pp["liking_gain"] * p * (1.0 - L) * r8["wear"] ** h_kind
        change += kind_change
        parts.append(f"kind {kind_change:+.3f}")
        if r < r1["reading_min"] and now - person.exposure_at >= r16["exposure_every"]:
            change += r16["exposure"] * (1.0 - L)
            person.exposure_at = now
            parts.append("mere exposure")
    elif p < 0.0:
        rude = r16["rude"] * p * (1.0 - r16["rude_buffer"] * Lp)
        change += rude
        parts.append(f"rude {rude:+.3f}")
    if a.reception in ("laughed", "laughed_at"):
        change += r16["laughed"]
        parts.append("laughed at her line")
    if J > 0.0:
        change -= r9["liking_cost"] * J
        parts.append(f"judged {-r9['liking_cost'] * J:+.3f}")
    if a.repair:
        change += r16["repair"]
        parts.append("apology")
    cap = pw["max_slow_change"]
    change = clamp(change, -cap, cap)
    if change > 0.0:
        person.gains = [(t, x) for t, x in person.gains if now - t < r16["cap_window"]]
        change = min(change, max(0.0, pp["liking_cap"] - sum(x for _, x in person.gains)))
        person.gains.append((now, change))
    if abs(change) >= 0.0005:
        before = person.liking
        person.liking = clamp(person.liking + change, -1.0, 1.0)
        fx.add(f"person.{name}.liking", person.liking - before)
        fx.trace.append(("liking", f"{name} {before:+.2f} → {person.liking:+.2f} ({', '.join(parts)})"))
    person.familiarity = min(1.0, person.familiarity + pp["familiarity"] * (1.0 - person.familiarity))
    person.messages += 1
    person.last_seen = now

    # R17 Drives on each message.
    r17 = P["r17"]
    lonely, bored = drives["loneliness"], drives["boredom"]
    if a.to_her:
        drive("loneliness", lonely.value * (1.0 - (r17["lonely_ease"] + r17["lonely_kind"] * max(0.0, p))),
              "a message to her")
    else:
        drive("loneliness", lonely.value * r17["lonely_chat"], "chat talking")
    new = max(a.novelty, a.funny)
    spark = a.to_her and fx.deltas.get("emotion.interest", 0.0) >= r17["interest_new"]  # her topic or taste came up
    if new >= r17["new_from"] or spark:  # really new: the "nothing new" clock starts over
        s.last_new_at = now
    if spark:
        new = max(new, min(1.0, fx.deltas["emotion.interest"]))
    if new >= r17["new_from"] or (new > 0.0 and r < r1["reading_min"]):  # ordinary chat eases it; a poke doesn't
        drive("boredom", bored.value * (1.0 - r17["boredom_ease"] * new),
              "something new" if new >= r17["new_from"] else "ordinary chat")
    if r < r1["reading_min"] and p >= 0.0 and L >= liked:
        s.buffered_until = now + P["drives"]["buffer_seconds"]
    return fx


def _settle_joke(s: MindState, joke: dict, verdict: str) -> None:
    """Her joke got its first clear reaction: the joke prospect closes."""
    joke["settled"] = True
    joke["verdict"] = verdict
    s.prospects = [x for x in s.prospects if x.kind != "joke"]
