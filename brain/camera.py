"""The cinematographer: frames her the way a film would, on engine events only.

The camera moves when her mind does, never on the actor's tags (docs/mind.md,
"Camera"): a felt horror startle snaps it a little closer, and felt moments
that need a closer shot (the crack, tenderness, guilt softening) get a slow
push to medium-close that starts when the appraisal lands, a beat before her
face shows the feeling. It never pushes in on a put-on or overplayed face:
pushing in on the act would amplify the act.

There are no hard cuts (one continuous camera, so a cut reads as a jump).
Nothing is tied to the end of her speech: after a push the camera holds at
least 4 s, and it reframes later, during idle, so it never signals "the AI
finished talking". Idle reframes sometimes arc around to her other side;
every move then happens from whichever side the camera is on. Godot's
CameraRig performs the moves; this only decides them.

`cinematic` (0 locked-off tripod .. 1 very cinematic) scales how often and how
strongly the camera moves. Times are the brain's loop clock (seconds).
"""

import math
import random

BASE_SHOT = "medium"
BASE_YAW = 14.0  # degrees around her (+ = her left); the camera works from either side
SHOTS = ["wide", "medium", "mcu", "close", "extreme"]  # widest to tightest
ENGINE_MOVES = ["push", "startle"]

# Height angle in degrees: + = camera above her eyes, looking down.
ANGLES = {"eye": 1.0, "low": -9.0, "high": 11.0}

PUSH_EVERY = 60.0  # at most one push per minute
HOLD_AFTER = 4.0  # a move holds at least this long before an idle reframe


def _clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))


class Cinematographer:
    def __init__(self, cinematic: float, rng: random.Random):
        self.cinematic = cinematic
        self.rng = rng
        self.shot = BASE_SHOT
        self.side = 1.0  # +1 = filming from her left, -1 = from her right
        self._pushed_at = -math.inf
        self._hold_until = -math.inf  # no idle reframe before this (loop time)

    def handheld(self, extra: float = 0.0) -> float:
        """Resting handheld drift for this level of cinematic."""
        return round(_clamp(0.06 + 0.2 * self.cinematic + extra, 0.0, 1.0), 2)

    def setup(self) -> list[dict]:
        """When Godot connects: base shot, resting drift."""
        self.shot, self.side = BASE_SHOT, 1.0
        self._pushed_at = self._hold_until = -math.inf
        return [{"cmd": "camera", "shot": BASE_SHOT, "move": "cut", "yaw": BASE_YAW},
                {"cmd": "camera_handheld", "amount": self.handheld()}]

    def push(self, now: float, shot: str = "mcu", force: bool = False) -> list[dict]:
        """A felt moment: a slow move in to `shot` over 3-5 s. Nothing when the
        shot is already that tight, when the camera is locked off, or when it
        pushed in during the last minute (force: the crack, which happens once a
        stream, isn't held back by an earlier push)."""
        if (self.cinematic <= 0.0 or SHOTS.index(self.shot) >= SHOTS.index(shot)
                or (now - self._pushed_at < PUSH_EVERY and not force)):
            return []
        duration = self.rng.uniform(3.0, 5.0)
        self.shot = shot
        self._pushed_at = now
        self._hold_until = now + duration + HOLD_AFTER
        return [{"cmd": "camera", "shot": shot, "move": "move", "duration": round(duration, 2),
                 "yaw": round(self.side * BASE_YAW, 1), "elevation": ANGLES["eye"]}]

    def startle(self, now: float) -> list[dict]:
        """A felt horror startle: a short snap a little closer (to medium-close,
        or close from medium-close), a jolt, and a rougher hand for 1.5 s.
        Commands may carry "dt" (seconds after now)."""
        if self.cinematic <= 0.0:
            return []
        out: list[dict] = []
        target = "close" if self.shot == "mcu" else "mcu"
        if SHOTS.index(target) > SHOTS.index(self.shot):
            self.shot = target
            out.append({"cmd": "camera", "shot": target, "move": "snap", "duration": 0.3,
                        "yaw": round(self.side * BASE_YAW, 1), "elevation": ANGLES["eye"]})
        out += [{"cmd": "camera_shake", "amount": round(0.35 * (0.5 + self.cinematic), 2)},
                {"cmd": "camera_handheld", "amount": self.handheld(0.3)},
                {"cmd": "camera_handheld", "amount": self.handheld(), "dt": 1.5}]
        self._hold_until = max(self._hold_until, now + 0.3 + HOLD_AFTER)
        return out

    def idle_reframe(self, now: float) -> dict | None:
        """Now and then while idle: a slow reframe. From a tight shot it eases
        back out; otherwise it drifts to a slightly different medium framing.
        Sometimes it arcs around to her other side (a slow orbit, never a jump).
        Never while a push or a startle is still holding."""
        if self.cinematic <= 0.0 or now < self._hold_until:
            return None
        tight = SHOTS.index(self.shot) >= SHOTS.index("mcu")
        self.shot = self.rng.choice(["medium", "medium", "mcu"] if not tight else ["medium"])
        orbit = self.rng.random() < 0.3 * self.cinematic
        if orbit:
            self.side = -self.side
        return {"cmd": "camera", "shot": self.shot, "move": "move",
                "duration": round(self.rng.uniform(5.0, 8.0) if orbit else self.rng.uniform(4.0, 7.0), 1),
                "yaw": round(self.side * BASE_YAW + self.rng.uniform(-6.0, 6.0), 1)}

    def test(self, name: str, now: float) -> list[dict]:
        """One shot size, framing or engine move, for trying it out (debug
        dropdown). Commands may carry "dt". Unknown names raise KeyError."""
        if name == "base shot":
            self.shot = BASE_SHOT
            return [{"cmd": "camera", "shot": BASE_SHOT, "move": "move", "duration": 1.2,
                     "yaw": round(self.side * BASE_YAW, 1)},
                    {"cmd": "camera_handheld", "amount": self.handheld()}]
        if name == "other side":
            self.side = -self.side
            return [{"cmd": "camera", "shot": self.shot, "move": "move", "duration": 5.0,
                     "yaw": round(self.side * BASE_YAW, 1)}]
        if name in SHOTS:
            self.shot = name
            return [{"cmd": "camera", "shot": name, "move": "move", "duration": 1.2,
                     "yaw": round(self.side * BASE_YAW, 1)}]
        if name == "push":  # from the base shot, so the move shows
            self.shot, self._pushed_at = BASE_SHOT, -math.inf
            return self.push(now)
        if name == "startle":
            self.shot = BASE_SHOT
            return self.startle(now)
        raise KeyError(f"camera test: unknown shot or move {name!r}")
