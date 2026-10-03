"""What her body shows of what she feels (docs/mind.md, "What the body shows").
Python decides everything (which display, which leak, how strong); Godot only
mixes and moves. Every number lives in persona.toml ([display], [gaze],
[tonic], [body_dials]).

  display rules   per feeling, per cause, per person and per rung (Ekman &
                  Friesen), the spec's table, first match wins: MASK the
                  wound, NEUTRALIZE envy and embarrassment, DEINTENSIFY
                  warmth toward strangers, INTENSIFY a horror startle and
                  contempt for AI things, NONE for someone else's loss. k is
                  how much she lets show (0 hides it, 1 shows it all, above 1
                  plays it up); mask = 1 - k.
  how much shows  per region: shown = felt x (1 - (1 - k) x region x rung).
                  People control the lower face well and the inner brow
                  poorly, and lose control as composure goes.
  leaks           gap = felt - shown: the chance of a short, strong pulse in
                  the feeling's region, in the windows brain.py offers.
  short displays  a feeling that rises by 0.12 or more within 2 s plays one
                  display; moods have no face of their own.
  resting face    from mood and the slow parts, low-passed in Godot.
  body            arousal animates her when she's glad and freezes her when
                  she's afraid or ashamed; hiding costs stillness and blinks."""

from .persona import Persona
from .rules import MindState, active_prohibits
from .state import WOUND_CAUSES, Person, clamp

_DEFAULT = Persona.load()
# Emotion -> the felt face that shows it (mimics.FELT).
FACE = {name: name for name in ("amusement", "joy", "pride", "relief", "warmth", "interest", "surprise", "irritation",
                                "anger", "contempt", "sadness", "anxiety", "fear", "embarrassment", "shame", "guilt",
                                "envy", "confusion")}
# How well people control the region each feeling shows in (Ekman 2003), and
# how much control each rung leaves (from persona.toml).
REGION: dict[str, float] = dict(_DEFAULT["display"]["region"])
RUNG: dict[str, float] = dict(_DEFAULT["display"]["rung"])
# How long one short display of each feeling lasts (seconds).
LENGTH: dict[str, tuple[float, float]] = {k: tuple(v) for k, v in _DEFAULT["display"]["length"].items()}
_HIDDEN = ("shame", "fear", "anxiety", "sadness", "envy")


