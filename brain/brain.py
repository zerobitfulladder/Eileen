"""Eileen's brain: decides what her body does and when, and tells Godot.

Godot (avatar/link.gd) runs all per-frame motion: saccades, blinks, breathing,
gesture curves, face mixing, lip sync. This module decides *what* happens and
*when* (docs/mind.md, "What the body shows"; the body contract, §3) and sends
commands such as {"cmd": "look", "target": "camera"}:

  reading   a chat message: her eyes go to chat and read it word by word.
            Her face reacts in step with her eyes, in the order the mind
            checks things (new? pleasant? in the way? can she handle it?
            right or wrong?). What she feels shows, or hides behind the face
            she chooses and leaks for a moment. Then she composes her answer:
            no thinking face for easy messages.
  speaking  the faces she puts on (the actor's tags) hold while she talks and
            change at the word where the next one starts; the feeling her
            line answers (concern for someone's news, warmth, joy, interest,
            guilt) stays on her face while she says it; sound tags play
            their sound and gesture only; her head follows her phrasing; her
            own joke makes her smile before the punchline.
  after     the put-on face and the held feeling let go (a leak may slip
            out), then one of: the honest look down, the bluff tell, the
            denial tell, the joke check.
  idle      glances at the viewer, reads chat, looks around; her state adds
            glances, weight shifts and sighs; a thought turns her eyes inward.

Everything she feels comes from her mind (mind/): felt displays, leaks, the
resting face (tonic), blink and breathing rates. Nothing smiles without a
cause. Choices that matter are seeded draws (stream seed, event, purpose), so
a replay of the same events moves her body the same way, and every timing and
size varies by ±25% so the same choreography never looks identical twice.
Time is the event loop's clock; commands inside a speech clip are timed to
its audio.
"""

import asyncio
import logging
import math
import random
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from camera import ENGINE_MOVES, SHOTS, Cinematographer
from mimics import ACTOR_FACES, COMPOSITES, EMOTIONS, ENGINE_FELT, ENGINE_PUT_ON, FAMILY, LEAKS, Faces, Performance
from mind.expression import REGION, RUNG
from visemes import Analysis

_LOGGER = logging.getLogger("eileen")

# --- tags ---------------------------------------------------------------------

# Tags Chatterbox Turbo performs itself. Any other [tag] is a stage direction:
# stripped before speech and acted out instead.
SOUND_TAGS = {"laugh", "chuckle", "sigh", "gasp", "cough", "clear throat", "groan", "sniff", "shush", "crying"}
DELIVERY_TAGS = {"happy", "angry", "sarcastic", "surprised", "fear", "whispering", "dramatic", "narration",
                 "advertisement"}
SPOKEN_TAGS = SOUND_TAGS | DELIVERY_TAGS
STAGE_GESTURES = {"nod": "nod", "shake head": "shake", "tilt head": "tilt", "shrug": "shrug"}
STAGE_GAZES = {"look away": "away", "look down": "down", "look at chat": "chat", "look at camera": "camera"}
STAGE_TAGS = {"wink", *STAGE_GESTURES, *STAGE_GAZES}
SIDE_GESTURES = {"tilt", "recoil", "shrug", "turn", "tilt_beat"}
# How long each sound usually lasts, for when the voice wasn't measured (no phoneme recognizer).
SOUND_LENGTH = {"laugh": 1.4, "chuckle": 0.7, "sigh": 2.0, "gasp": 1.0, "cough": 0.9, "clear throat": 0.8,
                "groan": 1.2, "sniff": 0.6, "shush": 0.8, "crying": 2.0}

# --- the contract's constants (§3.3) ---------------------------------------------

LIKES = 0.4  # "someone she likes"
READ_WORD = (0.16, 0.20)  # s per word (the sender's name is the first word)
WORDS_PER_LINE = 7
LINE_RETURN = 0.3
GAZE_TO_CHAT = 0.2
ONSET = {"surprise": (0.15, 0.25), "plain": (0.25, 0.4), "irony": (0.5, 0.9)}
COVER_DELAY = {"composed": (0.3, 0.8), "strained": (0.8, 1.5)}  # overwhelmed: no cover
JOKE_MOVES = {"comeback", "banter", "joke", "callback", "use_comeback", "tease_someone"}
STUBBORN_MOVES = {"double_down", "technically_true", "stand_by_it", "hold_ground", "defend_taste", "explain_joke"}
DENIAL_MOVES = {"excuse", "cover_it", "vague", "soft_deflect", "insist"}
DODGE_COMPOSE = {"excuse", "vague", "cover_it", "soft_deflect", "change_subject", "define_real"}
JUDGE_MOVES = {"judge_dry", "judge_giving_up", "judge_curt"}
WOUND_FEELINGS = ("shame", "fear", "anxiety", "sadness", "envy", "embarrassment")
LEAK_WINDOWS = {"understanding": 1.0, "after": 1.5, "pause": 0.5, "backstage": 1.3}
ON_STOP_SLOTS = (("display", "face"), ("display", "stance"), ("felt", "felt"), ("felt", "check"), ("felt", "think"),
                 ("leak", "leak"))
SLIP_EVERY = 600.0  # the late double-take and the off-beat bob: at most once per 10 minutes each
AMUSED_LAUGH = 0.85  # felt amusement at this intensity or more is a laugh (mimics.felt: EYE_Joy 0.8, full mouth)
# Felt displays that stay on her face while she says her line (the feeling her words answer: someone's news,
# kindness, a topic she loves, an apology). Brief ones (surprise, fear, contempt, a laugh...) end on their own.
HELD_FELT = ("concern", "warmth", "joy", "interest", "guilt", "pride", "sadness")
HELD_FELT_MAX = 12.0  # s: the longest a felt display is held open through a line
HELD_FELT_FADE = 1.4  # s: how it lets go after her last word (a felt release)
# A felt reaction starts 0.2-0.5 s before the words that express it (spec): with a fast actor her first word
# came 0.6 s after she understood, before her face had reacted at all, so the gate waits this long past its onset.
FELT_LEAD = 0.35

_TAG = re.compile(r"\[([^\]]+)\]")
_GREETING = re.compile(r"\s*(hi|hey|hello|heya|hiya|yo|sup|good (morning|evening|night)|evening|morning)\b",
                       re.IGNORECASE)
_LAUGH = re.compile(r"l+o+l+|lmf?a+o+|a*(?:h+a+){2,}h*|(?:he){2,}h*|rofl|xd+|kek|😂+|🤣+|💀+", re.IGNORECASE)
_WORDS = re.compile(r"[\w']+|😂+|🤣+|💀+")
_PHRASE_END = re.compile(r"[,;:.!?…—]+(?=\s)")
_NEGATION = re.compile(r"\b(?:no|not|never|nope|nah|nothing|don't|can't|won't|isn't|didn't|doesn't|wasn't)\b",
                       re.IGNORECASE)


@dataclass
class Tag:
    name: str
    position: float  # 0..1, how far through the sentence's words it sits
    offset: int  # character index in SentencePlan.spoken
    intensity: float = 1.0  # from [name:0.5]


@dataclass
class SentencePlan:
    text: str  # what the TTS says: stage directions removed, sound tags kept
    tags: list[Tag]
    kind: str  # "question", "exclamation" or "statement"
    spoken: str  # just the words, no tags

    @property
    def sound_tags(self) -> tuple[tuple[int, str], ...]:
        """(offset in `spoken`, name) of each sound tag: [laugh], [sigh]..."""
        return tuple((t.offset, t.name) for t in self.tags if t.name in SOUND_TAGS)

    @property
    def has_speech(self) -> bool:
        return bool(re.search(r"\w", _TAG.sub("", self.text)))


# Tags the LLM makes up anyway ("[mild eye roll]", "[smirk]") -> the real tag and a strength.
_SOFTER = {"mild": 0.6, "slight": 0.55, "small": 0.6, "little": 0.6, "soft": 0.6, "faint": 0.5, "subtle": 0.5,
           "half": 0.6, "quick": 0.8, "light": 0.6, "big": 1.3, "huge": 1.4, "slow": 1.0}
_SYNONYMS = {"smirk": "smug", "smirks": "smug", "squint": "skeptical", "squints": "skeptical", "glare": "suspicious",
             "frown": "unsure", "eyeroll": "eye roll", "rolls eyes": "eye roll", "giggle": "chuckle", "snort": "chuckle",
             "huff": "sigh", "laughs": "laugh", "sighs": "sigh", "grins": "grin", "smiles": "smile", "nods": "nod",
             "shrugs": "shrug", "winks": "wink", "pouts": "pout", "thinking": "considering", "think": "considering",
             "look up": "recall", "blank stare": "deadpan", "stare": "deadpan", "tilt": "tilt head",
             "whisper": "whispering", "satisfied": "smug", "cautious": "unsure", "looking down": "look down",
             "looking away": "look away", "nervous": "unsure", "dry": "deadpan", "flat": "deadpan",
             "scream": "gasp", "screams": "gasp", "knowing look": "smug", "musing": "considering",
             "mischievous": "teasing", "sure": "smug", "tilting head": "tilt head", "tilts head": "tilt head",
             "head tilt": "tilt head", "confident": "smug", "amused": "smile", "soft smile": "smile"}
_KNOWN = (*ACTOR_FACES, *SPOKEN_TAGS, *STAGE_TAGS)


def _known(name: str) -> str | None:
    """The tag's real name if she knows it (aliases applied), else None."""
    name = Faces.name(name)
    return name if name in _KNOWN else None


def known_tag(name: str) -> tuple[str, float] | None:
    """A tag as written -> (real tag, strength), or None if it means nothing to her."""
    if real := _known(name):
        return real, 1.0
    words = name.replace("-", " ").split()
    strength = 1.0
    while words and words[0] in _SOFTER:
        strength = _SOFTER[words.pop(0)]
    rest = " ".join(words)
    if real := _known(_SYNONYMS.get(rest, rest)):
        return real, strength
    for known in sorted(_KNOWN, key=len, reverse=True):  # "a slow eye roll" -> eye roll
        if f" {known} " in f" {rest} ":
            return known, strength
    return None


def plan_sentence(sentence: str) -> SentencePlan:
    plain = " ".join(_TAG.sub(" ", sentence).split())
    total = max(1, len(plain))
    tags, tts_parts, last = [], [], 0
    for m in _TAG.finditer(sentence):
        name, _, value = m.group(1).partition(":")
        name = " ".join(name.lower().split())
        normal = known_tag(name)
        name, softer = normal if normal else (name, 1.0)
        try:
            intensity = min(1.5, max(0.1, float(value))) if value.strip() else softer
        except ValueError:
            intensity = softer
        said_before = len(" ".join(_TAG.sub(" ", sentence[: m.start()]).split()))
        tags.append(Tag(name, min(1.0, said_before / total), said_before, intensity))
        tts_parts.append(sentence[last: m.start()])
        if name in SPOKEN_TAGS:
            tts_parts.append(f"[{name}]")
        last = m.end()
    tts_parts.append(sentence[last:])
    end = plain.rstrip()
    kind = "question" if end.endswith("?") else "exclamation" if end.endswith("!") else "statement"
    return SentencePlan(" ".join("".join(tts_parts).split()), tags, kind, plain)


# --- small helpers ------------------------------------------------------------------


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _face(layer: str, slot: str, shapes: dict[str, float], *, attack: float, hold: float, release: float,
          curve: str = "felt", intensity: float = 1.0, **extra) -> dict:
    """A face_layer command for the few faces brain composes itself (short names: {"MTH_Small": 0.3})."""
    return {"cmd": "face_layer", "layer": layer, "slot": slot, "shapes": {f"Fcl_{k}": v for k, v in shapes.items()},
            "intensity": intensity, "attack": attack, "hold": hold, "release": release, "curve": curve, **extra}


def _look(target: str, offset: tuple[float, float] = (0.0, 0.0), **extra) -> dict:
    return {"cmd": "look", "target": target, "offset": [round(offset[0], 1), round(offset[1], 1)], **extra}


def _toward(yaw: float, pitch: float, **extra) -> dict:
    """Look in a direction relative to her body: yaw + = her left, pitch + = down."""
    return {"cmd": "look", "yaw": round(yaw, 1), "pitch": round(pitch, 1), **extra}


def _gesture(name: str, strength: float, duration: float | None = None) -> dict:
    out = {"cmd": "gesture", "name": name, "strength": round(strength, 2)}
    if duration is not None:
        out["duration"] = round(duration, 2)
    return out


def _laughter(text: str) -> bool:
    """The message is a laugh ("LMAOOO", "hahaha true", "lol"): it starts with one, or it's mostly laughter.
    A trailing "lol" on a jab ("ur a chatbot lol") is tone, not laughter."""
    words = _WORDS.findall(text)
    laughs = [bool(_LAUGH.fullmatch(w)) for w in words]
    return bool(words) and (laughs[0] or 2 * sum(laughs) >= len(words))


def _word(token: str) -> str:
    return re.sub(r"\W", "", token.lower())


def _jitter(rng: random.Random) -> float:
    return rng.uniform(0.75, 1.25)


def _shown(x: float) -> float:
    """How strong a shown felt display plays, from the spec's peak × k (0..1.3). The recipes read on stream at
    intensity 1.0 (the legibility test renders them there); the peak formula alone puts an ordinary feeling at
    0.6-0.7 of that, where brows, lids and mouth corners no longer read at the medium shot (live runs: a concern
    face at 0.68 was indistinguishable from her resting face). So the range is lifted and keeps its order:
    0.35 -> 0.9, 0.7 -> 1.1, 1.35 and up -> 1.5 (bigger since the user's live test found her faces too quiet).
    The mask decides whether a feeling shows, not how faint it is."""
    return _clamp(0.9 + 0.6 * (x - 0.35), 0.9, 1.5)


# --- plans ---------------------------------------------------------------------------


@dataclass
class Step:
    """One thing in a plan: a command to send, a lane event, or a Python-side action, at t seconds."""
    t: float
    cmd: dict | None = None
    hold: float | None = None  # the gaze stays put this long from t (brain's own gaze movers wait)
    soft: bool = False  # the hold only keeps her eyes on the camera: composing may look away anyway
    lane: tuple[str, str] | None = None
    fn: Callable[[], None] | None = None
    tag: str = ""  # "gaze": a reading look; "release" / "leak": kept when a new reading starts


def _shift(step: Step, dt: float) -> Step:
    """The same step, dt seconds later."""
    return replace(step, t=step.t + dt)


class Timeline:
    """The scheduled steps of one phase; cancel() drops what hasn't run yet."""

    def __init__(self) -> None:
        self._handles: list[tuple[asyncio.TimerHandle, str]] = []

    def at(self, when: float, fn: Callable, *args, tag: str = "") -> None:
        loop = asyncio.get_running_loop()
        self._handles = [(h, t) for h, t in self._handles if h.when() > loop.time() and not h.cancelled()]
        self._handles.append((loop.call_at(when, fn, *args), tag))

    def cancel(self, keep: Callable[[float, str], bool] | None = None) -> None:
        kept = []
        for handle, tag in self._handles:
            if keep is not None and keep(handle.when(), tag):
                kept.append((handle, tag))
            else:
                handle.cancel()
        self._handles = kept


@dataclass
class _Fix:
    """One fixation while she reads: when (s after the reading starts), which words, where on the chat."""
    at: float
    words: tuple[int, ...]
    x: float
    y: float


@dataclass
class _Reading:
    """One chat message on her face, from her first glance at it until she starts answering."""
    sender: str
    text: str
    seq: int
    rng: random.Random  # purpose "body": every draw of this reading, in a fixed order
    timeline: Timeline
    tokens: list[str] = field(default_factory=list)
    fixes: list[_Fix] = field(default_factory=list)
    pending: bool = False  # she's still speaking: the reading starts after her line
    started: bool = False
    t0: float = math.nan
    t_end: float = math.nan
    reading: object = None  # mind.Reading, once the appraisal has landed
    t_a: float = math.nan
    t_c: float = math.nan
    t_f: float = math.nan
    ready: asyncio.Event = field(default_factory=asyncio.Event)  # t_c and the freeze are known
    freeze_end: float = -math.inf
    words_at: float = -math.inf  # the crack: her words come no earlier than this
    felt_lead: float = -math.inf  # her first word waits for her felt reaction to have started (FELT_LEAD)
    primary: str = ""
    primary_rise: float = 0.0
    hidden: bool = False
    wound_primary: bool = False
    cover: str = ""
    cover_at: float = math.inf
    cover_intensity: float = 1.0
    cover_started: bool = False
    blame_until: float = -math.inf
    composed: bool = False  # composing started
    answering: bool = False  # her reply has started
    wrapped: bool = False


@dataclass
class _Reply:
    """One reply of hers, from the clips brain builds to the end of the after-line sequence."""
    kind: str  # "reply" (to a message), "first" (she speaks first) or "say"
    seq: int
    coping: object = None  # mind.Coping
    reading: _Reading | None = None
    honest: bool = False
    joke: bool = False
    stance: str = ""  # "stubborn", "math", "philosophy" or ""
    denial: bool = False
    denial_gaze: float = 0.0  # s of held eye contact at the start of a denial line
    utterance: int = -1
    face: str = ""  # the put-on face the clips built so far leave held
    face_open: bool = False
    face_moves_head: bool = False
    teasing: bool = False
    punchline: bool = False
    brow_at: float = -math.inf  # the last brow beat, relative to the start of the next clip
    started: float = math.nan  # loop time of her first sound
    mind_started: float = math.nan


