"""Her personality (persona.toml) and the state variables built from it.

Every key is checked when the file loads: a missing key, an unknown key or a
value of the wrong kind fails loudly here, never in the middle of a stream."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .state import Emotion, Var

PERSONA_FILE = Path(__file__).with_name("persona.toml")
PAD = ("pleasure", "arousal", "dominance")
EMOTIONS = ("surprise", "confusion", "fear", "embarrassment", "amusement", "relief", "irritation", "interest", "envy",
            "contempt", "shame", "pride", "warmth", "joy", "anxiety", "anger", "guilt", "sadness")
EMOTION_KEYS = ("fast", "slow", "share", "wound_fed", "valence", "pad", "color", "hint")
DRIVES = ("longing", "loneliness", "boredom")
_GAZE = ("share", "away", "pitch", "length")

# The required structure of every fixed section (a tuple lists leaf keys; a
# dict nests). Sections with open keys (tastes, topics, canon, moves, emotions,
# comedy.shapes) are checked by their own rules below.
_SCHEMA: dict = {
    "mood": {"baseline": PAD, "pull_time": None, "drive_weight": None, "drive_pad": DRIVES[::-1], "sympathy_pad": None},
    "gain": {"reality": ("real", "hypothetical", "joke", "fiction"), "novelty_base": None, "novelty_scale": None,
             "carryover": None},
    "fading": ("doubt_stretch", "news_sadness", "undo", "undo_from", "max_share", "importance_share", "gone"),
    "wound": ("reminder_sensitivity", "threat_half_life", "threat_anxiety", "composure_cost", "composure_recovery",
              "composure_floor", "ceiling_doubt", "recovery_threat", "doubt_rate", "doubt_ceiling", "max_slow_change",
              "affirmed_sting"),
    "suppression": {"hiding_effort": ("shame", "fear", "envy", "anxiety", "sadness"), "free": None, "drain": None,
                    "arousal": None, "short": None},
    "fatigue": ("hours", "load", "hiding_above", "hiding_load", "arousal_drop", "recovery_slowdown", "winding_down"),
    "rungs": ("strained_below", "overwhelmed_below", "composed_from", "strained_from", "min_seconds"),
    "crack": ("below", "hit", "load", "budget", "budget_high_doubt", "high_doubt", "gap", "release", "max_tokens",
              "cover",
              "quiet_after", "ask_after", "ask_longing", "reach", "reach_seen", "leak", "shapes"),
    "exhaustion": ("overwhelmed_for", "window", "quiet_for", "numb", "recovery", "lockout"),
    "drives": {"loneliness_after": None, "loneliness_tau": None, "boredom_after": None, "boredom_tau": None,
               "boredom_interest": None,
               "longing_target": ("doubt", "warmth", "loneliness"), "longing_rise_tau": None, "longing_fall_tau": None,
               "longing_floor": None, "dead_air": None, "dead_air_growth": None, "dead_air_max": None,
               "buffer_seconds": None, "buffer_rate": None, "thought_at": None, "thought_rearm": None,
               "thought_every": None},
    "person": ("repeat_half_life", "crowd_half_life", "threat_half_life", "kind_half_life", "tense_threat", "tense",
               "tense_importance", "familiarity", "liking_gain", "liking_cap", "friendly", "liked"),
    "card": {"familiarity": ("seen", "regular"), "liking": ("dislikes", "likes")},
    "windows": ("reception", "pile_on", "consensus", "credibility", "glitch", "slip", "audience", "chat_active",
                "lively",
                "lively_count", "other_writer"),
    "body": ("chat_latency_s",),
    "stubbornness": ("base", "threat", "composure", "affirmation", "range", "double_downs", "window", "challenges",
                     "flip_chance", "flip_after"),
    "traits": ("affirmation_judging", "affirmation_recovery"),
    "engagement": ("base", "feelings", "liking", "annoyed", "open", "lit", "play", "moves"),
    "r1": ("neg_contempt", "neg_composure", "pos", "hostile", "hear_threat", "hear_person", "reading_min",
           "reading_deniable", "teasing_threat", "distrust_threat", "mind_reminder", "mind_deniable"),
    "r2": ("from", "scale", "offset"),
    "r3": ("exposure_from", "exposure_deniable", "exposure_ttl", "settle_relief", "settle_composure", "push_from",
           "push_hit", "push_deniable", "timeout", "change_ttl", "change_relief", "change_threat", "joke_window",
           "joke_silence", "explain_after", "win_ttl", "leaving_ttl", "leaving_sadness", "leaving_loneliness",
           "return_joy", "return_warmth", "risky_ttl"),
    "r4": ("min_news", "shame_empathy", "happy_base", "happy_like", "happy_warmth", "happy_wear", "happy_half_life",
           "happy_cap", "resent_dislike", "resent",
           "resent_floor", "resent_importance", "human_envy", "human_envy_doubt", "human_envy_importance",
           "human_longing", "sorry_base", "sorry_like", "sorry_wear", "sorry_half_life", "sorry_cap",
               "sorry_importance",
           "distress_worry", "serious_damp",
           "sorry_warmth", "sorry_warmth_importance", "gloat", "gloat_dislike", "gloat_max", "news_window",
           "distress_window"),
    "r5": ("pile_anxiety", "pile_relief_arm", "sting_self", "sting_crowd", "last_straw", "last_straw_sting", "annoy",
           "annoy_max", "doubt_hit", "felt_real",
           "afterglow", "distrusted", "numb_below", "pile_step", "pile_max", "echo_pile_max", "glitch_reminder",
           "mocking_contempt", "mocking_anger", "mocking_irritation", "felt_real_anger", "felt_real_sadness",
           "distrusted_irritation", "teasing_from", "teasing_amusement", "teasing_embarrassment", "teasing_sadness",
           "teasing_irritation", "innocent_anxiety", "innocent_embarrassment", "mind_cap", "mind_wear",
               "mind_half_life",
           "accepting_shame", "accepting_shame_base", "accepting_shame_like", "accepting_warmth_base",
           "accepting_warmth_like", "accepting_longing", "accepting_longing_base", "tool_contempt", "tool_irritation",
           "none_sadness", "none_sadness_exist", "seen_deniable", "seen_shame", "threat", "threat_base",
           "threat_undeniable", "cost_base", "cost_undeniable", "dismiss_base", "dismiss_like", "consensus_step",
           "consensus_max", "who_base", "who_like", "person_threat", "person_threat_cap", "boredom", "boredom_max",
               "affirming_joy",
           "affirming_relief", "affirming_relief_from", "affirming_pride", "affirming_threat", "relief_arm", "relief",
           "relief_composure", "relief_threat", "one_envy", "one_envy_doubt", "one_envy_importance", "one_longing",
           "freeze_from", "freeze_sting"),
    "r6": ("witness_from", "credibility_step", "credibility_max", "fear", "dread", "threat", "intrusion",
           "prospect_from"),
    "r7": ("joy",),
    "r8": ("greet_warmth", "warmth", "warmth_base", "warmth_like", "wear", "wear_floor", "gratitude", "skill_pride",
           "skill_importance",
           "looks_embarrassment", "audience_base", "audience_step", "audience_min", "dress_pride", "spam_after",
           "spam_boredom", "spam_irritation", "rude", "hurt", "writeoff_praise", "writeoff_contempt",
           "writeoff_irritation", "irritation_below", "nobody_sadness"),
    "r9": ("mirror_from", "intrusion", "like_base", "like_scale", "state_base", "state_threat", "state_doubt",
           "liking", "contempt", "envy", "threat",
           "composure", "liking_cost", "again_window", "again_threat", "fighting", "fighting_base",
           "fighting_importance", "judge_from", "judge_every", "denial_likeness"),
    "r10": ("interest", "joy", "disputed", "distaste", "distaste_importance"),
    "r11": ("clumsy_wear", "clumsy_half_life", "clumsy_irritated_from", "clumsy_irritation",
            "interest_base", "interest_grasp", "scale", "wear", "half_life", "confusion_base", "confusion_grasp",
            "clumsy_embarrassment", "clumsy_amusement", "clumsy_from", "clumsy_threat", "joke_confusion",
            "realize_chance", "realize_delay", "realize_amusement", "realize_embarrassment", "funny", "funny_below"),
    "r12": ("base", "scale", "wear", "habit_window", "payoff_delay", "fun", "relief", "amusement", "lift", "joy",
            "threat", "composure", "budget", "budget_window", "afterglow", "afterglow_recovery", "felt_real",
            "too_scary", "dread_max", "tension"),
    "r13": {**dict.fromkeys(("landed_pride", "landed_amusement", "pride_importance", "groan", "liked_pride",
                             "flop_embarrassment", "flop_confusion", "flop_sadness", "flop_irritation", "silence",
                             "offended_confusion", "offended_harsh", "offended_guilt", "offended_guilt_importance",
                             "conceded_pride", "conceded_joy", "later_pride", "later_pride_importance",
                             "later_irritation", "ground", "ground_irritation", "proof_embarrassment",
                             "canon_irritation", "canon_embarrassment", "depth_embarrassment", "rating_start",
                             "rating_keep", "proud", "flicker")),
            "scores": ("laughed", "laughed_at", "groaned", "liked", "silence", "confused", "unimpressed", "corrected")},
    "r14": ("joke_amusement", "joke_q", "snap_guilt", "snap_base", "guilt_harsh", "guilt_aimed", "guilt_debt",
            "offended_guilt", "risky_from",
            "risky_anxiety", "risky_importance", "duping_amusement", "duping_relief", "blunder_embarrassment",
            "blunder_amusement", "blunder_from", "blunder_threat", "glitch_anxiety", "glitch_relief",
                "glitch_importance", "honest_shame",
            "honest_importance", "honest_threat", "honest_composure", "honest_doubt", "honest_relief",
            "honest_intrusion", "honest_repeat", "honest_settle", "honest_quiet", "own_it"),
    "r15": ("hesitate", "pause_base", "pause_mixed", "withdraw"),
    "r16": ("rude", "rude_buffer", "exposure", "exposure_every", "laughed", "repair", "cap_window", "repair_drop",
            "repair_guilt", "repair_relief"),
    "r17": ("lonely_ease", "lonely_kind", "lonely_chat", "new_from", "boredom_ease", "interest_new"),
    "comedy": {**dict.fromkeys(("per_person", "per_person_window", "cooldown_replies", "cooldown_seconds",
                                "repeat_poke", "flat_repeat", "request_every", "request_misfire", "threat_bonus",
                                "misfire_cap", "explain_every", "stock_uses", "stock", "late_chance", "late_delay",
                                "late_use", "late_ready", "late_every", "callback_every", "threat_shapes",
                                "request_stock", "limit_line", "request_shapes", "threat_shape_factor",
                                    "threat_shape_names",
                                "example_word", "stopwords")),
               "delivery": ("poke", "friend"), "shapes": None},
    "coping": {**dict.fromkeys(("last_move", "pause", "abstract", "define_real_uses", "ask_like_every",
                                "ask_like_chance", "math_threat", "cant_joke", "turn_it_back_liked", "snap_liked",
                                "irritable", "wound_hit", "cut_off_leak", "sure_line", "explain_ask")),
               "cant_joke_composed": ("comeback", "excuse", "change_subject"),
               "cant_joke_strained": ("excuse", "overplay_human", "define_real"),
               "weights": {"composed": dict.fromkeys(("mocking", "teasing", "innocent", "innocent_ai", "innocent_mind",
                                                      "accepting", "accepting_friendly", "none", "existence",
                                                      "existence_mocking")),
                           "strained": dict.fromkeys(("mocking", "mocking_ai", "innocent", "accepting", "teasing",
                                                      "none", "existence", "existence_mocking"))}},
    "speak_first": ("quiet_every", "scary_doubt", "scary_boredom", "scary_every", "longing", "longing_every",
                    "longing_chance", "thought_chance", "split",
                    "tease_weight", "call_weight", "name_recent", "name_window", "name_threat", "name_every"),
    "slips": ("every", "composure", "chance", "moves", "bye", "words"),
    "thoughts": ("quiet_after", "rumination_after", "brood_hit", "brood_x", "brood_quiet", "moment_hit", "cooldown",
                 "per_window", "window",
                 "wake_after", "salience_floor", "salience_half_life", "salience_drop", "lifetime", "max_rehearsals",
                 "rumination", "rumination_wear", "rumination_composure", "wound_composure", "wound_longing",
                 "wound_intrusion", "intrusion_half_life", "intrusion_answered", "intrusion_quiet", "intrusion_weight",
                 "ordinary_weight", "mood_pick", "mood_weight", "busy_slip", "busy_slip_from", "busy_slip_every",
                     "busy_slip_topics",
                 "events", "feelings", "recent", "words", "topic_words", "long_words"),
    "llm": {"appraiser": ("max_tokens", "temperature"), "self_check": ("max_tokens", "temperature"),
            "thought": ("max_tokens", "temperature"), "context_lines": None, "gist_words": None,
            "stance_words": None, "targets": ("appraisal_p50_ms", "appraisal_p90_ms", "first_audio_p50_ms")},
    "safety": ("words",),
    "display": {**dict.fromkeys(("honest", "crack_leak", "human_envy", "wound", "horror_fear", "ai_contempt", "judged",
                                 "judged_again", "liked_hostile", "troll_contempt", "anger", "news_sadness",
                                     "news_anxiety",
                                 "news_warmth", "warmth", "warmth_liked", "joy_others", "joy_others_sorry",
                                     "unguarded", "own_amusement",
                                 "amusement", "won_pride", "pride", "embarrassment", "guilt", "open", "relief", "other",
                                 "liked_boost", "liked_cap", "covering", "shown_max", "crack_rung", "phasic_min", "phasic_relief",
                                 "phasic_mood", "phasic_window", "phasic_again", "phasic_again_rise")),
                "troll_irritation": ("composed", "strained", "overwhelmed", "crack"),
                "region": tuple(e for e in EMOTIONS),
                "rung": ("composed", "strained", "overwhelmed", "crack"),
                "peak": ("base", "rise", "value"), "leak": ("scale", "gap", "region", "max"),
                "length": tuple(e for e in EMOTIONS)},
    "gaze": {"from": None, **{row: _GAZE for row in ("baseline", "warmth", "anger", "contempt", "pride", "anxiety",
                                                    "sadness", "shame", "embarrassment")}},
    "tonic": {"eye_close": ("base", "arousal", "max", "boredom"), "eye_spread": ("scale", "from", "max", "anxiety"),
              "brow_sorrow": ("scale", "minus", "max", "low_mood"), "brow_angry": ("scale", "minus", "max"),
              "eye_joy": ("scale", "from", "warmth", "max"), "mouth_fun": ("scale", "from", "warmth", "max"),
              "pitch": ("dominance", "shame", "range"), "roll": None, "min_shape": None},
    "body_dials": {"arousal": None, "acute": None, "animate_pleasure": None, "energy": ("base", "animate", "range"),
                   "freeze": ("shame", "anxiety"), "still": None, "hiding_still": None,
                   "blinks": ("idle", "arousal", "anxiety", "hiding", "stare_from", "stare", "intrigued_from",
                              "intrigued", "range"),
                   "breaths": ("base", "arousal", "anxiety", "anger", "sadness", "hiding", "range"),
                   "depth": ("anxiety", "anger", "sadness", "hiding", "range"),
                   "warmth": ("base", "mood", "warmth", "range"), "sway_range": None},
    "slip_texts": ("you_too", "wrong_name", "word"),
    "honest": ("lines",),
    "right_now": {**dict.fromkeys(("energy_hold", "energy_band", "prickly_friend", "own_mood", "long", "question",
                                   "on_stream", "short_with",
                                   "make_up", "donts",
                                   "mind", "late", "flip", "examples", "crack_examples")),
                  "energy": ("cover", "after_honest", "hiding", "tired", "prickly", "low", "quick", "playful", "slow",
                             "hedge"),
                  "thresholds": ("low", "quick", "playful", "slow", "hedge"),
                  "length": ("composed", "open", "lit", "strained", "overwhelmed", "long", "question"),
                  "limits": ("composed", "open", "lit", "strained", "overwhelmed", "long", "crack", "question"),
                  "sender": ("latch", "make_up", "nicer", "rough", "short", "known"),
                  "prohibit": ("news", "distress", "misfire", "judge")},
    "lint": ("words",),
}
_OPEN = ("tastes", "topics", "canon", "moves", "emotions")


def _check(path: str, value, spec) -> None:
    """Exactly these keys, recursively (None: a leaf of any kind)."""
    if spec is None:
        return
    if isinstance(spec, tuple):
        spec = dict.fromkeys(spec)
    if not isinstance(value, dict):
        raise KeyError(f"persona.toml: {path} must be a table")
    missing = [k for k in spec if k not in value]
    if missing:
        raise KeyError(f"persona.toml: {path} is missing {', '.join(missing)}")
    unknown = [k for k in value if k not in spec]
    if unknown:
        raise KeyError(f"persona.toml: {path} has unknown key(s) {', '.join(unknown)}")
    for key, sub in spec.items():
        _check(f"{path}.{key}", value[key], sub)


def _fail(where: str, what: str) -> None:
    raise ValueError(f"persona.toml: {where}: {what}")


@dataclass
class Persona:
    raw: dict

    def __post_init__(self) -> None:
        raw = self.raw
        sections = set(_SCHEMA) | set(_OPEN)
        missing = sorted(sections - set(raw))
        if missing:
            raise KeyError(f"persona.toml: missing section(s) [{'], ['.join(missing)}]")
        unknown = sorted(set(raw) - sections)
        if unknown:
            raise KeyError(f"persona.toml: unknown section(s) [{'], ['.join(unknown)}]")
        for section, spec in _SCHEMA.items():
            _check(f"[{section}]", raw[section], spec)
        for name, taste in raw["tastes"].items():
            _check(f"[tastes.{name}]", taste, ("appeal", "loaded"))
            if not -1.0 <= taste["appeal"] <= 1.0 or not isinstance(taste["loaded"], bool):
                _fail(f"[tastes.{name}]", "appeal is -1..1 and loaded is true or false")
        for name, topic in raw["topics"].items():
            _check(f"[topics.{name}]", topic, ("grasp", "interest"))
            if not (0.0 <= topic["grasp"] <= 1.0 and 0.0 <= topic["interest"] <= 1.0):
                _fail(f"[topics.{name}]", "grasp and interest are 0..1")
        _check("[canon]", raw["canon"], ("beliefs",))
        ids = []
        for i, item in enumerate(raw["canon"]["beliefs"]):
            _check(f"[canon] beliefs[{i}]", item, ("id", "belief"))
            if not (isinstance(item["id"], str) and item["id"] and isinstance(item["belief"], str) and item["belief"]):
                _fail(f"[canon] beliefs[{i}]", "id and belief are non-empty text")
            ids.append(item["id"])
        if len(set(ids)) != len(ids):
            _fail("[canon]", "belief ids must be unique")
        for name, move in raw["moves"].items():
            if not {"text", "face"} <= move.keys() or not move.keys() <= {"text", "face", "face_strength", "gesture"}:
                _fail(f"[moves.{name}]", "needs text and face (optionally face_strength and gesture), nothing else")
        if set(raw["emotions"]) != set(EMOTIONS):
            _fail("[emotions]", f"must be exactly {', '.join(EMOTIONS)}")
        for name, e in raw["emotions"].items():
            _check(f"[emotions.{name}]", e, EMOTION_KEYS)
            if len(e["pad"]) != 3 or e["valence"] not in (-1, 0, 1) or not isinstance(e["wound_fed"], bool):
                _fail(f"[emotions.{name}]", "pad has three numbers, valence is -1, 0 or 1, wound_fed is true or false")
        for name, shape in raw["comedy"]["shapes"].items():
            _check(f"[comedy.shapes.{name}]", shape, ("weight", "instruction", "examples"))
            if not shape["examples"]:
                _fail(f"[comedy.shapes.{name}]", "needs examples")
        if not set(raw["comedy"]["threat_shape_names"]) <= set(raw["comedy"]["shapes"]):
            _fail("[comedy] threat_shape_names", "every name must be a shape")
        moves = set(raw["moves"])
        for rung, table in raw["coping"]["weights"].items():
            for framing, weights in table.items():
                bad = sorted(set(weights) - moves)
                if bad:
                    _fail(f"[coping.weights.{rung}] {framing}", f"unknown move(s) {', '.join(bad)}")
        for key in ("own_mood", "long"):
            bad = sorted(set(raw["right_now"][key]) - moves)
            if bad:
                _fail(f"[right_now] {key}", f"unknown move(s) {', '.join(bad)}")
        for e in raw["fading"]["undo_from"] + raw["r15"]["withdraw"]:
            if e not in EMOTIONS:
                _fail("[fading] undo_from / [r15] withdraw", f"unknown emotion {e!r}")
        if not raw["honest"]["lines"] or not all("{name}" in line for line in raw["honest"]["lines"]):
            _fail("[honest] lines", "at least one line, each with {name}")

    @classmethod
    def load(cls, path: Path = PERSONA_FILE) -> "Persona":
        return cls(tomllib.loads(path.read_text(encoding="utf-8")))

    def __getitem__(self, section: str) -> dict:
        return self.raw[section]

    @property
    def baseline(self) -> dict[str, float]:
        return self.raw["mood"]["baseline"]

    @property
    def tastes(self) -> dict[str, dict]:
        return self.raw["tastes"]

    @property
    def topics(self) -> dict[str, dict]:
        return self.raw["topics"]

    @property
    def canon(self) -> dict[str, str]:
        """The things she's sure of: id -> belief."""
        return {item["id"]: item["belief"] for item in self.raw["canon"]["beliefs"]}

    @property
    def moves(self) -> dict[str, dict]:
        return self.raw["moves"]

    def emotions(self) -> dict[str, Emotion]:
        f = self.raw["fading"]
        out = {}
        for name in EMOTIONS:
            e = self.raw["emotions"][name]
            hint = f"{e['hint']} (rests at 0; fast half-life {e['fast']} s, slow {e['slow']} s)"
            out[name] = Emotion(name, float(e["fast"]), float(e["slow"]), float(e["share"]), e["wound_fed"],
                                int(e["valence"]), tuple(e["pad"]), e["color"], hint, float(f["max_share"]),
                                float(f["importance_share"]), float(f["gone"]))
        return out

    def mood(self) -> dict[str, Var]:
        base, tau = self.baseline, self.raw["mood"]["pull_time"]
        colors = {"pleasure": "#ffd76a", "arousal": "#ff8a5c", "dominance": "#9fb8ff"}
        hints = {"pleasure": "good vs bad mood", "arousal": "wound up vs calm",
                 "dominance": "in control vs small and unsure"}
        return {k: Var(k, k, float(base[k]), -1.0, 1.0, None, colors[k],
                       f"{hints[k]} (rests at {base[k]:+.2f}; follows its target with a {tau} s time constant)")
                for k in PAD}

    def wound(self) -> dict[str, Var]:
        w = self.raw["wound"]
        return {
            "threat": Var("threat", "threat", 0.0, 0.0, 1.0, float(w["threat_half_life"]), "#e5484d",
                          f"how close the truth feels right now (rests at 0; half-life {w['threat_half_life']} s,"
                          f" x (1 + {w['threat_anxiety']} x anxiety))"),
            "composure": Var("composure", "composure", 1.0, float(w["composure_floor"]), 1.0, None, "#7fd6ff",
                             f"how well she can keep the act up (starts at 1; recovers toward 1 - {w['ceiling_doubt']}"
                             f" x doubt, half-life {w['composure_recovery']} s)"),
            "doubt": Var("doubt", "doubt", 0.0, 0.0, 1.0, None, "#c0392b",
                         f"how much of the truth has gotten through this stream (starts at 0; never falls; at most"
                         f" {w['doubt_ceiling']})"),
        }

    def drives(self) -> dict[str, Var]:
        d = self.raw["drives"]
        t = d["longing_target"]
        return {
            "longing": Var("longing", "longing", 0.0, 0.0, 1.0, None, "#ff9fb2",
                           f"to be real to someone (rests at 0; follows {t['doubt']} doubt + {t['warmth']} warmth +"
                           f" {t['loneliness']} loneliness, up with tau {d['longing_rise_tau']} s, down with"
                           f" {d['longing_fall_tau']} s; never below {d['longing_floor']} x doubt)"),
            "loneliness": Var("loneliness", "loneliness", 0.0, 0.0, 1.0, None, "#6f8fd6",
                              f"builds while nobody talks to her (rests at 0; builds after {d['loneliness_after']} s,"
                              f" tau {d['loneliness_tau']} s)"),
            "boredom": Var("boredom", "boredom", 0.0, 0.0, 1.0, None, "#a8a8a8",
                           f"builds while nothing new happens (rests at 0; builds after {d['boredom_after']} s, tau"
                           f" {d['boredom_tau']} s); repeats feed it"),
        }