def display_rule(persona: Persona, emotion: str, cause: str, person: Person | None, rung: str, now: float,
                 honest: bool, crack_leak: bool, state: MindState | None = None) -> tuple[str, float]:
    """The display rule for one source of one feeling: (rule, k) before her control.
    honest: her honest line is playing; crack_leak: the crack's leak phase."""
    d = persona["display"]
    wound = cause in WOUND_CAUSES
    L = person.liking if person is not None else 0.0
    liked = L >= persona["person"]["liked"]
    troll = person is not None and (L < 0.0 or person.hurt["hostile"] > 0.0)
    if wound and honest:
        return "mask (honest)", d["honest"]  # 1
    if wound and crack_leak:
        return "lets go (crack)", d["crack_leak"]  # 2
    if emotion == "envy" and cause == "wound":
        return "neutralize", d["human_envy"]  # 3 shows intrigued instead; leaks as the lingering look
    if wound and emotion in _HIDDEN:
        return "mask", d["wound"]  # 4
    if emotion == "fear" and cause == "fiction":
        return "intensify", d["horror_fear"]  # 5
    if emotion == "contempt" and cause == "taste":
        return "intensify", d["ai_contempt"]  # 6
    if emotion == "contempt" and cause == "standard" and not (person is not None and person.denial):  # 7
        # (someone she likes gets protective denial, not judging: row 8 keeps it off her face)
        again = person is not None and now - person.peace_again_at < persona["r9"]["again_window"]
        return ("deintensify", d["judged_again"]) if again else ("put-on skeptical", d["judged"])
    if emotion in ("contempt", "anger") and liked:
        return "deintensify", d["liked_hostile"]  # 8
    if emotion == "irritation" and troll:  # 9
        k = d["troll_irritation"][rung]
        return ("neutralize" if k == 0.0 else "deintensify" if k < 1.0 else "none"), k
    if emotion == "contempt" and troll:
        return "none", d["troll_contempt"]  # 10
    if emotion == "anger":
        return "deintensify", d["anger"]  # 11
    if emotion == "sadness" and cause == "news":
        return "none (concern)", d["news_sadness"]  # 12
    if emotion == "anxiety" and cause == "news":
        return "none (concern)", d["news_anxiety"]  # 12b worry for someone in crisis
    if emotion == "warmth" and cause == "news":
        return "none", d["news_warmth"]  # 13
    if emotion == "warmth":
        return "deintensify", d["warmth_liked"] if liked else d["warmth"]  # 14
    if emotion == "joy" and cause == "news":  # 15; muted while she's sorry for someone (condolences)
        sorry = any(x["kind"] == "news" for x in active_prohibits(state, now)) if state is not None else False
        return "deintensify", d["joy_others_sorry"] if sorry else d["joy_others"]
    if emotion == "joy" and cause in ("taste", "goal", "fiction"):
        return "none", d["unguarded"]  # 16
    if emotion == "amusement" and cause in ("self", "fiction"):
        return "none", d["own_amusement"]  # 17
    if emotion == "amusement":
        return ("none", d["unguarded"]) if liked else ("deintensify", d["amusement"])  # 18
    if emotion == "pride":
        return ("none", d["won_pride"]) if cause == "self" else ("deintensify", d["pride"])  # 19, 20
    if emotion == "embarrassment":
        return "neutralize", d["embarrassment"]  # 21
    if emotion == "guilt":
        return "deintensify", d["guilt"]  # 22
    if emotion in ("interest", "confusion", "surprise"):
        return "none", d["open"]  # 23
    if emotion == "relief":
        return "deintensify", d["relief"]  # 24
    return "deintensify", d["other"]


def shown(s: MindState, persona: Persona, rung: str, now: float, covering: bool = False, honest: bool = False,
          crack_leak: bool = False) -> dict[str, dict]:
    """For each feeling: how much she feels, how much her face shows, and the
    biggest part's rule. Covering after a crack: k + 0.1 on every row."""
    d = persona["display"]
    region, cap_rung = d["region"], d["rung"][rung]
    out = {}
    for name, emotion in s.emotions.items():
        felt = emotion.value
        if felt < 0.005:
            out[name] = {"felt": 0.0, "shown": 0.0, "rule": "", "k": 1.0}
            continue
        total, rule_of_top, k_top = 0.0, "", 1.0
        for source, part in emotion.parts():
            cause, _, target = source.partition("|")
            person = s.people.get(target)
            rule, k = display_rule(persona, name, cause, person, rung, now, honest, crack_leak, s)
            if emotion.valence > 0 and person is not None and k <= 1.0:  # people she likes see more of her good feelings
                k = min(d["liked_cap"], k * (1.0 + d["liked_boost"] * max(0.0, person.liking)))
            if covering:
                k += d["covering"]
            k_eff = 1.0 - (1.0 - k) * region[name] * cap_rung if k <= 1.0 else k
            total += part * k_eff
            if not rule_of_top:
                rule_of_top, k_top = rule, k
        out[name] = {"felt": round(felt, 3), "shown": round(min(d["shown_max"], min(felt, 1.0) * total / max(
            sum(p for _, p in emotion.parts()), 1e-9)), 3), "rule": rule_of_top, "k": round(k_top, 3)}
    return out