@dataclass
class _Current:
    """The felt display playing now (felt/felt)."""
    name: str
    family: str
    source: str
    started: float
    peak: float
    ends: float
    face: str = ""  # the recipe that shows it ("concern" for sadness about news, "blend: ..."), "" if not held-able
    cmd: dict | None = None  # its lasting felt/felt face_layer, to hold it open through her line


@dataclass
class _Shown:
    """How one felt display plays (§3.5)."""
    emotion: str
    steps: list[Step]  # relative to the display's start
    shown: bool = True
    face: str = ""  # what shows (a recipe name)
    peak_at: float = 0.0
    ends_at: float = 0.0
    hold_end: float = 0.0  # when its peak ends
    cover: str = ""  # hidden behind this put-on face instead (row 7, row 9)
    cover_intensity: float = 1.0
    cover_delay: float = 0.0
    push: bool = False  # a felt moment that needs a closer shot (tender, guilt)
    claims: tuple[tuple[str, float], ...] = ()  # (emotion, s) it absorbs from the tick
    joy: bool = False


@dataclass
class _HeldFace:
    name: str
    open: bool
    until: float
    moves_head: bool


class Brain:
    def __init__(self, send: Callable[[dict], None], energy: float = 0.3, warmth: float = 0.25,
                 cinematic: float = 0.6, seed: int | None = None):
        if seed is None:
            seed = random.randrange(1 << 30)
            _LOGGER.info("brain seed %d", seed)
        self._send = send
        self._seed = str(seed)
        self.rng = random.Random(f"{seed}:brain")  # idle motion and faces
        self.faces = Faces(self.rng)
        self.camera = Cinematographer(cinematic, random.Random(f"{seed}:camera"))
        self._mind = None
        self._base_energy = energy
        self.energy = energy
        self.warmth = warmth
        self.targets: set[str] = {"camera"}
        self._task: asyncio.Task | None = None
        self._speaking = False
        self._gaze = "camera"  # what she's looking at: a target name, or "away"
        self._gaze_holds: list[tuple[float, float, bool]] = []  # (start, end, soft), loop time
        self._clip_holds: dict[tuple[int, int], list[tuple[float, float, bool]]] = {}  # relative to the clip's start
        self._clip_actions: dict[tuple[int, int], list[tuple[float, Callable[[], None]]]] = {}
        self._favorite_side = self.rng.choice((1.0, -1.0))  # people tend to look away to one side
        self._boost = 0.0
        self._hiding = False
        self._last_idle = ""
        self._next_reframe = 0.0
        self._purposes: dict[tuple[str, str], int] = {}
        self._events = 0  # replies without a mind (the event number for seeded draws)
        self._tick = 0
        # Phases.
        self._read: _Reading | None = None  # the message she's reading or reacting to
        self._prepared: _Reply | None = None  # the next reply (read_reaction / speaking_first)
        self._replies: dict[int, _Reply] = {}
        self._playing: _Reply | None = None
        self._after = Timeline()
        self._idle_tl = Timeline()
        self._speech_tl = Timeline()
        self._ticks = Timeline()
        self._seq_tl = Timeline()
        self._stopped = asyncio.Event()
        self._release_at = math.inf  # when the after-line lets go of display/face
        # Faces in play.
        self._face: _HeldFace | None = None  # display/face
        self._felt: _Current | None = None  # felt/felt
        self._felt_held = False  # felt/felt is held open through her line (HELD_FELT)
        self._claims: dict[str, tuple[float, float]] = {}  # emotion -> (from, until): the tick doesn't play it
        self._played: dict[tuple[str, str], float] = {}  # (emotion, source) -> when it last played
        self._batch: list[tuple[str, float, float]] = []
        self._queued: tuple[str, float, float, float] | None = None  # (emotion, peak, rise, queued at)
        # Leaks.
        self._leaked: dict[str, float] = {}
        self._last_leak = -math.inf
        self._honest = False  # an honest answer: no leaks from its reading to the end of its after-line
        self._leaks_off_until = -math.inf  # the crack's first 4 s
        # Slips and voice.
        self._serious_at = -math.inf  # the last distress or honest reading
        self._double_take_at = -math.inf
        self._bob_at = -math.inf
        self._voice_first = False
        self._happy_due = False
        self._fear_at = -math.inf  # a fiction fear of 0.5 or more was displayed
        self._startle_at = -math.inf
        # The body.
        self._body_sent: dict[str, float] = {}
        self._tonic: tuple[dict[str, float], float, float] | None = None  # low-passed
        self._tonic_sent: tuple[dict[str, float], float, float] | None = None
        self._tonic_at = -math.inf
        self._gaze_profile: dict | None = None
        self._joy_at = -math.inf
        self._philosophy = False
        self._threat_peak: float | None = None  # the highest threat since her last relief sigh
        self._S_was_high = False
        self._cues: dict[str, float] = {}  # state cue -> when it's due next (loop time)
        self._skip_glance = False

    # --- wiring from the server -------------------------------------------------------

    @property
    def mind(self):
        return self._mind

    @mind.setter
    def mind(self, mind) -> None:
        """A (new) mind: the stream seed comes from it, so a replay gives the same body."""
        self._mind = mind
        if mind is not None:
            self._seed = str(mind.coper.seed)
            self.rng.seed(f"{self._seed}:brain")
            self.camera.rng.seed(f"{self._seed}:camera")
            self._favorite_side = self.rng.choice((1.0, -1.0))
            self._tonic = self._tonic_sent = None
            self._body_sent = {}

    def connected(self, targets: list[str]) -> None:
        """Godot said hello: set the body up and start living."""
        if "chat" not in targets:
            raise ValueError(f"Godot has no 'chat' look target (got {targets}); eileen.tscn needs Targets/Chat")
        self.targets = set(targets) | {"camera"}
        self._cancel_all()
        self._body_sent = {}
        self._tonic = self._tonic_sent = None
        if self.mind is None:
            self._send_body()
        else:
            self.apply_body(self.mind.body(), self.mind.tonic(), self.mind.gaze())
        self._send(self.catalog())
        for command in self.camera.setup():
            self._send_cmd(command)
        self._begin(self._idle)

    def disconnected(self) -> None:
        self._cancel_all()

    def set_cinematic(self, value: float) -> None:
        self.camera.cinematic = _clamp(value)
        self.cmd("camera_handheld", amount=self.camera.handheld())

    def catalog(self) -> dict:
        """What can be tested from Godot's debug dropdowns. Every item is unique."""
        reactions = [f"[{tag}]" for tag in sorted((SPOKEN_TAGS | STAGE_TAGS) - set(ACTOR_FACES))]
        return {"type": "catalog",
                "expressions": {
                    "Put-on faces (her tags)": list(ACTOR_FACES),
                    "Put-on (engine)": [*ENGINE_PUT_ON, "social: greet", "social: qualify"],
                    "Felt faces (emotions)": [*EMOTIONS, "concern"],
                    "Felt faces (engine)": list(ENGINE_FELT),
                    "Composites": list(COMPOSITES),
                    "Leaks": [f"leak: {name}" for name in LEAKS],
                    "Reactions": reactions,
                    "Sequences": list(self._SEQUENCES)},
                "camera": {"Shots": SHOTS, "Engine moves": ENGINE_MOVES, "Framing": ["other side", "base shot"]}}

    _SEQUENCES = ("freeze 1.0 s", "flinch", "crack (body only)", "joke check", "left hanging", "denial tell",
                  "bluff tell", "failed wink: shut", "failed wink: squint", "double-take slip", "thought (wound)",
                  "honest after-line")

    def perform_now(self, item: str) -> None:
        """Play one catalog item right away (debug dropdown), through the same functions the live flow uses."""
        self._seq_tl.cancel()
        rng = random.Random(f"{self._seed}:perform:{item}:{self._now():.3f}")
        side = self._side(rng)
        if item in ACTOR_FACES or item in ENGINE_PUT_ON:
            steps = self._perf_steps(self.faces.put_on(item, energy=self.energy, hold=2.0), 0.0)
        elif item.startswith("social: "):
            steps = self._perf_steps(self.faces.social(item.removeprefix("social: ")), 0.0)
        elif item in EMOTIONS or item == "concern" or item in ENGINE_FELT or item in COMPOSITES:
            hold = 2.0 if item == "thinking" else None
            steps = self._perf_steps(self.faces.felt(item, 0.8, hold=hold), 0.0)
        elif item.startswith("leak: "):
            steps = self._perf_steps(self.faces.leak(item.removeprefix("leak: "), 0.5), 0.0)
        elif item.startswith("[") and item.endswith("]"):
            tag = item[1:-1]
            if tag not in SPOKEN_TAGS and tag not in STAGE_TAGS:
                raise KeyError(f"perform: no tag {item!r}")
            steps = self._tag_steps(tag, 0.0, SOUND_LENGTH.get(tag, 0.0), 1.0, rng, mind_free=True)
        elif item in self._SEQUENCES:
            steps = self._sequence(item, rng, side)
        else:
            raise KeyError(f"perform: no catalog item {item!r}")
        self._run(steps, self._now(), self._seq_tl)

    def _sequence(self, item: str, rng: random.Random, side: float) -> list[Step]:
        match item:
            case "freeze 1.0 s":
                return [Step(0.0, {"cmd": "freeze", "seconds": 1.0, "breath": 1.3, "double_blink": True,
                                   "exhale": 0.5}, lane=("freeze", "1.00 s"))]
            case "flinch":
                return [Step(0.0, {"cmd": "freeze", "seconds": 0.25, "exhale": 0.0, "blink_hold": 0.15},
                             lane=("flinch", "0.25 s"))]
            case "crack (body only)":
                return self._crack_steps(0.0, 1.05, rng, side, warm=True)
            case "joke check":
                return self._joke_glance(rng, side)
            case "left hanging":
                return self._left_hanging(rng, side)
            case "denial tell":
                return self._denial_tell(rng, side)
            case "bluff tell":
                return self._bluff_tell(rng, side)
            case "failed wink: shut" | "failed wink: squint":
                variant = item.removeprefix("failed wink: ")
                return self._perf_steps(self.faces.failed_wink(variant, side), 0.0, lane=("slip", "wink"))
            case "double-take slip":
                return self._double_take(0.0, rng)
            case "thought (wound)":
                return self._thought_steps(rng, wound=True, tone="shame", length=rng.uniform(1.5, 3.0))[0]
            case "honest after-line":
                return self._honest_after(rng, side)[0]
        raise KeyError(item)

    def camera_now(self, name: str) -> None:
        """Run one camera shot or engine move right away (debug dropdown)."""
        self._run([self._camera_step(c, 0.0) for c in self.camera.test(name, self._now())], self._now(),
                  self._seq_tl)

    # --- reading a message (§3.4) ---------------------------------------------------------

    def message_arrived(self, sender: str, text: str) -> None:
        """A chat message (Server.mind_reply, right before mind.read): her eyes go to chat and she reads
        it word by word while her mind appraises it. If she's still speaking, she reads it after her line."""
        m = self._need_mind()
        old = self._read
        if old is not None:  # a reading nobody answered (an appraisal error, an empty reply)
            old.timeline.cancel()
            old.ready.set()
        seq = m.seq + 1  # mind.read numbers the message next
        r = _Reading(sender, text, seq, self._roll("body", seq), Timeline())
        self._read = r
        self._prepared = None
        if self._speaking:
            r.pending = True
            return
        self._start_reading(r, self._now())

    def _start_reading(self, r: _Reading, t0: float) -> None:
        if self._read is not r:
            return
        r.pending, r.started, r.t0 = False, True, t0
        self._stop_motion()
        self._idle_tl.cancel()
        self._after.cancel(keep=lambda when, tag: tag in ("release", "leak") and when <= t0 + 0.6)
        if self._release_at > t0 + 0.6 and self._release_at < math.inf:  # her line's face lets go as she reads
            self._release_face(0.2)
        self._release_at = math.inf
        rng, m = r.rng, self.mind
        person = m.state.people.get(r.sender)
        r.tokens = [r.sender, *r.text.split()]
        x, y, t, size, on_line = 6.0 + rng.uniform(-1.0, 1.0), 0.0, GAZE_TO_CHAT, 1, 0
        i = 0
        while i < len(r.tokens):
            if on_line >= WORDS_PER_LINE:
                t += LINE_RETURN
                x, y, on_line = 6.0 + rng.uniform(-1.0, 1.0), y + rng.uniform(1.5, 2.5), 0
            n = min(size, len(r.tokens) - i)
            r.fixes.append(_Fix(t, tuple(range(i, i + n)), x, y))
            t += sum(rng.uniform(*READ_WORD) for _ in range(n))
            x -= rng.uniform(2.0, 3.5)
            i, on_line, size = i + n, on_line + n, 3 - size
        r.t_end = t0 + t
        steps = [Step(f.at, fn=lambda f=f: self._look_if_free(_look("chat", (f.x, f.y))), tag="gaze")
                 for f in r.fixes]
        steps.append(Step(0.0, {"cmd": "body_ramp", "param": "blinks_per_minute", "value": 0.33, "seconds": 0.2,
                                "back_after": round(max(t, 1.5) + 0.5, 2)}))
        if person is not None and person.threat > m.persona["person"]["tense_threat"]:
            steps += self._perf_steps(self.faces.check("tense", side=self._side(rng)), 0.25, lane=("flinch", "tense"))
        if person is not None and person.familiarity > 0.3 and _GREETING.match(r.text):
            steps += self._perf_steps(self.faces.check("greet_flash", side=self._side(rng)), rng.uniform(0.25, 0.35),
                                      lane=("social", "greet flash"))
        words = len(r.text.split())
        if words > 15:
            steps.append(Step(GAZE_TO_CHAT, _gesture("lean_in", 0.3, t - GAZE_TO_CHAT)))
        friendly = person is not None and person.liking >= LIKES
        if rng.random() < 0.5 and friendly and (r.text.rstrip().endswith("?") or words > 15):
            steps.append(Step(t, _gesture("nod", 0.4, 0.45)))
        steps.append(Step(t + 1.5, fn=lambda: self._reading_stalled(r)))
        self._run(steps, t0, r.timeline)
        if r.reading is not None:  # the appraisal landed while she was still speaking
            self._react(r)

    def _look_if_free(self, look: dict, hold: float | None = None) -> None:
        """A look that gives way to one that's held (a display's gaze, the crack's look down)."""
        if self._can_move_gaze():
            self._send_cmd(dict(look))
            if hold is not None:
                now = self._now()
                self._gaze_holds.append((now, now + hold, False))

    def _gaze_free_at(self, over_soft: bool = False) -> float:
        now = self._now()
        return max((b for a, b, soft in self._gaze_holds if a <= now < b and not (soft and over_soft)), default=now)

    def _reading_stalled(self, r: _Reading) -> None:
        if r.reading is None and self._read is r:
            self.look("camera")

    def read_reaction(self, reading) -> None:
        """Her mind has read the message (mind.Reading): the rest of the reading face, the cover and
        composing. A reply follows unless the appraisal failed."""
        self._need_mind()
        r = self._read
        if r is None or r.seq != reading.seq:
            raise ValueError(f"read_reaction for message #{reading.seq} without message_arrived"
                             f" (reading #{r.seq if r else None})")
        r.reading = reading
        r.t_a = self._now()
        if not reading.error:
            cp = reading.coping
            self._prepared = _Reply("reply", r.seq, cp, r, honest=cp.move == "honest")
            self._voice_first = True
            self._joke_claim(cp)
            if reading.appraisal.distress or cp.move == "honest":
                self._serious_at = r.t_a
        if r.started:
            self._react(r)

    def _react(self, r: _Reading) -> None:
        """When the appraisal has landed: understanding, the re-read, the novelty check, a freeze or a
        flinch, which feeling leads, the honest face, the crack's first beats; then what shows."""
        m, rd, rng, tl = self.mind, r.reading, r.rng, r.timeline
        now = self._now()
        t_a = max(r.t_a, r.t0)
        if rd.error:  # her face shows only the reading glance
            r.ready.set()
            self._wrap_reading(r)
            return
        a, fx, cp = rd.appraisal, rd.effects, rd.coping
        honest, crack = cp.move == "honest", cp.rung == "crack"
        if honest:
            self._honest = True
        steps: list[Step] = []
        # 1. Understanding: where her eyes reach the trigger word, or when the appraisal lands.
        key = _word(a.trigger.split()[0]) if a.trigger.strip() else ""
        wi = next((i for i, tok in enumerate(r.tokens) if i > 0 and key and _word(tok) == key), len(r.tokens) - 1)
        fix = next(f for f in r.fixes if wi in f.words)
        t_w = r.t0 + fix.at
        t_c = r.t_c = max(t_w, t_a)
        if crack:
            self._leaks_off_until = t_c + 4.0
        steps.append(Step(t_c, lane=("understanding", a.trigger or r.tokens[wi])))
        # 2. A re-read if the meaning came late; a double take if it's surprising.
        side = self._side(rng)
        if a.novelty < 0.75 and t_a - t_w > 0.3:
            now_fix = max((f for f in r.fixes if r.t0 + f.at <= t_a), key=lambda f: f.at)
            back, length = rng.uniform(3.0, 6.0), rng.uniform(0.3, 0.5)
            steps.append(Step(t_a, fn=lambda: self._look_if_free(_look("chat", (now_fix.x + back, now_fix.y)), length),
                              tag="gaze"))
            if t_a + length >= r.t_end:
                last = r.fixes[-1]
                steps.append(Step(t_a + length, fn=lambda: self._look_if_free(_look("chat", (last.x, last.y))),
                                  tag="gaze"))
        elif a.novelty >= 0.75:
            steps += self._perf_steps(self.faces.check("double_take", side=side), t_c)
        # 5 (first part). Which feeling leads, and when the felt reaction starts.
        rises = {k.removeprefix("emotion."): v for k, v in fx.deltas.items()
                 if k.startswith("emotion.") and v >= 0.08 and k != "emotion.surprise"}
        wound = {n: v for n, v in rises.items() if n in WOUND_FEELINGS and self._wound_caused(n)}
        if cp.rung != "" and wound:
            r.primary, r.wound_primary = max(wound, key=wound.get), True
        elif rises:
            r.primary = max(rises, key=rises.get)
        r.primary_rise = rises.get(r.primary, 0.0)
        for k, v in fx.deltas.items():
            if k.startswith("emotion.") and v >= 0.05:
                self._claim(k.removeprefix("emotion."), t_a, t_c + 4.0)
        irony = (a.reality == "joke" or a.funny > 0 or a.invites != "none" or fx.framing in ("teasing", "mocking"))
        t_f = t_c + rng.uniform(*ONSET["irony" if irony else "plain"])
        surprise = fx.deltas.get("emotion.surprise", 0.0)
        surprise_lead = a.novelty >= 0.75 and surprise >= 0.12
        # 3. The novelty check (never a gasp).
        if a.novelty >= 0.5 and rng.random() < 0.75:
            at = t_c + rng.uniform(0.0, 0.15) * _jitter(rng)
            size = _jitter(rng)
            if a.novelty < 0.75:
                steps += self._perf_steps(self.faces.check("brow_flash", size=size, side=side), at)
            elif not surprise_lead:
                steps += self._perf_steps(self.faces.check("brow_flash_big", size=size, side=side), at)
        # 4. A freeze, only for a hit she can't brush off; a flinch for anything less.
        x = fx.hit * (1.0 - fx.deniable)
        credible = fx.cred >= 0.5
        if credible:
            x = max(x, fx.deltas.get("emotion.fear", 0.0))
        first = fx.pushed or (fx.hit0 > 0.0 and fx.hit / fx.hit0 >= 0.9)
        seconds = 0.0
        if (x >= 0.3 and first) or credible:
            seconds = min(1.4, 0.3 + x)
            freeze = {"cmd": "freeze", "seconds": round(seconds, 2), "breath": round(min(2.0, max(0.6, seconds + 0.3)), 2),
                      "double_blink": rng.random() < 0.4, "exhale": 0.5}
            if not crack:  # the crack's sequence freezes her itself
                steps.append(Step(t_c, freeze, lane=("freeze", f"{seconds:.2f} s")))
        elif fx.hit >= 0.15:
            seconds = rng.uniform(0.2, 0.3)
            flinch = {"cmd": "freeze", "seconds": round(seconds, 2), "exhale": 0.0,
                      "blink_hold": round(rng.uniform(0.12, 0.18), 2)}
            if not crack:
                steps.append(Step(t_c, flinch, lane=("flinch", f"{seconds:.2f} s")))
        if crack:
            seconds = max(0.4, seconds)
        if seconds:
            r.freeze_end = t_c + seconds
        # The surprise leads and turns into the next feeling (not a second display).
        if surprise_lead:
            e = m.state.emotions["surprise"]
            peak = _clamp(0.35 + 0.8 * surprise + 0.3 * e.target)
            at = t_c + rng.uniform(*ONSET["surprise"])
            perf = self.faces.felt("surprise", _shown(peak), side=side)
            steps += self._perf_steps(perf, at, lane=("felt", "surprise"))
            t_f = max(t_f, at + perf.peak_at + 0.2)
        r.t_f = t_f
        # 12. She gets a joke a beat late; or almost gets a correction.
        if fx.late == "realize":
            when = next(item[0] for item in m.state.later if item[5] == "realize")
            at = now + (when - m.now)
            self._claim("amusement", at - 0.5, at + 3.0)
            tl.at(at, self._realize, at)
        line = m.state.last_line
        if (a.contradicts == "correct" and line.get("kind") == "joke" and m.now - line.get("at", -math.inf) < 120.0):
            steps += self._perf_steps(self.faces.felt("realize", 0.5, hold=0.1, slot="check", side=side), t_c + 0.3)
        # 13. Felt moments that need a closer shot start the camera when the appraisal lands.
        if not honest and (crack or r.primary == "guilt" or (r.primary == "warmth" and self._tender(r.primary, rd))):
            steps += [self._camera_step(c, t_a) for c in self.camera.push(t_a, force=crack)]
        if honest:  # the sincere face and a steady look, held through the line
            steps += self._perf_steps(self.faces.felt("sincere", 0.9, hold=-1, side=side), t_f + 0.3,
                                      lane=("felt", "sincere"))
            steps.append(Step(t_f + 0.3, _look("camera"), hold=2.0))
        if crack:
            steps += self._crack_steps(t_c, r.freeze_end - t_c, rng, side, warm=m.state.emotions["warmth"].target >= 0.4)
            r.words_at = t_c + 2.0
        self._run(steps, 0.0, tl)
        r.ready.set()
        self._what_shows(r)

    def _what_shows(self, r: _Reading) -> None:
        """The display rules decide what shows: the primary display, the understanding leak, the checks, the
        cover, a second display, mimicry, composing, and the social smile."""
        m, rd, rng, tl = self.mind, r.reading, r.rng, r.timeline
        a, fx, cp = rd.appraisal, rd.effects, rd.coping
        honest, crack = cp.move == "honest", cp.rung == "crack"
        t_c, t_f = r.t_c, r.t_f
        rung = cp.rung or m.rung
        side = self._side(rng)
        planned_display = False  # a felt display (primary or second) plays from this reading
        bright_at = math.inf  # when the first bright display starts
        shown = None
        if r.primary and not honest and not crack:
            e = m.state.emotions[r.primary]
            peak = _clamp(0.35 + 0.8 * r.primary_rise + 0.3 * e.target)
            shown = self._felt_plan(r.primary, peak, r.primary_rise, rng, r)
            if shown is not None and shown.shown:
                self._show(shown, t_f, tl)
                planned_display = True
                r.felt_lead = t_f + FELT_LEAD  # her face reacts before her words do
                if FAMILY[shown.emotion] == "bright":
                    bright_at = t_f
            r.hidden = shown is None or not shown.shown
        # 9. The cover: when the primary is hidden, or a wound feeling chose the move.
        cover, cover_at, cover_intensity = "", math.inf, 1.0
        if not honest and not crack and rung != "overwhelmed" and r.primary and (r.hidden or r.wound_primary):
            neutralized = rd.effects.deltas.get("emotion.irritation", 0.0) >= 0.08 and m.view()["irritation"]["k"] == 0.0
            cover = cp.face or (rng.choice(("bored", "deadpan")) if neutralized else "")
            if cover:
                cover_at = t_f + rng.uniform(*COVER_DELAY[rung])
        if shown is not None and shown.cover and not honest and not crack:
            if shown.emotion == "contempt" or not cover:  # row 7's skeptical face; row 9's substitute
                cover, cover_intensity = shown.cover, shown.cover_intensity
                cover_at = t_f + shown.cover_delay
        r.cover, r.cover_at, r.cover_intensity = cover, cover_at, cover_intensity
        if cover:
            tl.at(cover_at, self._start_cover, r)
        # 7. Hidden: the understanding window, before the cover.
        if r.primary and r.hidden and not honest and not crack:
            at = t_c + rng.uniform(0.25, 0.6)
            if at < cover_at:
                tl.at(at, self._understanding_leak, r, tag="leak")
        # 6. The checks, in Scherer's order, each with chance 0.75 and ±25%.
        if not honest and not crack and r.primary:
            self._checks(r, rng, side)
        # 8. A second display: another family, a rise of 0.25 or more, from the primary's peak on.
        if not honest and not crack and r.primary:
            rises = {k.removeprefix("emotion."): v for k, v in fx.deltas.items()
                     if k.startswith("emotion.") and k != "emotion.surprise" and v >= 0.25}
            family = FAMILY[r.primary]
            others = {n: v for n, v in rises.items() if n != r.primary and FAMILY[n] != family}
            if others:
                name = max(others, key=others.get)
                e = m.state.emotions[name]
                second = self._felt_plan(name, _clamp(0.35 + 0.8 * others[name] + 0.3 * e.target), others[name], rng, r)
                if second is not None and second.shown:
                    at = t_f + (min(max(shown.peak_at, shown.hold_end), shown.peak_at + 1.0) if not r.hidden
                                else rng.uniform(0.4, 0.7))
                    self._show(second, at, tl)
                    planned_display = True
                    if FAMILY[second.emotion] == "bright":
                        bright_at = min(bright_at, at)
                elif second is not None and second.cover and not cover:
                    r.cover, r.cover_at, r.cover_intensity = second.cover, t_f + second.cover_delay, second.cover_intensity
                    cover, cover_at = r.cover, r.cover_at
                    tl.at(cover_at, self._start_cover, r)
        # 10. Mimicry: laughter in the message, when nothing else shows.
        laughing = a.reception in ("laughed", "laughed_at") or _laughter(r.text)
        if laughing and not planned_display and not honest and not crack:
            at = t_c + rng.uniform(0.3, 0.5)
            person = m.state.people.get(r.sender)
            liking = person.liking if person else 0.0
            troll = liking < 0.0 or fx.framing in ("mocking", "tool")
            if troll:
                perf = self.faces.put_on("deadpan", energy=self.energy, intensity=0.8, hold=1.0)
                tl.at(at, self._put_on_now, perf, "deadpan", ("felt", "mimicry"))
            elif person is None or person.threat < 0.3:
                perf = self.faces.felt("amusement", 0.3 + 0.2 * max(0.0, liking), hold=0.6, slot="check")
                self._retime(perf, attack=0.2, release=0.6)
                self._run(self._perf_steps(perf, at, lane=("felt", "mimicry")), 0.0, tl)
                bright_at = min(bright_at, at)
        # 14. Composing, until her first word.
        compose_at = max(t_f + 1.0, r.t_end, r.freeze_end, r.blame_until, (cover_at + 0.4) if cover else -math.inf)
        if crack:
            compose_at = max(compose_at, t_c + 3.0)
        tl.at(compose_at, self._compose, r)
        # 11. The social smile: greetings, thanks and goodbyes, from anyone.
        if not honest and not crack and (a.social in ("greeting", "thanks") or a.leaving > 0):
            at = t_c + rng.uniform(0.3, 0.5)
            if not (bright_at <= at + 1.0):
                self._run(self._perf_steps(self.faces.social("greet"), at, lane=("social", "greet")), 0.0, tl)

    def _checks(self, r: _Reading, rng: random.Random, side: float) -> None:
        """The reading face's checks after the felt onset (§3.4 step 6). Each fires with chance 0.75; times
        and sizes vary ±25%. Hidden primary: smaller, and none after the cover starts."""
        m, rd = self.mind, r.reading
        a, fx = rd.appraisal, rd.effects
        rises = {k.removeprefix("emotion."): v for k, v in fx.deltas.items() if k.startswith("emotion.") and v >= 0.08}
        negative = {n: v for n, v in rises.items() if m.state.emotions[n].valence < 0}
        lead = max(negative, key=negative.get) if negative else ""
        composure = m.state.wound["composure"].value
        primary = r.primary
        scale = 0.7 if r.hidden else 1.0

        def fire(lo: float, hi: float) -> tuple[float, float] | None:
            if rng.random() >= 0.75:
                return None
            return r.t_f + rng.uniform(lo, hi) * _jitter(rng), _jitter(rng) * scale

        # valence: pleasant or not
        if (draw := fire(0.0, 0.25)) is not None:
            if FAMILY[primary] == "bright":
                self._check_at(r, draw[0], "lips_up", draw[1], side, joyful=primary in ("joy", "amusement"))
            elif m.state.emotions[primary].valence < 0:
                self._check_at(r, draw[0], "pull_back", draw[1], side)
        # obstruction: something in her way
        if (draw := fire(0.15, 0.55)) is not None:
            worst = max(negative.values(), default=0.0)
            if fx.hit >= 0.2 or worst >= 0.2:
                size = 1.0 + 0.4 * _clamp((max(fx.hit, worst) - 0.2) / 0.6)
                self._check_at(r, draw[0], "frown", draw[1] * size, side)
        # coping: can she handle it
        if (draw := fire(0.35, 1.05)) is not None:
            if composure >= 0.7 and lead in ("contempt", "anger"):
                self._check_at(r, draw[0], "press", draw[1], side)
            elif composure < 0.4 or primary in ("sadness", "shame", "fear", "anxiety"):
                self._check_at(r, draw[0], "cant_handle", draw[1], side)
        # agency: whose fault
        if (draw := fire(0.65, 1.0)) is not None:
            if lead in ("contempt", "anger") or a.praise < 0:
                self._check_at(r, draw[0], "blame_them", draw[1], side)
            elif lead in ("guilt", "shame", "embarrassment") or fx.reception == "flop":
                length = rng.uniform(0.8, 1.2)
                r.blame_until = draw[0] + length
                r.timeline.at(draw[0], self._blame_self, r, side * 14.0, length)

    def _check_at(self, r: _Reading, at: float, name: str, size: float, side: float, joyful: bool = False) -> None:
        r.timeline.at(at, self._play_check, r, name, size, side, joyful)

    def _play_check(self, r: _Reading, name: str, size: float, side: float, joyful: bool) -> None:
        if r.hidden and r.cover_started:
            return
        steps = self._perf_steps(self.faces.check(name, size=size, joyful=joyful, side=side), 0.0)
        if not self._can_move_gaze():
            steps = [s for s in steps if not (s.cmd is not None and s.cmd["cmd"] == "look") and s.hold is None]
        self._run(steps, self._now(), r.timeline)

    def _blame_self(self, r: _Reading, yaw: float, length: float) -> None:
        if (r.hidden and r.cover_started) or not self._can_move_gaze():
            return
        self._run([Step(0.0, _toward(yaw, 12.0), hold=length), Step(length, _look("camera"))], self._now(),
                  r.timeline)

    def _start_cover(self, r: _Reading) -> None:
        """The face she chooses goes on, held until her line takes over (display/face, open)."""
        if r.cover_started or not r.cover or self._read is not r or r.answering:
            return
        r.cover_started = True
        perf = self.faces.put_on(r.cover, energy=self.energy, intensity=r.cover_intensity, hold=-1, max_hold=10.0)
        self._put_on_now(perf, r.cover, ("put_on", r.cover))

    def _put_on_now(self, perf: Performance, name: str, lane: tuple[str, str] | None) -> None:
        self._run(self._perf_steps(perf, 0.0, lane=lane) + [Step(0.0, fn=lambda: self._held(perf))], self._now(),
                  self._read.timeline if self._read is not None else self._ticks)

    def _understanding_leak(self, r: _Reading) -> None:
        if r.cover_started or self._read is not r:
            return
        steps = self._leak_steps("understanding", face_held=False, cover=lambda: self._start_cover(r),
                                 cover_planned=bool(r.cover))
        if steps:
            self._run(steps, self._now(), r.timeline)

    def _realize(self, at: float) -> None:
        """She gets the joke, late: the realize face (the display playing now), then the amusement it brings."""
        perf = self.faces.felt("realize", 0.9)
        steps = self._perf_steps(perf, 0.0)
        release = next(c["release"] for c in perf.commands if c["cmd"] == "face_layer")
        now = self._now()
        self._felt = _Current("amusement", "bright", "self", now, now + perf.peak_at, now + perf.ends_at)
        self._felt_held = False

        def amused() -> None:
            e = self.mind.state.emotions["amusement"]
            shown = self._felt_plan("amusement", _clamp(0.35 + 0.8 * 0.3 + 0.3 * e.target), 0.3,
                                    self._roll("body"), None)
            if shown is not None and shown.shown:
                self._show(shown, self._now(), self._ticks)

        steps.append(Step(max(0.0, perf.ends_at - release), fn=amused))
        self._run(steps, self._now(), self._ticks)

    def _compose(self, r: _Reading) -> None:
        """Composing her answer until her first word (§3.4 step 14). The first matching rule wins."""
        if self._read is not r or r.answering or r.composed:
            return
        if not self._can_move_gaze(over_soft=True):  # a directed look holds her gaze: compose when it lets go
            r.timeline.at(self._gaze_free_at(over_soft=True) + 0.05, self._compose, r)
            return
        r.composed = True
        m, rd, rng = self.mind, r.reading, r.rng
        a, cp = rd.appraisal, rd.coping
        side = self._side(rng)
        now = self._now()
        steps: list[Step] = []
        nudges = True
        if cp.move == "honest":
            nudges = False
            steps.append(Step(0.0, _look("camera")))
        elif m.rung == "overwhelmed" or cp.pause > 0.0 or cp.rung == "crack":
            nudges = False
            if cp.rung != "crack":  # the crack's own look down is already playing
                steps.append(Step(0.0, _toward(side * rng.uniform(4.0, 10.0), rng.uniform(14.0, 20.0))))
            until = cp.pause + 1.0 if cp.pause > 0.0 else 3.0
            steps.append(Step(0.0, {"cmd": "body_ramp", "param": "sway", "value": 0.3, "seconds": 0.5,
                                    "back_after": round(until, 2)}, lane=("hesitation", "quiet")))
        elif m.rung == "strained" and cp.move in DODGE_COMPOSE:
            yaw, pitch = side * rng.uniform(10.0, 20.0), rng.uniform(8.0, 14.0)
            steps += [Step(0.0, _toward(yaw, pitch)),
                      Step(0.0, _face("felt", "think", {"MTH_Small": 0.3}, attack=0.5, hold=-1, release=1.2,
                                      max_hold=20.0))]
            steps += self._backstage(yaw, pitch, 1.0)
        elif a.topic in ("philosophy", "mind", "math", "physics") or a.contradicts != "none":
            yaw, pitch = side * rng.uniform(12.0, 24.0), -rng.uniform(8.0, 16.0)
            steps.append(Step(0.0, _toward(yaw, pitch)))
            steps += self._perf_steps(self.faces.felt("thinking", 0.9, max_hold=20.0, side=side), 0.0)
            steps += self._backstage(yaw, pitch, 1.0)
        elif r.text.rstrip().endswith("?") and a.topic in ("common_sense", "music", "food", "games", "stream"):
            yaw, pitch = side * rng.uniform(12.0, 24.0), -rng.uniform(8.0, 16.0)
            steps.append(Step(0.0, _toward(yaw, pitch)))
            steps += self._backstage(yaw, pitch, 1.0)
        else:
            steps.append(Step(0.0, _look("camera")))
            steps += self._maybe_double_take(rng)
        self._run(steps, now, r.timeline)
        if nudges:
            self._begin(self._nudges)

    async def _nudges(self) -> None:
        """Small shifts of her gaze while she thinks of her answer."""
        while True:
            await asyncio.sleep(self.rng.uniform(1.0, 2.2))
            if self._can_move_gaze():
                self.cmd("nudge", yaw=round(self.rng.uniform(-3.0, 3.0), 1), pitch=round(self.rng.uniform(-2.0, 2.0), 1))

    def _wrap_reading(self, r: _Reading) -> None:
        """A message she won't answer (the appraisal failed, or the reply came out empty): her eyes come back
        after reading, and idle takes over."""
        if r.wrapped:
            return
        r.wrapped = True
        at = max(self._now(), r.t_end + 0.3 if r.started else self._now())

        def done() -> None:
            if self._read is r:
                self._read = None
            if self._prepared is not None and self._prepared.reading is r:  # her reply never came
                self._prepared = None
            self._stop_motion()
            self.look("camera")
            self._face_end("felt", "think", 1.2)
            if self._face is not None and self._face.open:
                self._release_face(0.3)
            self._idle_tl.at(self._now() + self.rng.uniform(1.0, 2.0), self._begin_idle)

        r.timeline.at(at, done)

    def _crack_steps(self, t_c: float, freeze: float, rng: random.Random, side: float, warm: bool) -> list[Step]:
        """The crack on the body (§3.9): freeze and hollow eyes, then the leak phase (wound k 0.7), then a
        visible re-mask with a shaky exhale. Without a mind (the debug dropdown) it plays the sad smile."""
        steps = [Step(t_c, {"cmd": "freeze", "seconds": round(max(0.4, freeze), 2),
                            "breath": round(min(2.0, max(0.6, freeze + 0.3)), 2), "double_blink": False, "exhale": 0.5},
                      lane=("freeze", f"crack {max(0.4, freeze):.2f} s"))]
        steps += [st for st in self._perf_steps(self.faces.felt("hollow", 1.0, hold=0.4, side=side), t_c)
                  if not (st.cmd is not None and st.cmd["cmd"] == "freeze")]
        if warm:
            perf = self.faces.felt("sad smile", 0.9, eyes=True, side=side)
        else:
            e = self.mind.state.emotions
            wound = max(WOUND_FEELINGS, key=lambda n: e[n].wound_part())
            perf = self.faces.felt(wound, 0.7, side=side)
        steps += [st for st in self._perf_steps(perf, t_c + 0.4, lane=("leak", "crack"))  # the crack owns her gaze
                  if not (st.cmd is not None and st.cmd["cmd"] == "look") and st.hold is None]
        steps.append(Step(t_c + 0.4, _toward(side * rng.uniform(10.0, 16.0), rng.uniform(14.0, 20.0)), hold=2.6))
        mask = self.faces.put_on("deadpan", energy=self.energy, intensity=0.7, hold=-1, max_hold=10.0, side=side)
        self._retime(mask, attack=1.0)
        steps += self._perf_steps(mask, t_c + 3.0, lane=("squelch", "re-mask"))
        steps.append(Step(t_c + 3.0, fn=lambda: self._held(mask)))
        steps.append(Step(t_c + 3.0, {"cmd": "face_end", "layer": "felt", "slot": "felt", "fade": 0.8}))
        steps.append(Step(t_c + 3.1, _gesture("shaky_exhale", 0.6)))
        steps.append(Step(t_c + 3.0, _look("camera")))
        return steps

    def _tender(self, name: str, reading) -> bool:
        """Warmth plays as the tender face for someone she likes, or someone vulnerable (row 14)."""
        m = self.mind
        target = m.state.emotions[name].top_source().partition("|")[2]
        person = m.state.people.get(target)
        vulnerable = (person is not None and person.sorry_until > m.now) or (
            reading is not None and reading.appraisal is not None
            and (reading.appraisal.distress or reading.appraisal.sincere_need))
        return (person is not None and person.liking >= LIKES) or vulnerable

    def _wound_caused(self, name: str) -> bool:
        e = self.mind.state.emotions[name]
        return e.target > 0.0 and e.wound_part() >= 0.5 * e.target

    # --- felt displays (§3.5) ---------------------------------------------------------------

    def _felt_plan(self, name: str, peak: float, rise: float, rng: random.Random, r: _Reading | None) -> _Shown | None:
        """How one felt display plays: the body-side display rules first, then shown (k ≥ 0.5) or hidden.
        None: nothing plays at all (relief below 0.2)."""
        m = self.mind
        e = m.state.emotions[name]
        source = e.top_source()
        cause, _, target = source.partition("|")
        view = m.view()
        k = view[name]["k"]
        now = self._now()
        reading = r.reading if r is not None else None
        side = self._side(rng)

        def show(perf: Performance, face: str, **extra) -> _Shown:
            first = next(c for c in perf.commands if c["cmd"] == "face_layer")
            hold_end = first["dt"] + first["attack"] + max(first["hold"], 0.0)
            return _Shown(name, self._perf_steps(perf, 0.0), face=face, peak_at=perf.peak_at, ends_at=perf.ends_at,
                          hold_end=hold_end, **extra)

        if name == "surprise":
            return show(self.faces.felt("surprise", _shown(peak), side=side), "surprise")
        if name == "embarrassment":  # NEUTRALIZE fails by design: the pressed smile is the display
            return show(self.faces.felt("embarrassment", _shown(peak), side=side), "embarrassment")
        if name in ("relief", "amusement") and now - self._startle_at <= 10.0:  # the relief laugh after a scare
            relief = self.faces.felt("relief", _shown(peak), side=side)
            laugh = self.faces.laugh("laugh", 0.8, felt=True)
            steps = self._perf_steps(relief, 0.0) + self._perf_steps(laugh, 0.6)
            steps.append(Step(0.6, _gesture("laugh", 0.8, 0.8)))
            return _Shown(name, steps, face="relief laugh", peak_at=relief.peak_at, ends_at=max(relief.ends_at, 1.8),
                          claims=(("relief", 6.0), ("amusement", 6.0)))
        if name == "fear" and cause == "fiction":  # INTENSIFY, and the camera startles
            perf = self.faces.felt("fear", _shown(peak * 1.2), side=side)
            out = show(perf, "fear")
            strong = e.target >= 0.5
            out.steps.append(Step(0.0, fn=lambda: self._startled(strong)))
            return out
        if name == "sadness" and cause == "news":  # the concern face, fully open, no sighs
            return show(self.faces.felt("concern", _shown(peak * min(k, 1.3)), side=side), "concern")
        if name == "warmth":
            if self._tender(name, reading):
                return show(self.faces.felt("warmth", _shown(peak * 0.8), side=side), "warmth", push=True)
            return show(self.faces.felt("warmth", _shown(peak * 0.5), head_intensity=_shown(peak * 0.8), side=side),
                        "warmth")
        if name == "joy" and e.target >= 0.6 and cause == "news":  # the breakthrough, then the catch
            full = _shown(peak)
            burst = rng.uniform(1.0, 2.0)
            first = self.faces.felt("joy", full, hold=burst, side=side)
            attack = next(c["attack"] for c in first.commands if c["cmd"] == "face_layer")
            catch_at = attack + burst
            rest = max(0.5, rng.uniform(2.0, 4.0) - burst)
            steps = self._perf_steps(first, 0.0) + [
                Step(0.0, fn=self._happy_voice),
                Step(catch_at, _face("leak", "leak", {"MTH_Small": 0.35}, attack=0.07, hold=0.4, release=0.2)),
                Step(catch_at, _look("chat"), hold=0.6), Step(catch_at + 0.6, _look("camera"))]
            steps += self._perf_steps(self.faces.felt("joy", 0.7 * full, hold=rest, side=side), catch_at + 0.4)
            return _Shown(name, steps, face="joy", peak_at=first.peak_at, ends_at=catch_at + 0.4 + rest + 1.5, joy=True)
        if name == "contempt" and cause == "standard":  # row 7: the playful skeptical face, not a sneer
            if reading is not None and reading.effects.peace_again:
                perf = self.faces.felt("contempt", 0.55, side=side)
                out = show(perf, "contempt")
                length = rng.uniform(1.0, 1.6)
                out.steps += [Step(0.2, _toward(side * rng.uniform(15.0, 25.0), rng.uniform(4.0, 8.0)), hold=length),
                              Step(0.2 + length, _look("camera"))]
                return out
            return _Shown(name, [], shown=False, cover="skeptical", cover_intensity=1.0,
                          cover_delay=rng.uniform(0.3, 0.6))
        if name == "contempt" and k > 1.0:  # row 6: snaps on, holds 50% longer
            return show(self.faces.felt("contempt", _shown(peak * min(k, 1.3)), deliberate=True,
                                        side=side), "contempt")
        if name == "irritation" and k == 0.0:  # row 9: a bored or deadpan face instead
            return _Shown(name, [], shown=False, cover=rng.choice(("bored", "deadpan")), cover_intensity=0.8)
        if name == "envy" and k == 0.0 and view[name]["rule"] == "neutralize":  # row 3: she over-asks instead
            return show(self.faces.felt("interest", _shown(0.6), side=side), "interest")
        if name == "relief" and rise < 0.2:
            return None
        if name == "amusement" and source == "self" and m.now - m.last_spoke_at >= 15.0:  # duping delight
            return show(self.faces.felt("suppressed smile", _shown(peak), side=side), "suppressed smile")
        if k < 0.5:
            hide = RUNG[m.display_rung()] < 0.3 and view[name]["shown"] > 0.5
            return _Shown(name, self._hide_steps(rng, side) if hide else [], shown=False)
        positive = max((n for n in view if m.state.emotions[n].valence > 0), key=lambda n: view[n]["shown"])
        negative = max((n for n in view if m.state.emotions[n].valence < 0), key=lambda n: view[n]["shown"])
        if view[positive]["shown"] >= 0.25 and view[negative]["shown"] >= 0.25 and name in (positive, negative):
            perf = self.faces.blend(negative, min(1.0, _shown(0.35 + 0.8 * view[negative]["shown"])), positive,
                                    min(1.0, _shown(0.35 + 0.8 * view[positive]["shown"])), side=side)
            return show(perf, perf.name, push=name == "guilt")
        intensity = _shown(peak * min(k, 1.3))
        if name == "amusement" and peak * min(k, 1.3) < AMUSED_LAUGH:  # a laugh only from a real laugh's peak
            intensity = min(intensity, AMUSED_LAUGH - 0.01)
        return show(self.faces.felt(name, intensity, side=side), name, push=name == "guilt", joy=name == "joy")

    def _hide_steps(self, rng: random.Random, side: float) -> list[Step]:
        """When control fails, she turns away instead of showing it, then comes back."""
        length = rng.uniform(2.0, 4.0)
        return [Step(0.0, {"cmd": "head_pose", "pitch": round(rng.uniform(8.0, 12.0), 1),
                           "yaw": round(side * rng.uniform(15.0, 25.0), 1), "roll": 0.0, "hold": round(length, 2),
                           "attack": 0.5, "release": 0.8, "slot": "hide"}),
                Step(0.0, _toward(side * rng.uniform(15.0, 25.0), rng.uniform(12.0, 18.0)), hold=length),
                Step(length, _look("camera"))]

    def _show(self, shown: _Shown, at: float, timeline: Timeline) -> None:
        """Play a felt display at `at` (loop time) and note it for the arbitration."""
        m = self.mind
        source = m.state.emotions[shown.emotion].top_source()
        self._felt = _Current(shown.emotion, FAMILY[shown.emotion], source, at, at + shown.peak_at, at + shown.ends_at,
                              shown.face, self._lasting(shown.steps))
        self._felt_held = False  # it takes over felt/felt from a display held through her line
        self._played[(shown.emotion, source)] = at
        for name, seconds in shown.claims:
            self._claim(name, at, at + seconds)
        steps = list(shown.steps) + [Step(0.0, lane=("felt", shown.face or shown.emotion))]
        if shown.joy or shown.emotion == "joy":
            steps.append(Step(0.0, fn=self._joy_shown))
        if shown.push and not self._honest:
            steps += [self._camera_step(c, 0.0) for c in self.camera.push(at)]
        self._run(steps, at, timeline)

    def felt_display(self, name: str, peak: float, rise: float) -> None:
        """A short display the mind says is due now (live loop, from mind.phasic()). Calls from one tick are
        arbitrated together: one display at a time (§3.5)."""
        self._need_mind()
        self._batch.append((name, peak, rise))
        if len(self._batch) == 1:
            asyncio.get_running_loop().call_soon(self._arbitrate)

    def _arbitrate(self) -> None:
        batch, self._batch = self._batch, []
        now = self._now()
        m = self.mind
        survivors = []
        for name, peak, rise in batch:
            frm, until = self._claims.get(name, (math.inf, -math.inf))
            if frm <= now <= until:
                continue
            source = m.state.emotions[name].top_source()
            if now - self._played.get((name, source), -math.inf) < 60.0 and rise < 0.3:
                continue
            cur = self._felt
            relief_laugh = name in ("relief", "amusement") and now - self._startle_at <= 10.0
            if (cur is not None and now < cur.ends and not relief_laugh
                    and not (FAMILY[name] != cur.family and rise >= 0.25 and now >= cur.peak)):
                continue
            survivors.append((rise, name, peak))
        if not survivors:
            return
        rise, name, peak = max(survivors)
        if self._speaking:  # it waits for a pause in her line or the end of it
            if self._queued is None or rise > self._queued[2]:
                self._queued = (name, peak, rise, now)
            return
        self._tick += 1
        self._play_tick(name, peak, rise, self._roll("body", f"{m.seq}.{self._tick}"), now, self._ticks)

    def _play_tick(self, name: str, peak: float, rise: float, rng: random.Random, at: float,
                   timeline: Timeline) -> None:
        shown = self._felt_plan(name, peak, rise, rng, None)
        if shown is None:
            return
        if shown.shown:
            self._show(shown, at, timeline)
        elif shown.cover and (self._face is None or not self._face.open):  # row 9's substitute
            perf = self.faces.put_on(shown.cover, energy=self.energy, intensity=shown.cover_intensity)
            self._run(self._perf_steps(perf, 0.0, lane=("put_on", shown.cover)) + [Step(0.0, fn=lambda: self._held(perf))],
                      at, timeline)
        elif shown.steps:  # hiding by turning away
            self._run(shown.steps, at, timeline)

    def _queued_steps(self, at: float) -> list[Step]:
        """The tick display that waited for a pause in her line, if it's still fresh (4 s)."""
        if self._queued is None:
            return []
        name, peak, rise, queued_at = self._queued
        self._queued = None
        if self._now() - queued_at > 4.0:
            return []
        self._tick += 1
        shown = self._felt_plan(name, peak, rise, self._roll("body", f"{self.mind.seq}.{self._tick}"), None)
        if shown is None or not shown.shown:
            return []
        steps = [_shift(s, at) for s in shown.steps]
        steps.append(Step(at, lane=("felt", shown.face or shown.emotion)))
        steps.append(Step(at, fn=lambda: self._shown_now(shown)))
        return steps

    def _shown_now(self, shown: _Shown) -> None:
        now = self._now()
        source = self.mind.state.emotions[shown.emotion].top_source()
        self._felt = _Current(shown.emotion, FAMILY[shown.emotion], source, now, now + shown.peak_at, now + shown.ends_at,
                              shown.face, self._lasting(shown.steps))
        self._felt_held = False  # a display in a pause of her line takes over from the one held through it
        self._played[(shown.emotion, source)] = now
        if shown.joy or shown.emotion == "joy":
            self._joy_shown()
        if shown.push and not self._honest:
            for c in self.camera.push(now):
                self._send_cmd(c)

    def _claim(self, name: str, frm: float, until: float) -> None:
        old = self._claims.get(name)
        if old is not None and old[1] >= frm:
            frm, until = min(old[0], frm), max(old[1], until)
        self._claims[name] = (frm, until)

    def _joy_shown(self) -> None:
        self._joy_at = self._now()

    def _happy_voice(self) -> None:
        self._happy_due = True

    def _startled(self, strong: bool) -> None:
        now = self._now()
        self._startle_at = now
        if strong:
            self._fear_at = now
        self._run([self._camera_step(c, 0.0) for c in self.camera.startle(now)], now, self._ticks)

    # --- leaks (§3.8) ---------------------------------------------------------------------------

    def _leak_steps(self, window: str, *, face_held: bool, cover: Callable[[], None] | None = None,
                    cover_planned: bool = False, forced: tuple[str, float] | None = None) -> list[Step] | None:
        """One leak window: maybe a short pulse of what she hides, then the squelch. Steps are relative to the
        window. forced: (emotion, gap) instead of the mind's candidate (the judging reply's sadness)."""
        m = self.mind
        if m is None or self._honest or self._now() < self._leaks_off_until:
            return None
        now = self._now()
        if forced is None:
            name, gap = m.leak()[:2]
            if name not in LEAKS or gap <= 0.1:
                return None
            if name == "pride" and window != "after":
                return None
            if now - self._leaked.get(name, -math.inf) < 20.0:
                return None
            p = _clamp(1.2 * (gap - 0.1) * (1.5 - REGION[name]), 0.0, 0.85) * LEAK_WINDOWS[window]
            if now - self._last_leak < 8.0:
                p *= 0.5
            rng = self._roll(f"leak:{window}")
            if rng.random() >= min(p, 0.85):
                return None
        else:
            (name, gap), rng = forced, self._roll(f"leak:{window}")
        self._leaked[name] = self._last_leak = now
        perf = self.faces.leak(name, gap)
        steps = self._perf_steps(perf, 0.0, lane=("leak", name), tag="leak")
        at = perf.peak_at + rng.uniform(0.05, 0.15)
        rung_ok = m.rung in ("composed", "strained")
        if window == "understanding" and cover_planned:
            steps.append(Step(at, fn=cover, lane=("squelch", "cover"), tag="leak"))
        elif not face_held and rung_ok and rng.random() < 0.4:
            steps += self._perf_steps(self.faces.social("qualify"), at, lane=("squelch", "qualify"), tag="leak")
        return steps

    def _backstage(self, yaw: float, pitch: float, length: float, at: float = 0.0) -> list[Step]:
        """A look away of 15° or more for 0.8 s or more, outside speech: one leak window, 0.3-0.6 s in."""
        if math.hypot(yaw, pitch) < 15.0 or length < 0.8 or self.mind is None:
            return []
        return [Step(at + self.rng.uniform(0.3, 0.6), fn=self._backstage_now)]

    def _backstage_now(self) -> None:
        if self._speaking:
            return
        steps = self._leak_steps("backstage", face_held=self._face is not None and self._face.open)
        if steps:
            self._run(steps, self._now(), self._ticks)

    # --- speaking (§3.6) ---------------------------------------------------------------------

    def speaking_first(self, coping) -> None:
        """She fills the dead air (Server.initiative): a glance at chat first, and with a thought pending a
        short look to her favorite side before it."""
        self._need_mind()
        self._stop_motion()
        self._after.cancel()
        self._idle_tl.cancel()
        seq = self.mind.seq
        self._prepared = _Reply("first", seq, coping)
        self._voice_first = True
        self._joke_claim(coping)
        rng = self._roll("body", seq)
        t, steps = 0.0, []
        if coping.move == "bring_up":
            length = rng.uniform(0.5, 0.9)
            steps.append(Step(0.0, _toward(self._favorite_side * rng.uniform(12.0, 20.0), rng.uniform(-6.0, 4.0)),
                              hold=length))
            t = length
        length = rng.uniform(1.0, 1.5)
        steps += [Step(t, _look("chat", (rng.uniform(-2.0, 6.0), rng.uniform(0.0, 3.0))), hold=length),
                  Step(t + length, _look("camera"))]
        self._run(steps, self._now(), self._idle_tl)

    async def speech_gate(self) -> None:
        """Before her first sound (speak_forever): wait for the freeze to end, for the crack's minimum, for
        her to have understood the message, for her felt reaction to have started (FELT_LEAD), and for a
        hesitation when she's of two minds (§3.4 step 15)."""
        reply = self._prepared
        r = reply.reading if reply is not None else None
        if r is None:
            return
        stopped = self._stopped
        await self._wait(r.ready.wait(), stopped)
        if stopped.is_set() or r.reading is None or r.reading.error:
            return
        rd = r.reading
        a, fx, cp = rd.appraisal, rd.effects, rd.coping
        rng = self._roll("body", r.seq)
        now = self._now()
        extra, steps = 0.0, []
        side = self._side(rng)
        r15 = self.mind.persona["r15"]
        if fx.mixed >= r15["hesitate"]:
            extra = r15["pause_base"] + r15["pause_mixed"] * fx.mixed
            steps.append(Step(0.0, {"cmd": "hold_breath", "seconds": round(extra, 2)}, lane=("hesitation", "mixed")))
            if self._can_move_gaze(over_soft=True):
                steps += [Step(0.0, _toward(side * rng.uniform(10.0, 15.0), rng.uniform(-2.0, 4.0)), hold=0.6 * extra),
                          Step(0.6 * extra, _look("camera"))]
        elif a.topic == "mind":
            extra = 0.3
            if self._can_move_gaze(over_soft=True):
                steps += [Step(0.0, _toward(side * rng.uniform(10.0, 15.0), rng.uniform(-4.0, 4.0)), hold=0.3),
                          Step(0.3, _look("camera"))]
        elif cp.move == "answer_fast":
            extra = rng.uniform(0.3, 0.5)
        self._run(steps, now, r.timeline)
        until = max(r.freeze_end, r.t_c, r.t_end, r.words_at, r.felt_lead, now + extra)
        if until > now:
            await self._wait(asyncio.sleep(until - now), stopped)

    def voice_text(self, plan: SentencePlan, index: int) -> str:
        """The text her voice says for clip `index`: the engine's [fear] or [happy] goes on the first spoken
        sentence of a reply when it's due (never from the actor, never for hidden feelings)."""
        if not self._voice_first or self._prepared is None:
            return plan.text
        self._voice_first = False
        if self._now() - self._fear_at <= 5.0:
            _LOGGER.info("  voice: [fear] (a horror startle)")
            return "[fear] " + plan.text
        if self._happy_due:
            self._happy_due = False
            _LOGGER.info("  voice: [happy] (joy for someone breaks through)")
            return "[happy] " + plan.text
        return plan.text

    def reply_starting(self) -> None:
        """The first clip of a reply is on its way: the thinking face lets go on its own time, the composing
        nudges stop, the reading's looks are done. The cover stays."""
        r = self._read
        if r is not None and not r.pending:
            r.answering = True
            r.timeline.cancel(keep=lambda when, tag: tag != "gaze")
        self._stop_motion()
        self._face_end("felt", "think", self.rng.uniform(1.2, 1.4))

    def _reply_for(self, utterance: int, index: int) -> _Reply:
        reply = self._replies.get(utterance)
        if reply is None:
            reply = self._prepared
            self._prepared = None
            if reply is None:  # a line to say as written (no message, no mind)
                self._events += 1
                reply = _Reply("say", self.mind.seq if self.mind is not None else self._events)
            reply.utterance = utterance
            self._replies[utterance] = reply
            for old in sorted(self._replies)[:-4]:
                del self._replies[old]
            self._setup_reply(reply)
        return reply

    def _setup_reply(self, reply: _Reply) -> None:
        """What the move sits as in her body for the whole reply: the stance, a denial, a joke."""
        cp = reply.coping
        if cp is None:
            return
        rng = self._roll("body", reply.seq)
        move = cp.move
        reply.joke = self._joke_claim(cp)
        topic = reply.reading.reading.appraisal.topic if reply.reading is not None else ""
        if move in STUBBORN_MOVES:
            reply.stance = "stubborn"
        elif move == "answer_fast":
            reply.stance = "math"
        elif move in ("explain", "argue_abstract") and topic in ("philosophy", "mind"):
            reply.stance = "philosophy"
        reminder = reply.reading.reading.effects.reminder if reply.reading is not None else 0.0
        if move in DENIAL_MOVES and reminder >= 0.25 and rng.random() < 0.6:
            reply.denial = True
            reply.denial_gaze = rng.uniform(2.0, 4.0)

    def sentence_commands(self, plan: SentencePlan, analysis: Analysis, utterance: int, index: int) -> list[dict]:
        """Everything the body does during this sentence, timed to its audio."""
        reply = self._reply_for(utterance, index)
        key = (utterance, index)
        rng = self._roll("body", reply.seq)
        duration = analysis.duration
        if index == 0:
            self._cover_carries(reply)
        self._boost = 0.35 if any(t.name == "dramatic" for t in plan.tags) else 0.0
        steps: list[Step] = []
        busy: list[tuple[float, float]] = []
        no_beats: list[tuple[float, float]] = []
        sounds = iter(analysis.sounds or [])
        if index == 0:
            steps += self._hold_felt(reply)
        if reply.face_open and reply.face_moves_head:  # the face held over from the last clip owns the head
            busy.append((0.0, duration))
        if self._felt_held and self._felt is not None and self._felt.cmd is not None and "head" in self._felt.cmd:
            busy.append((0.0, duration))  # so does the feeling held through her line
        if reply.face_open and reply.face == "deadpan":
            no_beats.append((0.0, duration))
        faces = [t for t in plan.tags if t.name in ACTOR_FACES]
        sarcastic_smug = not faces and any(t.name == "sarcastic" for t in plan.tags)
        face_times = [analysis.time_at(t.position) for t in faces]
        seen = 0
        for tag in plan.tags:
            if tag.name in SOUND_TAGS and analysis.sounds is not None:
                window = next(sounds, None)
                if window is None:
                    continue  # the voice skipped this sound: don't act it out
                t, length = window[0], window[1] - window[0]
            elif tag.name in SOUND_TAGS:
                t, length = analysis.time_at(tag.position), SOUND_LENGTH[tag.name]
            else:
                t, length = analysis.time_at(tag.position), 0.0
            if tag.name in ACTOR_FACES or (tag.name == "sarcastic" and sarcastic_smug):
                if reply.honest:
                    _LOGGER.info("  tag [%s] dropped: no put-on faces in the honest answer", tag.name)
                    continue
                name = tag.name if tag.name in ACTOR_FACES else "smug"
                intensity = tag.intensity if tag.name in ACTOR_FACES else 0.8
                nxt = face_times[seen + 1] if tag.name in ACTOR_FACES and seen + 1 < len(face_times) else math.inf
                seen += tag.name in ACTOR_FACES
                steps += self._clip_face(reply, name, intensity, t, nxt, duration, busy, no_beats)
                if tag.name == "sarcastic":
                    steps.append(Step(t, _gesture("tilt", self._side(rng) * 0.6 * self._amp(), 1.6)))
                continue
            if tag.name not in SPOKEN_TAGS and tag.name not in STAGE_TAGS:
                why = "a felt face (only her mind shows feelings)" if self.faces.kind(tag.name) else "unknown"
                _LOGGER.info("  tag [%s] dropped: %s", tag.name, why)
                continue
            shift = rng.uniform(0.3, 0.8) if t < 0.2 else 0.0  # at the very start, her eyes get there a beat in
            for s in self._tag_steps(tag.name, t, length, tag.intensity, rng, reply=reply):
                if s.cmd is not None and s.cmd["cmd"] == "look":
                    s.t += shift
                steps.append(s)
        if index == 0:
            steps += self._pre_leak(reply)
        if index == 0 and not faces and not sarcastic_smug:
            steps += self._default_face(reply, rng, duration, busy)
            steps += self._greet_back(reply, rng)
        if index == 0:
            steps += self._stance(reply, duration, rng, busy)
        if reply.denial:
            steps.append(Step(0.0, {"cmd": "body_ramp", "param": "talking_blinks_per_minute", "value": 0.21,
                                    "seconds": 0.3, "back_after": round(max(0.5, duration), 2)}))
        if reply.joke and not reply.punchline and duration >= 1.0 and self.mind is not None:
            steps += self._punchline(plan, analysis, rng)
            reply.punchline = True
        # Pauses between her sentences: leak windows; a display that waited plays at the first one.
        pauses = analysis.pauses(0.4)
        for i, (start, _) in enumerate(pauses):
            if i == 0:
                steps += self._queued_steps(start + 0.05)
            leak = self._leak_steps("pause", face_held=reply.face_open)
            if leak:
                steps += [_shift(s, start + 0.1) for s in leak]
        steps += self._talking_head(plan, analysis, busy, no_beats, reply, rng)
        steps += self._clip_end(plan, analysis, reply, rng)
        return self._to_clip(steps, key)

    def silent_commands(self, pieces: list[tuple[float, SentencePlan]], duration: float, utterance: int,
                        index: int) -> list[dict]:
        """A silent clip: a dramatic [pause] and/or faces without words ("[suspicious] [pause]"). Put-on faces
        here are held open and carry into the words after them. Sound tags need the voice: skipped."""
        reply = self._reply_for(utterance, index)
        rng = self._roll("body", reply.seq)
        if index == 0:
            self._cover_carries(reply)
        steps: list[Step] = self._hold_felt(reply) if index == 0 else []
        busy: list[tuple[float, float]] = []
        any_face = False
        faces = [(offset, t) for offset, plan in pieces for t in plan.tags if t.name in ACTOR_FACES]
        seen = 0
        for offset, plan in pieces:
            for tag in plan.tags:
                if tag.name in SOUND_TAGS:
                    continue
                if tag.name in ACTOR_FACES:
                    if reply.honest:
                        continue
                    any_face = True
                    nxt = faces[seen + 1][0] if seen + 1 < len(faces) else math.inf
                    seen += 1
                    steps += self._clip_face(reply, tag.name, tag.intensity, offset, nxt, duration, busy, [])
                elif tag.name in SPOKEN_TAGS or tag.name in STAGE_TAGS:
                    steps += self._tag_steps(tag.name, offset, max(0.0, duration - offset), tag.intensity, rng,
                                             reply=reply)
                else:
                    _LOGGER.info("  tag [%s] dropped: %s", tag.name,
                                 "a felt face (only her mind shows feelings)" if self.faces.kind(tag.name) else "unknown")
        if index == 0:
            steps += self._pre_leak(reply)
        if index == 0 and not any_face:
            steps += self._default_face(reply, rng, duration, busy)
            steps += self._greet_back(reply, rng)
        if duration >= 0.4:
            leak = self._leak_steps("pause", face_held=reply.face_open)
            if leak:
                steps += [_shift(s, 0.2) for s in leak]
        return self._to_clip(steps, (utterance, index))

    def _clip_face(self, reply: _Reply, name: str, intensity: float, t: float, nxt: float, duration: float,
                   busy: list, no_beats: list) -> list[Step]:
        """An actor's face at time t, held open until the next face tag (a crossfade at that word) or the
        after-line release (§3.6). The face she's already wearing stays on."""
        end = min(nxt, duration)
        if reply.face == name and reply.face_open:
            if reply.face_moves_head:
                busy.append((t, end))
            if name == "deadpan":
                no_beats.append((t, end))
            return []
        strained = self.mind is not None and self.mind.rung == "strained"
        perf = self.faces.put_on(name, energy=self.energy, intensity=intensity, hold=-1, max_hold=6.0, overplay=strained)
        if perf.moves_head:
            busy.append((t, end))
        if name == "deadpan":
            no_beats.append((t, end))
        reply.face, reply.face_open, reply.face_moves_head = name, True, perf.moves_head
        reply.teasing |= name == "teasing"
        return self._perf_steps(perf, t, lane=("put_on", name)) + [Step(t, fn=lambda: self._held(perf))]

    def _default_face(self, reply: _Reply, rng: random.Random, duration: float, busy: list) -> list[Step]:
        """The first clip has no face tag: the cover stays if one is held; otherwise the move's face (at the
        move's strength, with its gesture: sure of it, a smug 0.5 and a small nod), her guess's doubt on
        physics, or the brighter face while covering after a crack."""
        if reply.honest or reply.coping is None or reply.face_open:  # the cover she's wearing stays on
            return []
        cp = reply.coping
        steps: list[Step] = []
        r = reply.reading
        topic = r.reading.appraisal.topic if r is not None else ""
        name, intensity, simulate = "", 1.0, False
        if cp.face:
            name, intensity, simulate = cp.face, cp.face_strength, cp.face == "tired"
        elif topic == "physics":
            name = "unsure"
        elif self._covering():
            name, intensity = "smile", 0.6
        if not name:
            return steps
        at = rng.uniform(0.1, 0.3) + (cp.pre_leak[1] if cp.pre_leak is not None else 0.0)
        perf = self.faces.put_on(name, energy=self.energy, intensity=intensity, hold=-1, max_hold=6.0,
                                 simulate=simulate)
        if perf.moves_head:
            busy.append((at, duration))
        reply.face, reply.face_open, reply.face_moves_head = name, True, perf.moves_head
        reply.teasing |= name == "teasing"
        steps += self._perf_steps(perf, at, lane=("put_on", name)) + [Step(at, fn=lambda: self._held(perf))]
        if cp.gesture:
            steps.append(Step(at + 0.2, _gesture(cp.gesture, 0.3)))
        return steps

    def _greet_back(self, reply: _Reply, rng: random.Random) -> list[Step]:
        """Her line answers a greeting, thanks or a goodbye and no face of hers holds: the social smile goes
        with her words too, as it did when she read theirs (spec SOCIAL: every streamer does this). Without it
        she said "Welcome in, Pip" with a blank face."""
        r = reply.reading
        if self.mind is None or reply.honest or reply.face_open or r is None or r.reading is None or r.reading.error:
            return []
        a = r.reading.appraisal
        if not (a.social in ("greeting", "thanks") or a.leaving > 0):
            return []
        return self._perf_steps(self.faces.social("greet"), rng.uniform(0.1, 0.3), lane=("social", "greet back"))

    def _hold_felt(self, reply: _Reply) -> list[Step]:
        """The feeling her line answers stays on her face while she says it (faces hold while she talks): a
        sustained display (HELD_FELT, or a blend of two feelings) that is still playing as her line starts, or
        that the message she's answering brought, is held open from her first clip and lets go after her last
        word with the put-on face (§3.7), as long as she still feels it. Without this, the concern for someone's
        dead cat ended 2-5 s in and she said the rest of her condolences with a blank face. It yields like any
        felt display: a new one in felt/felt (a display in a pause, her punchline smile) takes over."""
        cur, m = self._felt, self.mind
        if (m is None or reply.honest or (reply.coping is not None and reply.coping.rung == "crack") or cur is None
                or cur.cmd is None or not (cur.face in HELD_FELT or cur.face.startswith("blend: "))
                or m.state.emotions[cur.name].value < 0.15):
            return []
        playing = self._now() < cur.ends
        r = reply.reading
        if not playing and not (r is not None and r.started and cur.started >= r.t0):
            return []  # an older display that has ended isn't what this line answers
        self._felt_held = True
        cur.ends = math.inf  # still playing, for the arbitration (§3.5)
        # Still on her face: it carries on (a short crossfade). Already gone (a slow reply): it comes back as a
        # feeling does, eased in.
        return [Step(0.0, dict(cur.cmd, hold=-1, max_hold=HELD_FELT_MAX, attack=0.4 if playing else cur.cmd["attack"]))]

    @staticmethod
    def _lasting(steps: list[Step]) -> dict | None:
        """A display's last felt/felt face_layer: the face it settles into (relief's smile, the joy after its
        catch)."""
        faces = [s.cmd for s in sorted(steps, key=lambda s: s.t) if s.cmd is not None and s.cmd["cmd"] == "face_layer"
                 and s.cmd["layer"] == "felt" and s.cmd["slot"] == "felt"]
        return dict(faces[-1]) if faces else None

    def _pre_leak(self, reply: _Reply) -> list[Step]:
        """A move that starts interested and cuts itself off shows the interest first (cut-off interest: a
        0.3 s leak before the dismissal)."""
        if reply.coping is None or reply.coping.pre_leak is None:
            return []
        emotion, seconds = reply.coping.pre_leak
        return self._perf_steps(self.faces.felt(emotion, 0.8, hold=seconds), 0.0, lane=("leak", emotion))

    def _cover_carries(self, reply: _Reply) -> None:
        """The cover put on while she read is the face her line starts with."""
        r, held = reply.reading, self._face
        if r is not None and r.cover_started and held is not None and held.open and held.until > self._now():
            reply.face, reply.face_open, reply.face_moves_head = held.name, True, held.moves_head

    def _joke_claim(self, coping) -> bool:
        """Her own joke: the real smile comes with the punchline, so the delight her self-check reports while
        the reply is on its way doesn't play as a second display. True for a joke."""
        joke = coping.move in JOKE_MOVES and not (coping.move == "comeback" and coping.shape == "stock")
        if joke and self.mind is not None:
            now = self._now()
            self._claim("amusement", now, now + 12.0)
        return joke

    def _covering(self) -> bool:
        """Covering after a crack: 2-5 minutes after it, while chat is active."""
        m = self.mind
        lo, hi = m.persona["crack"]["cover"]
        age = m.now - m.coper.crack_at
        return lo <= age <= hi and any(m.now - t < 120.0 for t, _ in m.state.writers)

    def _stance(self, reply: _Reply, duration: float, rng: random.Random, busy: list) -> list[Step]:
        """How the move sits in her body for the first sentence (§3.6)."""
        steps: list[Step] = []
        if reply.stance == "stubborn":  # chin up, a slow shake, lips pressed, gaze held, no nods
            steps += [Step(0.1, {"cmd": "head_pose", "pitch": -4.0, "yaw": 0.0, "roll": 0.0, "hold": round(duration, 2),
                                 "attack": 0.4, "release": 0.6, "slot": "stance"}),
                      Step(0.3, _gesture("shake", 0.3, 1.2)),
                      Step(0.1, _face("display", "stance", {"MTH_Small": 0.3}, attack=0.3, hold=round(duration, 2),
                                      release=0.4, curve="deliberate"))]
            busy.append((0.1, duration))
        elif reply.stance == "math":  # a quick nod, chin up
            steps += [Step(0.05, _gesture("nod", 0.35)),
                      Step(0.2, {"cmd": "head_pose", "pitch": -3.0, "yaw": 0.0, "roll": 0.0, "hold": round(duration, 2),
                                 "attack": 0.3, "release": 0.6, "slot": "stance"})]
            busy.append((0.2, duration))
        elif reply.stance == "philosophy":  # she leans in and looks up to the side to build the argument
            length = rng.uniform(0.8, 1.4)
            at = duration * rng.uniform(0.3, 0.6)
            steps += [Step(0.2, _gesture("lean_in", 0.4)),
                      Step(at, _toward(self._side(rng) * rng.uniform(12.0, 20.0), -rng.uniform(10.0, 14.0)), hold=length),
                      Step(at + length, _look("camera"))]
            steps.append(Step(0.0, fn=self._philosophy_on))
        return steps

    def _philosophy_on(self) -> None:
        self._philosophy = True
        self._set_energy()

    def _punchline(self, plan: SentencePlan, analysis: Analysis, rng: random.Random) -> list[Step]:
        """Her own joke: a real smile starts 0.4 s before the punchline (speakers laugh first)."""
        spoken = plan.spoken or " "
        breaks = [analysis.time_at(m.end() / len(spoken)) for m in _PHRASE_END.finditer(spoken)]
        breaks = [b for b in breaks if b < analysis.duration - 0.2]
        start = breaks[-1] if breaks else analysis.duration / 2.0
        at = max(0.0, start - 0.4)
        perf = self.faces.felt("amusement", rng.uniform(0.55, 0.7))

        def claim() -> None:
            now = self._now()
            self._claim("amusement", now, now + 8.0)
            self._felt = _Current("amusement", "bright", "self", now, now + perf.peak_at, now + perf.ends_at)
            self._felt_held = False  # her punchline smile takes over felt/felt

        return self._perf_steps(perf, at, lane=("felt", "amusement")) + [Step(at, fn=claim)]

    def _tag_steps(self, tag: str, t: float, length: float, intensity: float, rng: random.Random, *,
                   reply: _Reply | None = None, mind_free: bool = False) -> list[Step]:
        """A sound, delivery or stage tag at time t (§3.6). Sounds play their sound's gesture, and a face
        only as listed; the felt ones come from her mind."""
        m = None if mind_free else self.mind
        amp = self._amp() * intensity
        side = self._side(rng)
        out: list[Step] = []
        match tag:
            case "laugh" | "chuckle":
                felt = m is not None and m.state.emotions["amusement"].value >= 0.4
                out += self._perf_steps(self.faces.laugh(tag, length, felt=felt), t)
                out.append(Step(t, _gesture(tag, amp, length if length > 0.3 else None)))
            case "sigh":
                out += [Step(t, _gesture("sigh", amp)), Step(t, self._gaze_cmd("down", rng), hold=max(length, 0.8))]
                perf = self.faces.put_on("tired", energy=self.energy, intensity=0.6, hold=length)
                out += self._perf_steps(perf, t) + [Step(t, fn=lambda: self._held(perf))]
            case "gasp":
                out += [Step(t, _gesture("gasp", amp)), Step(t, _look("camera"), hold=max(length, 0.8))]
                if m is not None and max(m.state.emotions["surprise"].value, m.state.emotions["fear"].value) >= 0.3:
                    out += [st for st in self._perf_steps(self.faces.felt("surprise", 0.7), t, lane=("felt", "surprise"))
                            if not (st.cmd is not None and st.cmd["cmd"] == "gesture" and st.cmd["name"] == "gasp")]
            case "cough":
                out += [Step(t, _gesture("cough", amp)), Step(t, self._gaze_cmd("away", rng), hold=max(length, 0.8))]
            case "clear throat":
                out += [Step(t, _gesture("nod", 0.4)), Step(t, self._gaze_cmd("down", rng), hold=max(length, 0.8))]
            case "groan":
                out.append(Step(t, _gesture("head_back", amp)))
                perf = self.faces.put_on("annoyed", energy=self.energy, hold=length + 0.3)
                out += self._perf_steps(perf, t) + [Step(t, fn=lambda: self._held(perf))]
            case "sniff":
                out.append(Step(t, _gesture("sniff", amp)))
            case "shush":
                out += [Step(t, _gesture("lean_in", amp)), Step(t, _look("camera"), hold=0.8)]
            case "crying":
                out.append(Step(t, self._gaze_cmd("down", rng), hold=max(length, 0.8)))
            case "sarcastic":
                out.append(Step(t, _gesture("tilt", side * 0.6 * amp, 1.6)))
            case "whispering":
                out += [Step(t, _gesture("lean_in", amp)), Step(t, _look("camera"), hold=0.8)]
            case "narration" | "advertisement":
                out.append(Step(t, _look("camera"), hold=0.8))
            case "dramatic" | "happy" | "angry" | "surprised" | "fear":
                pass  # voice only (dramatic also boosts this sentence's gestures)
            case "wink":
                out += self._wink(t, rng, side)
                perf = self.faces.put_on("smile", energy=self.energy, intensity=0.6, hold=0.8)
                out += self._perf_steps(perf, t) + [Step(t, fn=lambda: self._held(perf))]
                if reply is not None:
                    reply.face, reply.face_open = "smile", False
            case "nod" | "shake head" | "tilt head" | "shrug":
                g = STAGE_GESTURES[tag]
                out.append(Step(t, _gesture(g, amp * (side if g in SIDE_GESTURES else 1.0))))
            case "look away" | "look down" | "look at chat" | "look at camera":
                out.append(Step(t, self._gaze_cmd(STAGE_GAZES[tag], rng), hold=0.8))
            case _:
                raise KeyError(f"no reaction for tag {tag!r}")
        if tag in ("sigh", "groan") and reply is not None:
            reply.face, reply.face_open = ("tired" if tag == "sigh" else "annoyed"), False
        return out

    def _wink(self, t: float, rng: random.Random, side: float) -> list[Step]:
        """A wink; one in three fails (slips are seeded draws)."""
        if self._slips_ok() and rng.random() < 1.0 / 3.0:
            variant = "shut" if rng.random() < 0.5 else "squint"
            return self._perf_steps(self.faces.failed_wink(variant, side), t, lane=("slip", "wink"))
        return [Step(t, {"cmd": "wink", "side": "left" if side > 0 else "right"})]

    def _gaze_cmd(self, where: str, rng: random.Random) -> dict:
        side = self._side(rng)
        match where:
            case "chat":
                return _look("chat")
            case "down":
                return _toward(side * rng.uniform(4.0, 12.0), rng.uniform(14.0, 22.0))
            case "away":
                return _toward(side * rng.uniform(20.0, 35.0), rng.uniform(-5.0, 10.0))
            case "camera":
                return _look("camera")
        raise KeyError(where)

    def _talking_head(self, plan: SentencePlan, analysis: Analysis, busy: list[tuple[float, float]],
                      no_beats: list[tuple[float, float]], reply: _Reply, rng: random.Random) -> list[Step]:
        """Head motion while talking, from the sentence's phrasing and stress, out of the way of held faces."""
        e, amp = self.energy, self._amp()
        duration = analysis.duration
        spoken = plan.spoken or " "
        out: list[Step] = []

        def free(t: float, margin: float = 0.0) -> bool:
            return not any(a - margin <= t <= b + margin for a, b in busy)

        # 1. Each phrase gets its own head position, held until the next phrase.
        breaks = [analysis.time_at(m.end() / len(spoken)) for m in _PHRASE_END.finditer(spoken)]
        edges = [0.0] + [b for b in breaks if 0.4 < b < duration - 0.6] + [duration]
        pose = (0.0, 0.0, 0.0)
        size = _lerp(0.6, 1.2, e)
        for start, end in zip(edges, edges[1:]):
            begin = start + rng.uniform(0.05, 0.25)
            length = end - begin
            if length < 0.7 or not free(begin, 0.3):
                continue
            candidate = pose
            for _ in range(8):  # somewhere noticeably different from the last phrase
                candidate = (rng.uniform(-3, 4) * size, rng.uniform(-6, 6) * size, rng.uniform(-5, 5) * size)
                if sum((a - b) ** 2 for a, b in zip(candidate, pose)) ** 0.5 > 4.0 * size:
                    break
            pose = candidate
            out.append(Step(begin, {"cmd": "head_pose", "pitch": round(pose[0], 1), "yaw": round(pose[1], 1),
                                    "roll": round(pose[2], 1), "hold": round(max(0.2, length - 0.9), 2),
                                    "attack": 0.45, "release": 0.5}))
        # 2. "No / not / never": a small shake on the first one.
        shakes = []
        negation = _NEGATION.search(spoken)
        if negation and rng.random() < 0.7:
            t = analysis.time_at(negation.start() / len(spoken))
            if free(t):
                shakes.append(t)
                out.append(Step(t, _gesture("shake", 0.25 * amp, 0.6)))
        # 3. Stressed words: a nod, a chin lift, a little turn, a tilt, or the brows.
        last = None
        gestures: list[float] = list(shakes)
        for t, strength in analysis.beats:
            if rng.random() > _lerp(0.35, 0.7, e) or any(abs(t - s) < 0.4 for s in shakes):
                continue
            if any(a <= t <= b for a, b in no_beats):
                continue
            options = {"beat": 1.0, "lift": 0.7, "turn": 0.8, "tilt_beat": 0.6, "brows": 0.7}
            held = not free(t)
            if held:  # a face holds the head: smaller beats on top of it, no turns
                options = {"beat": 1.0, "lift": 0.5, "brows": 0.9}
            if reply.stance == "stubborn":
                options.pop("beat", None)  # she holds back nods when she disagrees
            options.pop(last, None)
            if not options:
                continue
            motion = rng.choices(list(options), weights=list(options.values()))[0]
            last = motion
            at = max(0.0, t - 0.1)
            if motion != "brows":
                sign = self._side(rng) if motion in ("turn", "tilt_beat") else 1.0
                out.append(Step(at, _gesture(motion, strength * amp * sign * (0.6 if held else 1.0))))
                gestures.append(at)
            if motion == "brows" or (strength > 0.7 and rng.random() < 0.3):
                out += self._brow_beat(reply, at, 0.6 * strength)
        # 4. A slip: a head bob that lands off the beat.
        if len(analysis.beats) >= 2 and self._now() - self._bob_at >= SLIP_EVERY and self._slips_ok() \
                and rng.random() < 0.08:
            t = rng.choice(analysis.beats)[0] + rng.uniform(0.15, 0.25)
            if t < duration and not any(abs(t - g) < 0.4 for g in gestures):
                self._bob_at = self._now()
                out.append(Step(t, _gesture("beat", 0.5), lane=("slip", "bob")))
        return out

    def _brow_beat(self, reply: _Reply, at: float, strength: float) -> list[Step]:
        """Conversational brows (display/beat): at most 0.5, at most once per 2 s across her clips."""
        if at - reply.brow_at < 2.0:
            return []
        reply.brow_at = at
        return [Step(at, _face("display", "beat", {"BRW_Surprised": round(min(0.5, strength), 2)}, attack=0.08,
                               hold=0.12, release=0.3, curve="deliberate"))]

    def _clip_end(self, plan: SentencePlan, analysis: Analysis, reply: _Reply, rng: random.Random) -> list[Step]:
        """How the sentence ends: a question hands the turn over, an exclamation lands, a statement settles."""
        amp, duration = self._amp(), analysis.duration
        end = round(max(0.0, duration - 0.4), 3)
        out: list[Step] = []
        if plan.kind == "question":
            out += [Step(end, _gesture("tilt", self._side(rng) * 0.6 * amp, 1.6)),
                    Step(end, _look("camera"), hold=1.5)]
            out += self._brow_beat(reply, end, 0.5)
        elif plan.kind == "exclamation":
            out.append(Step(end, _gesture(rng.choice(("beat", "lift")), 0.6 * amp)))
        elif rng.random() < 0.25:
            motion = rng.choice(("beat", "tilt_beat"))
            if not (motion == "beat" and reply.stance == "stubborn"):
                sign = self._side(rng) if motion == "tilt_beat" else 1.0
                out.append(Step(end, _gesture(motion, 0.4 * amp * sign)))
        out.append(Step(round(end + 0.2, 3), {"cmd": "blink_soon", "chance": 0.5}))
        reply.brow_at -= duration  # the 2 s brow rule carries over into the next clip
        return out

    # --- after her line (§3.7) -------------------------------------------------------------------

    def on_event(self, msg: dict) -> None:
        name = msg["name"]
        now = self._now()
        if name == "sentence_started":
            key = (msg["utterance"], msg["index"])
            self._gaze_holds += [(now + a, now + b, soft) for a, b, soft in self._clip_holds.pop(key, [])]
            for t, fn in self._clip_actions.pop(key, []):
                self._speech_tl.at(now + t, fn)
            reply = self._replies[msg["utterance"]]
            self._playing = reply
            if not self._speaking:
                self._speaking = True
                reply.started = now
                if self.mind is not None:
                    reply.mind_started = self.mind.now
                if reply.reading is not None and self._read is reply.reading:
                    self._read = None
                self._after.cancel()
                self._idle_tl.cancel()
                self._begin(self._talk)
        elif name == "finished":
            if not self._speaking:  # nothing was said (an empty reply)
                r = self._read
                if r is not None and not r.pending and r.reading is not None:
                    self._wrap_reading(r)
                return
            self._speaking = False
            self._after_line(now, self._playing)
            r = self._read
            if r is not None and r.pending:  # a message came while she was talking: now she reads it
                t0 = now + self.rng.uniform(0.3, 0.6)
                r.timeline.at(t0, self._start_reading, r, t0)

    def _after_line(self, t: float, reply: _Reply) -> None:
        """She hands the turn back: the put-on face lets go (a leak may slip out), then one gaze sequence."""
        self._after.cancel()
        self._stop_motion()
        tl = self._after = Timeline()
        rng = self._roll("body", reply.seq)
        m = self.mind
        side = self._side(rng)
        steps: list[Step] = []
        held = self._face is not None and self._face.open and self._face.until > t
        release = t + rng.uniform(0.5, 1.0)
        if held or self._felt_held:  # the put-on face, and the feeling held through her line, let go together
            steps.append(Step(release, fn=lambda: self._release_face(0.2), tag="release"))
            self._release_at = release
        window = _clamp(release - 0.1, t + 0.2, t + 1.2) if held else t + rng.uniform(0.2, 1.2)
        judging = reply.coping is not None and reply.coping.move in JUDGE_MOVES
        # One gaze sequence, in priority order.
        seq_end = t
        line = m.state.last_line if m is not None else {}
        bluff = (m is not None and line.get("kind") == "bluff" and line.get("at", -math.inf) >= reply.mind_started - 1.0)
        bluff_tell = False
        if reply.honest:
            gaze, seq_end = self._honest_after(rng, side)
            steps += [_shift(s, t) for s in gaze]
            seq_end += t
        elif bluff and rng.random() < 0.8:
            bluff_tell = True
            steps += [_shift(s, t) for s in self._bluff_tell(rng, side)]
            seq_end = t + 2.5
        elif reply.denial:
            steps += [_shift(s, t) for s in self._denial_tell(rng, side)]
            seq_end = t + 1.8
        elif (reply.joke or (line.get("kind") == "joke" and line.get("at", -math.inf) >= reply.mind_started - 1.0)) \
                and m is not None and rng.random() < 0.7:
            steps += [_shift(s, t) for s in self._joke_glance(rng, side)]
            seq_end = t + 1.9
            if m.joke_wait is not None:  # an absurd comeback: is anyone laughing?
                spoke_at = m.now
                steps.append(Step(t, fn=lambda: self._wait_for_laugh(t, spoke_at, rng, side)))
        else:
            steps.append(Step(t, fn=self._look_back))
        if not bluff_tell:  # the bluff's smile pressed back is this window's leak
            steps.append(Step(window, fn=lambda: self._after_leak(held, judging, rng), tag="leak"))
        if reply.teasing and rng.random() < 0.25:
            steps += self._wink(t + rng.uniform(0.1, 0.3), rng, side)
        steps += self._queued_steps(t + 0.3)
        if rng.random() < 0.3 and not (reply.stance == "stubborn" or reply.denial or reply.honest):
            steps.append(Step(t + rng.uniform(0.2, 0.6), _gesture("nod", 0.4)))
        self._next_reframe = t + rng.uniform(8.0, 20.0)
        idle_at = max(t + self._dwell(1.4, 2.9), seq_end + 0.3)
        steps.append(Step(idle_at, fn=self._after_done))
        self._run(steps, 0.0, tl)

    def _look_back(self) -> None:
        if self._can_move_gaze():
            self.look("camera")

    def _after_done(self) -> None:
        self._honest = False
        self._begin(self._idle)

    def _after_leak(self, held: bool, judging: bool, rng: random.Random) -> None:
        steps = None
        if judging and not self._honest and rng.random() < 0.35:  # what she judged in them is what she can't have
            steps = self._leak_steps("after", face_held=held, forced=("sadness", 0.9))
        if steps is None:
            steps = self._leak_steps("after", face_held=held)
        if steps:
            self._run(steps, self._now(), self._after)

    def _honest_after(self, rng: random.Random, side: float) -> tuple[list[Step], float]:
        """After the honest answer: a look down to the side, inner brows up, then back. No leaks."""
        length = rng.uniform(2.0, 4.0)
        return [Step(0.1, _toward(side * rng.uniform(10.0, 16.0), rng.uniform(12.0, 18.0)), hold=length),
                Step(0.1, _face("felt", "felt", {"BRW_Sorrow": 0.5}, attack=0.4, hold=round(length, 2), release=0.8)),
                Step(0.1 + length, {"cmd": "face_end", "layer": "felt", "slot": "felt", "fade": 0.6}),
                Step(0.1 + length, _look("camera"))], 0.1 + length

    def _bluff_tell(self, rng: random.Random, side: float) -> list[Step]:
        """She can't keep a straight face when she bluffs: a smile pressed back, eye contact a beat too long,
        then a glance away."""
        twitch = rng.uniform(0.1, 0.3)
        stare = rng.uniform(0.6, 1.0)
        yaw, pitch = side * rng.uniform(12.0, 20.0), rng.uniform(6.0, 12.0)
        away = rng.uniform(0.6, 1.0)
        steps = [Step(twitch, _face("leak", "leak", {"MTH_Fun": 0.5, "MTH_Small": 0.45}, attack=0.08, hold=0.4,
                                    release=0.2), lane=("leak", "bluff")),
                 Step(0.0, _look("camera"), hold=stare),
                 Step(stare, _toward(yaw, pitch), hold=away),
                 Step(stare + away, _look("camera"))]
        return steps + self._backstage(yaw, pitch, away, stare)

    def _denial_tell(self, rng: random.Random, side: float) -> list[Step]:
        """After a denial line: a break down to the side, then a burst of blinks."""
        length = rng.uniform(0.8, 1.4)
        at = rng.uniform(0.1, 0.3)
        return [Step(at, _toward(side * rng.uniform(10.0, 16.0), rng.uniform(10.0, 16.0)), hold=length),
                Step(at + length, _look("camera")),
                Step(rng.uniform(0.3, 0.6), {"cmd": "blink_mode", "mode": "burst", "count": rng.choice((2, 3))})]

    def _joke_glance(self, rng: random.Random, side: float) -> list[Step]:
        """After her joke: a hopeful look at chat, brows a little up, then back to neutral."""
        at, length = rng.uniform(0.1, 0.3), rng.uniform(1.0, 1.5)
        return [Step(at, _look("chat", (rng.uniform(2.0, 6.0), rng.uniform(-1.0, 1.0))), hold=length),
                Step(at, _face("felt", "check", {"BRW_Surprised": 0.3, "MTH_Joy": 0.15}, attack=0.2,
                               hold=round(max(0.2, length - 0.5), 2), release=0.5)),
                Step(at, _gesture("tilt", side * 0.75, 1.6)),
                Step(at + length, _look("camera"))]

    def _wait_for_laugh(self, t: float, spoke_at: float, rng: random.Random, side: float) -> None:
        """Live chat lags: reactions are only expected after the chat latency (persona.toml)."""
        wait = self.mind.persona["body"]["chat_latency_s"] + 8.0
        self._after.at(t + wait, self._left_hanging_now, spoke_at, rng, side)

    def _left_hanging_now(self, spoke_at: float, rng: random.Random, side: float) -> None:
        m = self.mind
        line = m.state.last_line
        active = any(m.now - t < 120.0 for t, _ in m.state.writers)
        if m.last_message_at > spoke_at or not active or line.get("settled") or self._speaking:
            return
        self._run(self._left_hanging(rng, side), self._now(), self._after)

    def _left_hanging(self, rng: random.Random, side: float) -> list[Step]:
        """Nobody laughed: the smile hangs on after the eyes leave chat, puzzled brows, then "it was funny"."""
        hang = rng.uniform(2.0, 2.5)
        return [Step(0.0, _look("chat", (rng.uniform(2.0, 6.0), 0.0)), hold=1.0),
                Step(0.0, _face("display", "social", {"MTH_Fun": 0.6, "MTH_Joy": 0.15}, attack=0.15,
                                hold=round(hang, 2), release=0.3, curve="deliberate"), lane=("felt", "left hanging")),
                Step(1.0, _look("camera")),
                Step(hang, _face("felt", "check", {"BRW_Angry": 0.25, "BRW_Sorrow": 0.25}, attack=0.15, hold=0.8,
                                 release=0.4)),
                Step(hang, _gesture("tilt", side * 0.3, 1.2)),
                Step(hang + 0.3, {"cmd": "blink"}),
                Step(hang + 1.0, {"cmd": "head_pose", "pitch": -5.0, "yaw": 0.0, "roll": 0.0, "hold": 1.2,
                                  "attack": 0.3, "release": 0.6, "slot": "stance"}),
                Step(hang + 1.0, _face("display", "stance", {"MTH_Small": 0.3}, attack=0.2, hold=1.2, release=0.4,
                                       curve="deliberate"))]

    def on_stop(self) -> None:
        """Cut off: everything stops, the faces let go, and she looks at the viewer."""
        self._stopped.set()
        self._stopped = asyncio.Event()
        self._speaking = False
        if self._read is not None:
            self._read.timeline.cancel()
            self._read.ready.set()
        self._read = None
        self._prepared = None
        self._queued = None
        self._honest = False
        self._cancel_timelines()
        self._stop_motion()
        self._gaze_holds.clear()
        self._clip_holds.clear()
        self._clip_actions.clear()
        for layer, slot in ON_STOP_SLOTS:
            self.cmd("face_end", layer=layer, slot=slot, fade=0.3)
        self._face = None
        self._felt_held = False
        self.look("camera")
        self._idle_tl.at(self._now() + self._dwell(1.4, 2.9), self._begin_idle)

    # --- idle, thoughts, the body (§3.10) ---------------------------------------------------------

    def thought(self, thought) -> None:
        """A thought crosses her mind (mind.thoughts.Thought): her eyes turn inward for a moment, and its
        tone shows as a leak (she's less guarded when she isn't talking to anyone)."""
        if self._speaking or self._read is not None:
            _LOGGER.info("  thought dropped (she's %s): %s", "speaking" if self._speaking else "reading", thought.text)
            return
        self._tick += 1
        rng = self._roll("body", f"{self.mind.seq}.{self._tick}")
        length = rng.uniform(1.5, 3.0)
        steps, _ = self._thought_steps(rng, thought.wound, thought.tone, length)
        self._stop_motion()
        self._idle_tl.cancel()
        self._skip_glance = True
        steps.append(Step(length + 0.1, fn=self._begin_idle))
        self._run(steps, self._now(), self._idle_tl)

    def _thought_steps(self, rng: random.Random, wound: bool, tone: str, length: float) -> tuple[list[Step], float]:
        side = self._favorite_side
        if wound:
            steps = [Step(0.0, _toward(side * rng.uniform(10.0, 16.0), rng.uniform(14.0, 20.0)), hold=length),
                     Step(0.0, _face("felt", "think", {"BRW_Sorrow": 0.3}, attack=0.4, hold=round(length, 2),
                                     release=0.6))]
        else:
            steps = [Step(0.0, _toward(side * rng.uniform(12.0, 24.0), rng.uniform(-8.0, 8.0)), hold=length)]
        region = "envy" if tone == "longing" else tone
        if tone != "neutral" and region in LEAKS and self.mind is not None:
            m = self.mind
            if tone == "longing":
                felt, k = m.state.drives["longing"].value, 0.0  # longing is the wound: hidden
            else:
                felt, k = m.state.emotions[tone].value, min(1.0, m.view()[tone]["k"])
            k2 = 1.0 - 0.7 * (1.0 - k)
            perf = self.faces.leak(region, felt * (1.0 - k2))
            steps += self._perf_steps(perf, rng.uniform(0.4, 0.8), lane=("leak", tone))
        steps.append(Step(length, _look("camera")))
        return steps, length

    def apply_body(self, body: dict, tonic: tuple[dict[str, float], float, float], gaze: dict) -> None:
        """Her state on her body (live loop, every second): the dials, the body's base values, the resting
        face and head (low-passed), the talking-gaze profile, and the cues her state adds while idle."""
        m = self._need_mind()
        now = self._now()
        S = m.suppression()
        _, gap, _ = m.leak()
        anxiety = m.state.emotions["anxiety"].value
        self._hiding = S > 0.5
        leaking = S > 0.5 or gap > 0.4  # the body leaks too
        self._base_energy = body["energy"]
        self.warmth = body["warmth"]
        self._set_energy()
        e = self.energy
        blinks = body["blinks_per_minute"] * (1.3 if gap > 0.4 and S <= 0.5 else 1.0)
        params = {
            "head_share": _lerp(0.55, 0.75, e),
            "head_speed": _lerp(5.5, 9.0, e) * (1.0 - 0.6 * body["freeze"]) * (0.7 if S > 0.5 else 1.0),
            "sway": _lerp(0.7, 1.3, e) * body["sway"],
            "breaths_per_minute": body["breaths_per_minute"],
            "breath_depth": body["breath_depth"] * (0.75 if gap > 0.4 and S <= 0.5 else 1.0),
            "blinks_per_minute": blinks,
            "talking_blinks_per_minute": blinks * 1.6,
            "shoulder_lift": 1.5 if leaking or anxiety >= 0.4 else 0.0,
        }
        changed = {k: round(v, 2) for k, v in params.items() if abs(self._body_sent.get(k, math.inf) - v) >= 0.01}
        if changed:
            self._body_sent.update(changed)
            self.cmd("body", **changed)
        # The resting face: low-passed (4 s), sent when it moves.
        shapes, pitch, roll = tonic
        if self._tonic is None:
            self._tonic = (dict(shapes), pitch, roll)
        else:
            alpha = 1.0 - math.exp(-max(0.0, now - self._tonic_at) / 4.0)
            old, p0, r0 = self._tonic
            keys = set(old) | set(shapes)
            self._tonic = ({k: old.get(k, 0.0) + (shapes.get(k, 0.0) - old.get(k, 0.0)) * alpha for k in keys},
                           p0 + (pitch - p0) * alpha, r0 + (roll - r0) * alpha)
        self._tonic_at = now
        cur, p, r = self._tonic
        sent = self._tonic_sent
        if sent is None or any(abs(cur.get(k, 0.0) - sent[0].get(k, 0.0)) > 0.03 for k in set(cur) | set(sent[0])):
            self.cmd("face_tonic", shapes={k: round(v, 3) for k, v in cur.items() if v >= 0.005})
            sent = (dict(cur), sent[1] if sent else math.inf, sent[2] if sent else math.inf)
        if abs(p - sent[1]) > 0.5 or abs(r - sent[2]) > 0.5:
            self.cmd("posture", pitch=round(p, 1), yaw=0.0, roll=round(r, 1), speed=0.5)
            sent = (sent[0], p, r)
        self._tonic_sent = sent
        self._gaze_profile = gaze
        # Cues her state adds while idle: a relief sigh when the threat drops; a shift when hiding ends.
        threat = m.state.wound["threat"].value
        if self._threat_peak is None or threat > self._threat_peak:
            self._threat_peak = threat
        elif self._threat_peak - threat >= 0.3:
            self._cues["relief_sigh"] = now + self.rng.uniform(1.0, 4.0)
            self._threat_peak = threat
        if S > 0.5:
            self._S_was_high = True
        elif S < 0.3 and self._S_was_high:
            self._S_was_high = False
            self._cues["hidden_ends"] = now + self.rng.uniform(3.0, 6.0)

    def _set_energy(self) -> None:
        joy = 0.2 * max(0.0, 1.0 - (self._now() - self._joy_at) / 30.0) if self._joy_at > -math.inf else 0.0
        self.energy = _clamp(self._base_energy + joy + (0.25 if self._philosophy else 0.0))

    def _begin_idle(self) -> None:
        self._begin(self._idle)

    async def _idle(self) -> None:
        self._philosophy = False
        while True:
            await asyncio.sleep(self.rng.uniform(0.2, 0.6))
            now = self._now()
            if now > self._next_reframe:
                if self._next_reframe and (reframe := self.camera.idle_reframe(now)):
                    self._send_cmd(reframe)
                self._next_reframe = now + self.rng.uniform(20.0, 40.0) / max(self.camera.cinematic, 0.25)
            if self.mind is not None and await self._state_cue(now):
                continue
            pick = self._pick_idle()
            if pick in ("camera", "chat", "around") and self._skip_glance:  # a thought replaced this glance
                self._skip_glance = False
                continue
            await getattr(self, f"_idle_{pick}")()

    def _pick_idle(self) -> str:
        e = self.energy
        weights = {"camera": 2.0 + 2.0 * e, "chat": 3.0 - e, "around": 0.8 + 0.8 * e, "shift": 0.5}
        if self._last_idle in weights:
            weights[self._last_idle] *= 0.25  # rarely the same thing twice in a row
        self._last_idle = self.rng.choices(list(weights), weights=list(weights.values()))[0]
        return self._last_idle

    async def _idle_camera(self) -> None:
        """Check in with the viewers."""
        if self._can_move_gaze():
            self.look("camera")
        if self.rng.random() < self._warm(0.2 + 0.2 * self.energy):
            self.cmd("gesture", name="tilt", strength=round(self._side(self.rng) * self.rng.uniform(0.4, 0.8), 2),
                     duration=round(self.rng.uniform(1.5, 3.0), 2))
        await asyncio.sleep(self._dwell(1.5, 4.5))

    async def _read_chat(self, lines: int) -> None:
        """Read lines in chat: small left-to-right jumps, a sweep back, the next line."""
        line = [self.rng.uniform(4, 7), self.rng.uniform(-2, 0)]
        self.look("chat", offset=line)
        await asyncio.sleep(self.rng.uniform(0.25, 0.5))
        for _ in range(lines):
            x = line[0]
            for _ in range(self.rng.randint(3, 5)):
                x -= self.rng.uniform(2.0, 3.5)  # her left-to-right is toward negative yaw
                self.look("chat", offset=[x, line[1] + self.rng.uniform(-0.3, 0.3)])
                await asyncio.sleep(self.rng.uniform(0.17, 0.3))
            line[1] += self.rng.uniform(1.5, 2.5)
            self.look("chat", offset=[self.rng.uniform(4, 7), line[1]])
            await asyncio.sleep(self.rng.uniform(0.15, 0.25))

    async def _idle_chat(self) -> None:
        if self._can_move_gaze():
            await self._read_chat(self.rng.randint(2, 4))
        await asyncio.sleep(self.rng.uniform(0.4, 1.0))

    async def _idle_around(self) -> None:
        for _ in range(self.rng.randint(1, 3)):
            yaw, pitch = self.rng.uniform(-35, 35), self.rng.uniform(-10, 12)
            length = self._dwell(0.8, 2.2)
            if self._can_move_gaze():
                self._send_cmd(_toward(yaw, pitch))
                self._run(self._backstage(yaw, pitch, length), self._now(), self._idle_tl)
            await asyncio.sleep(length)

    async def _idle_shift(self) -> None:
        self.cmd("shift_weight")
        if self.rng.random() < 0.5:
            self.cmd("gesture", name="inhale", strength=1.3, duration=0.9)  # a deeper breath with it
        await asyncio.sleep(self.rng.uniform(0.8, 1.6))

    async def _state_cue(self, now: float) -> bool:
        """One cue her state calls for, if one is due (idle only). True if it played."""
        m = self.mind
        e = {k: x.value for k, x in m.state.emotions.items()}
        drives = m.state.drives
        due = self._cues
        factor = 1.0 + e["anxiety"] + 0.5 * e["shame"] + e["fear"]
        contempt_leads = e["contempt"] > 0.05 and e["contempt"] == max(e.values())
        hiding = m.body()["hiding"] or m.leak()[1] > 0.4
        sad_self = e["sadness"] - m.state.emotions["sadness"].part_of(lambda s: s.startswith("news|"))
        lonely = drives["loneliness"].value > 0.5
        bored = drives["boredom"].value > 0.6
        rules = {  # cue -> (active, next interval)
            "glance": (factor > 1.3 and not contempt_leads, lambda: self.rng.uniform(6.0, 12.0) / factor),
            "shift": (True, lambda: self.rng.uniform(8.0, 15.0) if hiding or e["anxiety"] >= 0.3
                      else self.rng.uniform(30.0, 60.0)),
            "sad_sigh": (sad_self > 0.4, lambda: self.rng.uniform(40.0, 90.0)),
            "bored_sigh": (bored, lambda: self.rng.uniform(60.0, 120.0)),
            "chat_glance": (lonely, lambda: self.rng.uniform(6.0, 12.0)),
        }
        for cue, (active, interval) in rules.items():
            if not active:
                due.pop(cue, None)
            elif cue not in due:
                due[cue] = now + interval()
        for cue in ("relief_sigh", "hidden_ends", *rules):
            when = due.get(cue)
            if when is None or when > now:
                continue
            if cue in rules:
                due[cue] = now + rules[cue][1]()
            else:
                del due[cue]
                if now - when > 10.0:  # it came due while she was busy: the moment has passed
                    continue
            await self._cue(cue)
            return True
        return False

    async def _cue(self, cue: str) -> None:
        side = self._side(self.rng)
        match cue:
            case "glance":
                length = self.rng.uniform(0.3, 0.6)
                if self._can_move_gaze():
                    self._send_cmd(_toward(side * self.rng.uniform(10.0, 20.0), self.rng.uniform(-4.0, 6.0)))
                    await asyncio.sleep(length)
                    self.look("camera")
            case "shift":
                self.cmd("shift_weight")
            case "sad_sigh" | "bored_sigh" | "relief_sigh":
                self.cmd("gesture", name="sigh", strength=round(0.5 * self._amp(), 2))
            case "chat_glance":
                if self._can_move_gaze():
                    self.look("chat", offset=[self.rng.uniform(-2.0, 6.0), self.rng.uniform(0.0, 3.0)])
                    await asyncio.sleep(self.rng.uniform(0.6, 1.2))
                    self.look("camera")
            case "hidden_ends":
                self.cmd("shift_weight")
                self.cmd("gesture", name="exhale", strength=0.5)
        await asyncio.sleep(self.rng.uniform(0.4, 0.9))

    async def _talk(self) -> None:
        """While speaking: mostly the viewer, with short look-aways, as her state sets them."""
        # Her eyes stay where they were into the first words and find the viewer a moment later.
        if self._gaze != "camera":
            await asyncio.sleep(self.rng.uniform(0.3, 1.2))
        while True:
            share, away, pitch, length = self._talk_profile()
            if self._can_move_gaze():
                self.look("camera")
            await asyncio.sleep(self._dwell(1.5, 4.0) * (0.5 + share))
            if self.rng.random() < (1.0 - share) * _lerp(1.1, 0.8, self.energy) and self._can_move_gaze():
                side = self._side(self.rng)
                yaw = side * (self.rng.uniform(4.0, 12.0) if away == "down" else self.rng.uniform(8.0, 22.0))
                self._send_cmd(_toward(yaw, self.rng.uniform(*pitch)))
                await asyncio.sleep(self.rng.uniform(*length))

    def _talk_profile(self) -> tuple[float, str, tuple[float, float], tuple[float, float]]:
        """The talking gaze: the mind's profile (apply_body), with the reply's overrides."""
        g = self._gaze_profile
        share, away, pitch, length = ((g["share"], g["away"], tuple(g["pitch"]), tuple(g["length"])) if g is not None
                                      else (0.6, "side", (-8.0, 12.0), (0.4, 1.1)))
        reply = self._playing
        if reply is not None:
            if reply.honest:
                share = 1.0
            elif reply.denial and self._now() - reply.started < reply.denial_gaze:
                share = 1.0
            elif reply.stance == "stubborn":
                share = 0.9
            elif reply.stance == "philosophy" and self._now() - reply.started > 2.0:
                share = 0.85
        return share, away, pitch, length

    # --- slips -------------------------------------------------------------------------------------

    def _slips_ok(self) -> bool:
        """Body slips only when she's at ease: composed, no sorrow for someone, not after the crack, not
        right after someone's distress or her honest answer."""
        m = self.mind
        if m is None:
            return True
        sorrow = m.state.emotions["sadness"].part_of(lambda s: s.startswith("news|"))
        return (m.state.wound["composure"].value > 0.6 and sorrow <= 0.3 and m.now - m.coper.crack_at >= 120.0
                and self._now() - self._serious_at >= 240.0)

    def _maybe_double_take(self, rng: random.Random) -> list[Step]:
        """As her eyes come back to the camera after reading: now and then a late double-take at chat."""
        if self._now() - self._double_take_at < SLIP_EVERY or not self._slips_ok() or rng.random() >= 0.12:
            return []
        self._double_take_at = self._now()
        return self._double_take(0.0, rng)

    def _double_take(self, at: float, rng: random.Random) -> list[Step]:
        length = rng.uniform(0.5, 0.8)
        return [Step(at + 0.6, _look("chat"), hold=length, lane=("slip", "double take")),
                Step(at + 0.6 + length, _look("camera"))]

    # --- machinery ------------------------------------------------------------------------------------

    def cmd(self, command: str, /, **args) -> None:
        self._send_cmd({"cmd": command, **args})

    def look(self, target: str, offset: list[float] | None = None) -> None:
        self._send_cmd(_look(target, tuple(offset) if offset else (0.0, 0.0)))

    def _send_cmd(self, command: dict) -> None:
        if command["cmd"] == "look":
            self._gaze = command.get("target", "away")
        self._send({"type": "cmd", **command})

    def _now(self) -> float:
        return asyncio.get_running_loop().time()

    def _need_mind(self):
        if self.mind is None:
            raise RuntimeError("this needs her mind (the server runs with --llm none)")
        return self.mind

    def _roll(self, purpose: str, seq: int | str | None = None) -> random.Random:
        """The seeded draw for one event and purpose: Random(f"{stream seed}:{seq}:{purpose}")."""
        if seq is None:
            seq = self.mind.seq if self.mind is not None else self._events
        key = (str(seq), purpose)
        n = self._purposes.get(key, 0) + 1
        self._purposes[key] = n
        if len(self._purposes) > 4096:
            self._purposes = {key: n}
        return random.Random(f"{self._seed}:{seq}:{purpose}" + (f":{n}" if n > 1 else ""))

    def _side(self, rng: random.Random) -> float:
        return self._favorite_side if rng.random() < 0.7 else -self._favorite_side

    def _perf_steps(self, perf: Performance, at: float, lane: tuple[str, str] | None = None,
                    tag: str = "") -> list[Step]:
        """A performance's commands as steps from `at` ("dt" and "gaze_hold" are brain's, never sent). Its gaze
        holds are soft when all it does with the eyes is look at the camera."""
        looks = [c for c in perf.commands if c["cmd"] == "look"]
        soft = bool(looks) and all(c.get("target") == "camera" and not any(c.get("offset", ())) for c in looks)
        steps = []
        for c in perf.commands:
            c = dict(c)
            dt = c.pop("dt")
            hold = c.pop("gaze_hold", None)
            steps.append(Step(at + dt, c, hold, soft, tag=tag))
        if perf.gaze_until > 0.0:
            steps.append(Step(at, hold=perf.gaze_until, soft=soft, tag=tag))
        if lane is not None:
            steps.append(Step(at, lane=lane, tag=tag))
        return steps

    @staticmethod
    def _retime(perf: Performance, **fields: float) -> None:
        """Change a performance's face envelope (the mimicry's slower attack, the re-mask's 1 s)."""
        for c in perf.commands:
            if c["cmd"] == "face_layer":
                c.update(fields)

    def _camera_step(self, command: dict, at: float) -> Step:
        command = dict(command)
        return Step(at + command.pop("dt", 0.0), command)

    def _run(self, steps: list[Step], start: float, timeline: Timeline) -> None:
        """Send a plan: each step at start + t (loop time)."""
        for s in sorted(steps, key=lambda s: s.t):
            timeline.at(start + s.t, self._fire, s, tag=s.tag)

    def _fire(self, s: Step) -> None:
        if s.cmd is not None:
            self._send_cmd(dict(s.cmd))
        if s.hold is not None:
            now = self._now()
            self._gaze_holds.append((now, now + s.hold, s.soft))
        if s.lane is not None and self.mind is not None:
            self.mind.lane_event(*s.lane)
        if s.fn is not None:
            s.fn()

    def _to_clip(self, steps: list[Step], key: tuple[int, int]) -> list[dict]:
        """A plan as a clip's timed commands; gaze holds, lane events and actions start with the clip."""
        commands, holds, actions = [], [], []
        for s in sorted(steps, key=lambda s: s.t):
            t = max(0.0, s.t)
            if s.cmd is not None:
                commands.append({"t": round(t, 3), **s.cmd})
            if s.hold is not None:
                holds.append((t, t + s.hold, s.soft))
            if s.lane is not None and self.mind is not None:
                actions.append((t, lambda lane=s.lane: self.mind.lane_event(*lane)))
            if s.fn is not None:
                actions.append((t, s.fn))
        self._clip_holds[key] = holds
        self._clip_actions[key] = actions
        return commands

    def _held(self, perf: Performance) -> None:
        """A put-on face started on display/face: remember what's held there, and until when."""
        face = next((c for c in perf.commands if c["cmd"] == "face_layer" and c["slot"] == "face"), None)
        if face is None:
            return
        held = face["hold"] < 0
        until = face.get("max_hold", math.inf) if held else face["hold"]
        self._face = _HeldFace(perf.name, held, self._now() + face["dt"] + face["attack"] + until, perf.moves_head)

    def _release_face(self, fade: float) -> None:
        """Her line's faces let go: the put-on face and stance, and a feeling held through the line (more slowly:
        a felt face eases out)."""
        self._face = None
        self.cmd("face_end", layer="display", slot="face", fade=fade)
        self.cmd("face_end", layer="display", slot="stance", fade=fade)
        if self._felt_held:
            self._felt_held = False
            self._face_end("felt", "felt", HELD_FELT_FADE)
            if self._felt is not None:
                self._felt.ends = self._now() + HELD_FELT_FADE

    def _face_end(self, layer: str, slot: str, fade: float) -> None:
        self.cmd("face_end", layer=layer, slot=slot, fade=round(fade, 2))

    def _begin(self, behavior: Callable) -> None:
        """Switch the gaze behavior (idle, composing, talking); the old one stops wherever it's waiting."""
        if self._task:
            self._task.cancel()
        self._task = asyncio.get_running_loop().create_task(behavior())

    def _stop_motion(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def _cancel_timelines(self) -> None:
        for tl in (self._after, self._idle_tl, self._speech_tl, self._ticks, self._seq_tl):
            tl.cancel()

    def _cancel_all(self) -> None:
        """Godot (re)connected or left: nothing of what was playing goes on."""
        self._cancel_timelines()
        if self._read is not None:
            self._read.timeline.cancel()
            self._read.ready.set()
        self._read = self._prepared = self._playing = None
        self._speaking = False
        self._felt_held = False
        self._clip_holds.clear()
        self._clip_actions.clear()
        self._gaze_holds.clear()
        self._stop_motion()

    @staticmethod
    async def _wait(aw, stopped: asyncio.Event) -> None:
        """Await `aw` unless she's stopped first."""
        task = asyncio.ensure_future(aw)
        stop = asyncio.ensure_future(stopped.wait())
        await asyncio.wait((task, stop), return_when=asyncio.FIRST_COMPLETED)
        for t in (task, stop):
            t.cancel()

    def _send_body(self) -> None:
        """Body values from the energy dial alone (no mind)."""
        e = self.energy
        blinks = _lerp(13.0, 19.0, e)
        self.cmd("body", head_share=round(_lerp(0.55, 0.75, e), 2), head_speed=round(_lerp(5.5, 9.0, e), 2),
                 sway=round(_lerp(0.7, 1.3, e), 2), breaths_per_minute=round(_lerp(12.0, 17.0, e), 2),
                 blinks_per_minute=round(blinks, 2), talking_blinks_per_minute=round(blinks * 1.6, 2))

    def _can_move_gaze(self, over_soft: bool = False) -> bool:
        """No look holds her gaze now. over_soft: a hold that only keeps her eyes on the camera doesn't count."""
        now = self._now()
        self._gaze_holds = [h for h in self._gaze_holds if h[1] > now]
        return not any(a <= now and not (soft and over_soft) for a, _, soft in self._gaze_holds)

    def _warm(self, chance: float) -> float:
        """Scale the chance of a friendly gesture by warmth."""
        return chance * _lerp(0.3, 1.3, self.warmth)

    def _amp(self) -> float:
        """Gesture size: energy, plus a boost for [dramatic] sentences; smaller while she hides (S > 0.5)."""
        return _lerp(0.6, 1.4, min(1.0, self.energy + self._boost)) * (0.7 if self._hiding else 1.0)

    def _dwell(self, low: float, high: float) -> float:
        """How long to hold a look: calmer = longer."""
        return self.rng.uniform(low, high) * _lerp(1.35, 0.7, self.energy)