def leak_chance(persona: Persona, name: str, gap: float) -> float:
    """The chance of a leak in one window: clamp(1.2 x (gap - 0.1) x (1.5 - region), 0, 0.85)."""
    lk = persona["display"]["leak"]
    return clamp(lk["scale"] * (gap - lk["gap"]) * (lk["region"] - persona["display"]["region"][name]), 0.0, lk["max"])


def biggest_gap(view: dict[str, dict]) -> tuple[str, float]:
    best = ("", 0.0)
    for name, v in view.items():
        gap = v["felt"] - min(v["shown"], v["felt"])
        if gap > best[1]:
            best = (name, gap)
    return best


def suppression(s: MindState, persona: Persona) -> float:
    """S: how much wound-caused feeling she's hiding right now (fixed hiding efforts)."""
    effort = persona["suppression"]["hiding_effort"]
    return min(1.0, sum(s.emotions[name].wound_part() * m for name, m in effort.items()))


def phasic(s: MindState, before: dict[str, float], persona: Persona, fired: dict[tuple[str, str], float],
           now: float) -> list[tuple[str, float, float]]:
    """Short displays due now: (emotion, peak before display rules, rise). A
    feeling that rose by Δmin or more since `before` (2 s ago) plays one; mood
    lowers Δmin for matching feelings. The same emotion from the same source
    plays at most once per 60 s unless it rose 0.3 or more."""
    d = persona["display"]
    out = []
    dp = s.mood["pleasure"].value - s.mood["pleasure"].rest
    for name, emotion in s.emotions.items():
        rise = emotion.value - before.get(name, 0.0)
        base = d["phasic_relief"] if name == "relief" else d["phasic_min"]
        if rise < base - d["phasic_mood"] * max(0.0, dp * emotion.valence):
            continue
        key = (name, emotion.top_source())
        if now - fired.get(key, -1e9) < d["phasic_again"] and rise < d["phasic_again_rise"]:
            continue
        pk = d["peak"]
        out.append((name, clamp(pk["base"] + pk["rise"] * rise + pk["value"] * emotion.value, 0.0, 1.0), rise))
    return out


def tonic(s: MindState, persona: Persona, view: dict[str, dict]) -> tuple[dict[str, float], float, float]:
    """The resting face (shapes) and head (pitch, roll) from mood and the slow
    parts. Display rules apply here too: her mask is on at rest."""
    t = persona["tonic"]
    e = s.emotions
    P, A, D = (s.mood[k].value for k in ("pleasure", "arousal", "dominance"))
    boredom, longing = s.drives["boredom"].value, s.drives["longing"].value

    def tail(name: str) -> float:  # the slow part she lets show
        v = view[name]
        return e[name].slow * (v["shown"] / v["felt"]) if v["felt"] > 0.0 else 0.0

    ec, es, bs, ba, ej, mf = (t[k] for k in ("eye_close", "eye_spread", "brow_sorrow", "brow_angry", "eye_joy",
                                             "mouth_fun"))
    shapes = {
        "Fcl_EYE_Close": clamp(ec["base"] + ec["arousal"] * A, 0.0, ec["max"]) + ec["boredom"] * boredom,
        "Fcl_EYE_Spread": clamp(es["scale"] * (A - es["from"]), 0.0, es["max"]) + es["anxiety"] * tail("anxiety"),
        "Fcl_BRW_Sorrow": clamp(bs["scale"] * max(tail("sadness"), tail("shame"), longing) - bs["minus"], 0.0, bs["max"])
                          + bs["low_mood"] * max(0.0, -P),
        "Fcl_BRW_Angry": clamp(ba["scale"] * max(tail("irritation"), tail("anger")) - ba["minus"], 0.0, ba["max"]),
        "Fcl_EYE_Joy": clamp(ej["scale"] * (P - ej["from"]) + ej["warmth"] * tail("warmth"), 0.0, ej["max"]),
        "Fcl_MTH_Fun": clamp(mf["scale"] * (P - mf["from"]) + mf["warmth"] * tail("warmth"), 0.0, mf["max"]),
    }
    shapes = {k: round(v, 3) for k, v in shapes.items() if v > t["min_shape"]}
    pitch = clamp(t["pitch"]["dominance"] * D + t["pitch"]["shame"] * tail("shame"), *t["pitch"]["range"])
    roll = t["roll"] * tail("warmth")
    return shapes, round(pitch, 1), round(roll, 1)


def body(s: MindState, persona: Persona, S: float) -> dict:
    """Body parameters (brain.apply_body): energy, blinks, breathing, stillness."""
    b = persona["body_dials"]
    e = s.emotions
    P, A = s.mood["pleasure"].value, s.mood["arousal"].value
    acute = sum(x.fast * max(0.0, x.pad[1]) for x in e.values())
    arousal_body = clamp(b["arousal"] * (A - s.mood["arousal"].rest) + b["acute"] * acute, -1.0, 1.0)
    animate = max(0.0, arousal_body) * (b["animate_pleasure"] + (1.0 - b["animate_pleasure"]) * max(0.0, P))
    freeze = max(e["fear"].value, b["freeze"]["shame"] * e["shame"].value, b["freeze"]["anxiety"] * e["anxiety"].value)
    hiding = S > persona["suppression"]["short"]
    bl, br, dp, wm = b["blinks"], b["breaths"], b["depth"], b["warmth"]
    blinks = bl["idle"] * (1.0 + bl["arousal"] * A) * (1.0 + bl["anxiety"] * e["anxiety"].value)
    blinks *= bl["hiding"] if hiding else 1.0
    blinks *= bl["stare"] if e["anger"].value > bl["stare_from"] else 1.0
    blinks *= bl["intrigued"] if e["interest"].value > bl["intrigued_from"] else 1.0
    breaths = (br["base"] + br["arousal"] * max(0.0, arousal_body) + br["anxiety"] * e["anxiety"].value
               + br["anger"] * e["anger"].value - br["sadness"] * e["sadness"].value + (br["hiding"] if hiding else 0.0))
    depth = ((1.0 - dp["anxiety"] * e["anxiety"].value) * (1.0 + dp["anger"] * e["anger"].value)
             * (1.0 + dp["sadness"] * e["sadness"].value) * (dp["hiding"] if hiding else 1.0))
    still = (1.0 - b["still"] * freeze) * (b["hiding_still"] if hiding else 1.0)
    warmth = clamp(wm["base"] + wm["mood"] * (P - s.mood["pleasure"].rest) + wm["warmth"] * e["warmth"].value,
                   *wm["range"])
    en = b["energy"]
    return {
        "energy": round(clamp(en["base"] + en["animate"] * animate, *en["range"]) * still ** 0.5, 3),
        "warmth": round(warmth, 3),
        "blinks_per_minute": round(clamp(blinks, *bl["range"]), 1),
        "breaths_per_minute": round(clamp(breaths, *br["range"]), 1),
        "breath_depth": round(clamp(depth, *dp["range"]), 2),
        "sway": round(clamp(still, *b["sway_range"]), 2),
        "freeze": round(freeze, 2),
        "arousal_body": round(arousal_body, 2),
        "hiding": hiding,
    }


def gaze(persona: Persona, view: dict[str, dict], liking: float) -> dict:
    """While she talks: the share of time on the camera, and how she looks away.
    The row is set by the strongest shown emotion at 0.3 or more; otherwise the
    baseline (the warmth row also for someone she likes)."""
    g = persona["gaze"]
    rows = [name for name in view if name in g and name != "from" and view[name]["shown"] >= g["from"]]
    if rows:
        row = max(rows, key=lambda name: view[name]["shown"])
    elif liking >= persona["person"]["liked"]:
        row = "warmth"
    else:
        row = "baseline"
    r = g[row]
    return {"share": r["share"], "away": r["away"], "pitch": tuple(r["pitch"]), "length": tuple(r["length"])}
