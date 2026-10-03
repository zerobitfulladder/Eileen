"""Faces: every face she makes, and the commands that perform it.

docs/mind.md ("What the body shows") gives the recipes; the body contract (§2)
gives this interface. Python decides which face, which side, how strong and
when; Godot (avatar/face.gd) only mixes and moves.

People make faces in two ways, and so does she:

  put-on  faces she makes on purpose: the actor's tags ([smug], [eye roll]...)
          and the few the engine picks (tired, annoyed, the social smiles).
          Like all posed expressions they snap on, hold flat, stop quickly and
          are a little lopsided: the side she turns toward at full strength,
          the other eye at 0.75.
  felt    what she actually feels, shown only by the engine: the emotions, the
          engine's felt faces, composites, the reading face's checks, leaks
          and felt laughs. They ease in, drift a little at the peak, ease out,
          and are symmetric (contempt is the one-sided exception). Only a felt
          smile reaches both eyes (EYE_Joy, the Duchenne marker).

Channels, so every face is its own mix: lids show arousal and attention; brows
show concern (inner brows up) and anger (lowered); EYE_Joy shows real
enjoyment; the mouth carries social signals; the head shows dominance and
approach; gaze shows attention; blinks, breath and stillness show arousal and
hiding.

Recipe keys:
  shapes      {blend shape: weight at intensity 1}
  head        (pitch, yaw, roll) held with the face; chest (+ curls forward); shoulders (lift)
  gaze        "camera" | "chat" | (yaw, pitch) | "fixed" (the eyes stay where they are) | None (not moved)
  gaze_mode   "eyes": only the eyes move;  gaze_at: when the look starts
  back        (lo, hi) s before the eyes return to the camera;  glide: s for that return
  gaze_hold   s the gaze stays put: a number, (lo, hi), "length" or ("length", factor)
  looks       a scripted gaze: [(at, target, options)]; at is s, (lo, hi), or ("+", lo, hi) after the
              previous look; target "camera", "chat", (yaw, pitch) or "stay" (no move, just held)
  hold        (lo, hi) s at the peak outside speech;  attack;  release
  then        [(gesture, strength, at[, duration])]; "blink" and "inhale" are the blink and inhale commands
  at_return   [(gesture, strength)] when the eyes come back (eye roll: a blink and a sigh)
  blink       ("slow", fraction of the hold) | "flutter" | ("suppress", "hold" or "length")
  breath      s of held breath;  freeze;  ramps [(param, value, back_after: s, "hold", "length" or "stare")]
  open        what changes when the face is held open through speech (hold -1)
Angles in degrees: pitch + = chin down, yaw + = her left, roll + = tilt to her right. One-sided shapes and
angles are written for side +1 (her left); side -1 mirrors them. Every name is a blend shape on Eileen.vrm.
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass

from mind.expression import LENGTH as _ENGINE_LENGTH


def _f(**weights: float) -> dict[str, float]:
    """Shapes by short name: _f(EYE_Close=0.45) -> {"Fcl_EYE_Close": 0.45}."""
    return {"Fcl_" + name: weight for name, weight in weights.items()}


# fmt: off
# Put-on faces. Display layer, slot "face", curve deliberate, attack 0.1 (the thinking faces 0.25), release 0.2.
PUT_ON: dict[str, dict] = {
    # A flat line: heavy lids, a flat wide mouth, nothing moves; one slow blink.
    "deadpan": {"shapes": _f(EYE_Close=0.45, MTH_Large=0.7, BRW_Angry=0.15), "head": (0, 0, 0), "gaze": "camera",
                "hold": (1.5, 2.5), "blink": ("slow", (0.6, 0.8)), "ramps": [("sway", 0.2, "hold")],
                "open": {"blink_at": (1.2, 1.8), "hold": 3.0}},
    # The iris in the corner of the eye, the head not following: silent judgment.
    "side eye": {"shapes": _f(EYE_Close=0.3, BRW_Angry=0.45, MTH_Angry=0.35), "head": (2, -4, 0),
                 "gaze": (30, 3), "gaze_mode": "eyes", "back": (0.9, 1.4), "hold": (1.0, 1.5)},
    # The iris half under the upper lid, the head tipping back; a blink and a sigh on the way back.
    "eye roll": {"shapes": _f(EYE_Close=0.15, MTH_Large=0.3, BRW_Angry=0.3), "head": (-5, -6, 6),
                 "gaze": (8, -30), "gaze_mode": "eyes", "back": (0.45, 0.7), "hold": (0.8, 1.2),
                 "at_return": [("blink", 0), ("sigh", 0.4)]},
    # Chin up, one lower lid raised: pleased with herself.
    "smug": {"shapes": _f(EYE_Close=0.28, EYE_Joy_L=0.3, MTH_Fun=0.9, MTH_Joy=0.1), "head": (-9, 6, -3),
             "gaze": "camera", "hold": (1.2, 2.0)},
    # A one-eyed smile and a big tilt.
    "teasing": {"shapes": _f(EYE_Joy_L=0.5, EYE_Joy_R=0.15, MTH_Fun=0.8, MTH_Joy=0.15), "head": (2, 5, 11),
                "gaze": "camera", "hold": (1.2, 2.0)},
    # "Really?": one narrowed eye, the head turned away, the eyes still on you.
    "skeptical": {"shapes": _f(EYE_Close_L=0.45, EYE_Angry=0.2, BRW_Angry=0.5, MTH_Angry=0.35), "head": (4, 10, 0),
                  "gaze": "camera", "hold": (1.2, 2.0)},
    # Both eyes slit; the eyes start with the head, then slide back to you; no blinking.
    "suspicious": {"shapes": _f(EYE_Angry=1.0, EYE_Close=0.3, BRW_Angry=0.65, MTH_Small=0.35), "head": (3, 12, 0),
                   "looks": [(0.0, (12, 0), {}), (0.15, "camera", {"glide": 0.6, "hold": "hold"})],
                   "hold": (1.5, 2.5), "blink": ("suppress", "hold"), "open": {"hold": 3.0}},
    # A droop, a wandering gaze that comes back slowly, a sigh.
    "bored": {"shapes": _f(EYE_Close=0.5, EYE_Sorrow=0.4, MTH_Sorrow=0.15), "head": (4, 5, 10),
              "gaze": (25, 8), "gaze_at": 0.4, "back": (1.2, 2.0), "glide": 0.5, "hold": (2.0, 3.0),
              "then": [("sigh", 0.5, 0.6)], "blink": ("slow", 0.7)},
    # Eyes up to the side, trying to remember.
    "recall": {"shapes": _f(BRW_Surprised=0.7, MTH_U=0.3), "head": (-6, 10, 3), "gaze": (25, -18),
               "back": (0.9, 1.5), "hold": (1.0, 1.6), "attack": 0.25},
    # Weighing it up: narrowed eyes, a pressed mouth, the gaze down to the side.
    "considering": {"shapes": _f(EYE_Angry=0.45, BRW_Angry=0.4, MTH_Small=0.55), "head": (3, 4, 8),
                    "gaze": (12, 12), "back": (1.0, 1.8), "hold": (1.0, 2.0), "attack": 0.25},
    # Not sure: worried brows, the mouth pulled down, a small shake.
    "unsure": {"shapes": _f(BRW_Sorrow=0.7, EYE_Sorrow=0.25, MTH_Angry=0.25), "head": (1, 3, 7), "gaze": (14, 4),
               "back": (0.4, 0.7), "hold": (1.0, 1.6), "then": [("shake", 0.3, 0.1)], "attack": 0.25},
    # A social smile: the mouth and the lower lids; the real smiling eyes don't join.
    "smile": {"shapes": _f(MTH_Fun=1.0, MTH_Joy=0.2, EYE_Fun=0.5), "head": (0, 0, 0), "gaze": "camera",
              "hold": (0.8, 2.0)},
    # A showy open grin, the eyes not smiling.
    "grin": {"shapes": _f(MTH_Joy=0.55, MTH_Fun=0.5, EYE_Fun=0.35), "head": (-3, 0, 4), "gaze": "camera",
             "hold": (1.0, 1.6)},
    # Pushed lips and a small frown.
    "pout": {"shapes": _f(MTH_U=0.7, BRW_Angry=0.35, EYE_Close=0.15), "head": (3, 4, 6), "gaze": "camera",
             "hold": (1.0, 1.8)},
    # --- engine-only: never taken from the actor's tags ---
    # Overplayed tiredness for human things (simulate: late, long, a slow blink, a sigh a bit too big);
    # the [sigh] tag uses it at 0.6 for the sigh's length.
    "tired": {"shapes": _f(EYE_Close=0.5, BRW_Sorrow=0.3), "head": (4, 0, 6), "gaze": (0, 14), "back": (0.6, 0.9),
              "hold": (1.2, 2.0), "simulate": {"then": [("sigh", 0.7, 1.2)], "slow_blink_at": 0.5}},
    # The [groan] face (brain passes hold = the groan's length + 0.3).
    "annoyed": {"shapes": _f(EYE_Close=0.45, BRW_Angry=0.55, MTH_Angry=0.45), "head": (-6, 0, 4), "gaze": None,
                "hold": (1.0, 1.6)},
}
ACTOR_FACES = ("deadpan", "side eye", "eye roll", "smug", "teasing", "skeptical", "suspicious", "bored", "recall",
               "considering", "unsure", "smile", "grin", "pout")
ENGINE_PUT_ON = ("tired", "annoyed")
THINKING_FACES = ("recall", "considering", "unsure")

# Felt faces. Felt layer, slot "felt", curve felt. Unless a recipe says otherwise: attack U(0.35, 0.6),
# release U(1.0, 2.5), hold = a draw from LENGTH minus attack minus 0.5 (at least 0.3, at most 5).
FELT: dict[str, dict] = {
    # --- the emotions (mind.expression.FACE) ---
    # MTH_Joy grows with intensity (see _amusement); a chuckle from 0.6, a laugh from 0.85.
    "amusement": {"shapes": _f(MTH_Fun=0.8, MTH_Joy=0.1, EYE_Joy=0.4, BRW_Fun=0.3), "head": (-3, 0, 4), "gaze": None},
    "joy": {"shapes": _f(MTH_Joy=0.55, EYE_Joy=0.55, BRW_Joy=0.6), "head": (-4, 0, 0), "gaze": "camera",
            "then": [("lift", 0.6, 0.3)]},
    # A small smile, chin up, chest out, long looks at you, slower breathing.
    "pride": {"shapes": _f(MTH_Fun=0.4, EYE_Close=0.15), "head": (-8, 3, 0), "chest": -2, "gaze": "camera",
              "gaze_hold": "length", "ramps": [("breaths_per_minute", 0.85, "length")]},
    # The lids drop with a sigh, then a small real smile.
    "relief": {"phases": [{"at": 0.0, "shapes": _f(EYE_Close=0.6), "head": (3, 0, 3), "attack": 0.3, "hold": 0.5},
                          {"at": 0.5, "shapes": _f(MTH_Fun=0.4, EYE_Joy=0.2), "head": (0, 0, 0)}],
               "gaze": (0, 8), "back": (0.6, 1.0), "then": [("sigh", 0.6, 0.05)]},
    # Tender: soft eyes, a gentle smile, inner brows a little up, a tilt, longer looks, a slow blink.
    "warmth": {"shapes": _f(EYE_Joy=0.22, MTH_Fun=0.5, BRW_Sorrow=0.25), "head": (2, 0, 6), "gaze": "camera",
               "gaze_hold": ("length", 1.3), "attack": 0.8, "blink": ("slow", 0.6)},
    # Intrigued: eyes open, brows up, leaning in, fewer blinks.
    "interest": {"shapes": _f(EYE_Spread=0.6, BRW_Surprised=0.55, MTH_Small=0.2), "head": (3, 0, 6), "gaze": "camera",
                 "then": [("lean_in", 0.6, 0.2)], "ramps": [("blinks_per_minute", 0.6, "length")]},
    "surprise": {"shapes": _f(EYE_Surprised=0.5, EYE_Spread=0.5, BRW_Surprised=0.9, MTH_Surprised=0.35),
                 "head": (-3, 0, 0), "gaze": "fixed", "attack": 0.08, "hold": (0.3, 0.7), "release": 0.4,
                 "then": [("gasp", 0.5, 0.0)], "blink": ("suppress", "length")},
    # Still, a short sharp exhale, a few more blinks.
    "irritation": {"shapes": _f(BRW_Angry=0.55, EYE_Close=0.28, MTH_Angry=0.3), "head": (2, 0, 0), "gaze": None,
                   "then": [("exhale", 0.5, 0.3)], "ramps": [("blinks_per_minute", 1.2, "length")]},
    # A glare from under the brows and a still stare.
    "anger": {"shapes": _f(BRW_Angry=0.9, EYE_Angry=0.7, MTH_Angry=0.3, MTH_Small=0.3), "head": (3, 0, 0),
              "gaze": "camera", "gaze_hold": (2.0, 4.0),
              "ramps": [("sway", 0.3, "stare"), ("blinks_per_minute", 0.4, "stare")]},
    # Down her nose, one lid lower, a scoff, a look away.
    "contempt": {"shapes": _f(EYE_Close=0.38, EYE_Close_L=0.2, MTH_Fun=0.3, MTH_Angry=0.25), "head": (-6, 8, -4),
                 "looks": [(0.0, "camera", {}), (0.6, (15, 2), {}), (1.4, "camera", {})],
                 "then": [("lift", 0.6, 0.15), ("exhale", 0.4, 0.25)]},
    # Inner brows up, heavy eyes, head and gaze down, stiller.
    "sadness": {"shapes": _f(BRW_Sorrow=0.85, EYE_Sorrow=0.6, MTH_Angry=0.3, MTH_Sorrow=0.15), "head": (6, 0, 3),
                "gaze": (5, 18), "back": (1.5, 2.5), "ramps": [("sway", 0.6, "length")]},
    # Sadness about someone else's news: soft, worried eyes, a steady, warm look and slow nods; no sighs. The
    # spec's BRW_Sorrow 0.4 + MTH_Small 0.2 read as her resting face with a tilt (the brows sit under her bangs),
    # so the inner brows go to 0.55 and the eyes soften (EYE_Sorrow 0.25), the part of the face that shows.
    "concern": {"shapes": _f(BRW_Sorrow=0.55, EYE_Sorrow=0.25, MTH_Small=0.2), "head": (2, 0, 5), "gaze": "camera",
                "gaze_hold": "length", "attack": 0.6,
                "then": [("nod", 0.3, 0.8, 0.8), ("nod", 0.3, ("+", 1.2, 1.6), 0.8)]},
    "anxiety": {"shapes": _f(EYE_Spread=0.4, BRW_Sorrow=0.5, MTH_Small=0.35), "head": (2, 4, 0), "shoulders": 1.5,
                "gaze": (14, 2), "back": (0.3, 0.6), "ramps": [("blinks_per_minute", 1.4, "length")]},
    # Wide eyes, raised and drawn brows, pulled back; a freeze with the breath held (see _fear).
    "fear": {"shapes": _f(EYE_Surprised=0.7, EYE_Spread=0.3, BRW_Sorrow=0.55, BRW_Surprised=0.3, MTH_I=0.3),
             "head": (-4, 0, 0), "chest": -2, "gaze": "fixed", "attack": 0.1},
    # A 3-5 s sequence: gaze down, a smile she presses away, head away, glances back (see _embarrassment).
    "embarrassment": {"phases": [
        {"at": 0.2, "shapes": _f(MTH_Fun=0.5, BRW_Sorrow=0.35, EYE_Joy=0.2), "attack": 0.3, "hold": 0.3},
        {"at": 0.5, "shapes": _f(MTH_Small=0.35, MTH_Fun=0.3, EYE_Joy=0.2, BRW_Sorrow=0.35), "head": (6, 12, 5),
         "attack": 0.25, "hold": (0.6, 1.5), "release": 1.0}]},
    # Head and eyes down and away, no smile.
    "shame": {"shapes": _f(BRW_Sorrow=0.6, EYE_Sorrow=0.4, EYE_Close=0.35), "head": (12, 6, 3), "chest": 3,
              "gaze": (10, 25), "back": (3.0, 8.0), "ramps": [("sway", 0.5, "length"), ("breath_depth", 0.7, "length")]},
    # Unlike shame, guilt looks at the person, with a slow small nod.
    "guilt": {"shapes": _f(BRW_Sorrow=0.6, EYE_Sorrow=0.3, MTH_Sorrow=0.2), "head": (4, 0, 5), "gaze": "camera",
              "then": [("nod", 0.3, 0.6, 0.8)]},
    # The look lingers a second too long, then slides away; a small inhale.
    "envy": {"shapes": _f(EYE_Close=0.2, MTH_Small=0.3, BRW_Sorrow=0.3), "head": (2, -3, 0),
             "looks": [(0.0, "stay", {}), ((1.0, 1.8), (15, 12), {}), (("+", 0.5, 0.5), "camera", {})],
             "then": [("inhale", 0.5, 0.3)]},
    # A squint at chat, a blink, leaning back a little.
    "confusion": {"shapes": _f(BRW_Angry=0.4, BRW_Sorrow=0.45, MTH_Small=0.35, EYE_Close=0.1), "head": (1, 5, 10),
                  "looks": [(0.0, "chat", {}), (0.8, "camera", {})],
                  "then": [("lean_in", -0.3, 0.1), ("blink", 0, 0.5)]},
    # --- engine-only felt faces ---
    # The honest answer: inner brows up, a steady look, a slow nod, fewer blinks.
    "sincere": {"shapes": _f(BRW_Sorrow=0.45, EYE_Close=0.12), "head": (3, 0, 0), "gaze": "camera",
                "gaze_hold": (3.0, 5.0), "attack": 0.5, "hold": (2.5, 4.0), "then": [("nod", 0.25, 0.6, 0.8)],
                "ramps": [("blinks_per_minute", 0.7, "hold")]},
    # Chin down, looking up at you, a small smile, two glances away.
    "coy": {"shapes": _f(MTH_Fun=0.5, EYE_Joy=0.25, BRW_Sorrow=0.35), "head": (8, 5, 8), "hold": (2.0, 3.0),
            "looks": [(0.0, "camera", {"offset": (0, -4)}), (0.8, (10, 12), {}),
                      (("+", 0.3, 0.5), "camera", {"offset": (0, -4)}), (1.8, (10, 12), {}),
                      (("+", 0.3, 0.5), "camera", {"offset": (0, -4)})]},
    "wince": {"shapes": _f(EYE_Close=0.75, BRW_Angry=0.5, BRW_Sorrow=0.3, MTH_I=0.4), "head": (-4, 9, 6), "gaze": None,
              "attack": 0.08, "hold": (0.3, 0.6), "release": 0.4, "then": [("recoil", 0.7, 0.0)]},
    # Getting it a beat late: brows up, eyes open, "oh", a nod.
    "realize": {"shapes": _f(BRW_Surprised=0.9, EYE_Spread=0.7, MTH_O=0.3), "head": (-6, 0, -2), "gaze": "camera",
                "attack": 0.12, "hold": (0.6, 1.0), "release": 0.6, "then": [("nod", 0.5, 0.4)]},
    # The reading face's frown, only for real thinking; brain moves the eyes and releases it.
    "thinking": {"shapes": _f(BRW_Angry=0.45, EYE_Angry=0.25, MTH_Small=0.5), "head": (0, 0, 0), "gaze": None,
                 "slot": "think", "attack": 0.6, "hold": -1},
    # --- composites ---
    # The crack: a smile with grieving brows; with eyes=True the smile reaches her eyes.
    "sad smile": {"shapes": _f(MTH_Fun=0.5, BRW_Sorrow=0.7, EYE_Sorrow=0.35, EYE_Joy=0.1), "eyes": _f(EYE_Joy=0.3),
                  "head": (5, 4, 6), "gaze": (8, 14), "back": (1.2, 2.0), "attack": 0.6, "hold": (1.5, 2.5)},
    # Joy or duping delight leaking: a smile pressed back, looking away.
    "suppressed smile": {"shapes": _f(MTH_Fun=0.4, MTH_Small=0.4, EYE_Joy=0.3), "head": (3, 10, 4), "gaze": (18, 8),
                         "back": (0.8, 1.3), "attack": 0.25, "hold": (0.8, 1.3)},
    # Nobody home for a moment: the light goes out of her eyes, and she freezes.
    "hollow": {"shapes": _f(EYE_Highlight_Hide=0.9, EYE_Close=0.15), "head": (2, 0, 0), "gaze": None, "attack": 0.3,
               "hold": (0.4, 0.8), "freeze": True},
}
EMOTIONS = ("amusement", "joy", "pride", "relief", "warmth", "interest", "surprise", "irritation", "anger",
            "contempt", "sadness", "anxiety", "fear", "embarrassment", "shame", "guilt", "envy", "confusion")
ENGINE_FELT = ("sincere", "coy", "wince", "realize", "thinking")
COMPOSITES = ("sad smile", "suppressed smile", "hollow")

# The reading face: what each appraisal check shows (felt layer, slot "check", curve felt).
CHECKS: dict[str, dict] = {
    "brow_flash": {"shapes": _f(BRW_Surprised=0.4), "a": 0.06, "h": 0.12, "r": 0.12, "suppress": 0.4},
    "brow_flash_big": {"shapes": _f(BRW_Surprised=0.6, EYE_Surprised=0.4), "a": 0.06, "h": 0.15, "r": 0.15,
                       "suppress": 0.4},
    "double_take": {"shapes": _f(BRW_Surprised=0.5), "head": (2, 0, 0), "a": 0.06, "h": 0.18, "r": 0.15},
    "greet_flash": {"shapes": _f(BRW_Surprised=0.8, EYE_Spread=0.3), "head": (-2, 0, 0), "a": 0.06, "h": 0.14,
                    "r": 0.15},
    "lips_up": {"shapes": _f(MTH_Fun=0.4), "joyful": _f(EYE_Joy=0.15), "a": 0.15, "h": 0.25, "r": 0.3},
    "pull_back": {"shapes": _f(MTH_Angry=0.3), "head": (-2.5, 0, 0), "a": 0.12, "h": 0.2, "r": 0.3},
    "frown": {"shapes": _f(BRW_Angry=0.5), "a": 0.10, "h": 0.2, "r": 0.3},
    "press": {"shapes": _f(MTH_Small=0.4), "head": (-4, 0, 0), "a": 0.15, "h": 0.6, "r": 0.4, "gaze_held": True},
    "cant_handle": {"shapes": _f(BRW_Sorrow=0.7), "head": (4, 0, 0), "a": 0.2, "h": 0.6, "r": 0.5,
                    "look": ((12, 14), 0.8)},
    "blame_them": {"shapes": _f(EYE_Close=0.35), "head": (-3, 0, 0), "a": 0.2, "h": 0.6, "r": 0.4},
    "tense": {"shoulders": 1.5, "pose_hold": 1.0, "pose_attack": 0.15, "pose_release": 0.35, "breath": 0.4},
}

# Leaks: a short pulse through the region that feeling escapes from (leak layer, slot "leak", curve felt).
# Attack 0.07, hold U(0.12, 0.25), release U(0.15, 0.25); intensity 0.45 + 0.35 x gap. Raised from the spec where
# the legibility test failed (contract: raise the region's weights, keep the formula): the lid leaks (envy 0.35,
# relief 0.45) so they differ from the eye-smile ones, and embarrassment (see below).
_SORROW_LEAK = {"shapes": _f(BRW_Sorrow=0.55), "nudges": [(0.0, 0, 8), (0.4, 0, -8)]}  # inner brows, a gaze drop
# Fear's eyes: raised from 0.6/0.3, which at a live gap (intensity about 0.57) widened them by under 2 px.
_FEAR_LEAK = {"shapes": _f(EYE_Spread=1.0, EYE_Surprised=0.5), "then": [("inhale", 0.5, 0.0)], "breath": 0.4}
_ANGER_LEAK = {"shapes": _f(BRW_Angry=0.6), "gaze_hold": 2.0, "ramps": [("blinks_per_minute", 0.3, 2.0)]}  # a stare
_JOY_LEAK = {"shapes": _f(EYE_Joy=0.35, MTH_Fun=0.6, MTH_Small=0.4)}  # a smile pressed back
_LONGING_LEAK = {"shapes": _f(EYE_Close=0.35), "gaze_hold": 1.0, "then": [("inhale", 0.4, 0.2)]}  # the look lingers
LEAKS: dict[str, dict] = {
    "sadness": _SORROW_LEAK, "shame": _SORROW_LEAK,
    "fear": _FEAR_LEAK, "anxiety": _FEAR_LEAK,
    "anger": _ANGER_LEAK, "irritation": _ANGER_LEAK,
    "amusement": _JOY_LEAK, "joy": _JOY_LEAK, "warmth": _JOY_LEAK,
    "envy": _LONGING_LEAK, "longing": _LONGING_LEAK,
    "contempt": {"shapes": _f(EYE_Close_L=0.3), "head": (-3, 0, 0)},  # one lid down, the chin up
    # A smile pressed away: MTH_Small and MTH_Fun cancel to nothing at the medium shot, so the eyes smile a little.
    "embarrassment": {"shapes": _f(MTH_Small=0.5, MTH_Fun=0.6, EYE_Joy=0.3), "hold": 0.6,
                      "nudges": [(0.0, 0, 10), (0.6, 0, -10)]},
    "guilt": {"shapes": _f(BRW_Sorrow=0.4), "looks": [(0.05, "chat", {}), (0.45, "camera", {})]},  # a glance back
    "pride": {"shapes": _f(MTH_Fun=0.6), "head": (-4, 0, 0)},  # only at the end of her line
    "relief": {"shapes": _f(EYE_Close=0.45), "then": [("exhale", 0.5, 0.05)]},  # the exhale shows
}

# Social smiles: no feeling needed (display layer, slot "social", deliberate; never EYE_Joy). A closed-lip smile
# doesn't register at the medium shot (the spec's MTH_Fun 0.8 + MTH_Joy 0.15 changes 82 px of the face, 300 needed),
# so both show a little teeth (MTH_Joy 0.3) and lift the lower lids (EYE_Fun), the way a polite smile does.
SOCIAL: dict[str, dict] = {
    "greet": {"shapes": _f(MTH_Fun=0.85, MTH_Joy=0.3, EYE_Fun=0.5), "attack": 0.1, "hold": (0.8, 1.2), "release": 0.25,
              "then": [("nod", 0.3, 0.1)]},  # greetings, thanks, goodbyes
    "qualify": {"shapes": _f(MTH_Fun=0.8, MTH_Joy=0.3, EYE_Fun=0.5), "attack": 0.1, "hold": 0.5, "release": 0.2},  # "it's fine"
}

# Laughs and chuckles (slot "sound", full mouth; the hold is the sound's length). Felt ones reach the eyes.
LAUGHS: dict[str, dict] = {
    "laugh": {
        "social": {"layer": "display", "curve": "deliberate", "shapes": _f(MTH_Joy=0.6, EYE_Fun=0.4),
                   "head": (-6, 0, 0), "attack": 0.1, "release": 0.4},
        "felt": {"layer": "felt", "curve": "felt", "shapes": _f(MTH_Joy=0.6, EYE_Joy=0.6, BRW_Fun=0.3),
                 "head": (-6, 0, 3), "attack": 0.15, "release": 0.8}},
    "chuckle": {
        "social": {"layer": "display", "curve": "deliberate", "shapes": _f(MTH_Fun=0.6, MTH_Joy=0.3, EYE_Fun=0.3),
                   "head": (-2, 0, 0), "attack": 0.1, "release": 0.3},
        "felt": {"layer": "felt", "curve": "felt", "shapes": _f(MTH_Fun=0.6, MTH_Joy=0.3, EYE_Joy=0.35),
                 "head": (-2, 0, 2), "attack": 0.12, "release": 0.6}},
}

# The failed wink's squint: lids lopsided through the blink channel, plus a scrunched smile.
SQUINT_SMILE = {"shapes": _f(MTH_Fun=0.6, MTH_Small=0.2, BRW_Angry=0.2), "head": (0, 0, 4), "attack": 0.06,
                "hold": 0.35, "release": 0.2}

FAMILIES: dict[str, tuple[str, ...]] = {
    "bright": ("amusement", "joy", "pride", "relief", "warmth", "interest"),
    "hostile": ("irritation", "anger", "contempt"),
    "alarm": ("surprise", "fear", "anxiety"),
    "low": ("sadness", "shame", "guilt", "envy", "embarrassment"),
    "puzzled": ("confusion",),
}
FAMILY: dict[str, str] = {emotion: family for family, names in FAMILIES.items() for emotion in names}

ALIASES = {"sideeye": "side eye", "side-eye": "side eye", "eyeroll": "eye roll", "eye-roll": "eye roll",
           "think": "considering", "remember": "recall", "skeptic": "skeptical", "intrigued": "interest",
           "confused": "confusion", "tender": "warmth"}

# Recipes that don't read at the medium shot (the legibility test): the camera has to be this close.
SHOT_ONLY: dict[str, str] = {"hollow": "close"}
# fmt: on

# How long one display lasts (s): the engine's lengths, plus concern.
LENGTH: dict[str, tuple[float, float]] = {**_ENGINE_LENGTH, "concern": (2.0, 5.0)}
SIDED_GESTURES = ("tilt", "recoil", "shrug", "turn", "tilt_beat")  # strength signed by side
RAMP_SECONDS = 0.3  # ramp time in and out for the recipes' body ramps
MAX_PEAK = 5.0  # no peak holds longer than this
EYE_PAIRS = ("Fcl_EYE_Close", "Fcl_EYE_Joy")  # both-eye shapes that also exist as _L / _R


def _mirror(shape: str, side: float) -> str:
    """One-sided shapes are written for side +1 (her left); side -1 swaps left and right."""
    if side > 0:
        return shape
    if shape.endswith("_L"):
        return shape[:-2] + "_R"
    if shape.endswith("_R"):
        return shape[:-2] + "_L"
    return shape


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _r1(x: float) -> float:
    """Degrees, rounded to 0.1 (never -0.0)."""
    return round(x, 1) + 0.0


def _lasting(recipe: dict) -> dict:
    """A recipe's lasting face: a sequence (relief, embarrassment) is represented by its last phase."""
    if "phases" not in recipe:
        return recipe
    last = recipe["phases"][-1]
    return {**{k: v for k, v in recipe.items() if k != "phases"}, "shapes": last["shapes"],
            "head": last.get("head", (0, 0, 0))}


@dataclass
class Performance:
    name: str
    commands: list[dict]  # each carries "dt" (s after the start); looks also "gaze_hold" (s)
    side: float  # +1 as written, -1 mirrored
    peak_at: float  # s after the start when the face first reaches full strength
    ends_at: float  # s after the start when everything has released (math.inf for an open hold)
    gaze_until: float  # s after the start until which brain must not move the gaze
    moves_head: bool  # carries a head attitude (brain keeps phrase poses away from it)


class _Plan:
    """Collects one performance's commands and what brain needs to know about it."""

    def __init__(self, name: str, side: float) -> None:
        self.name, self.side = name, side
        self.commands: list[dict] = []
        self.peak_at: float | None = None
        self.ends_at = 0.0
        self.gaze_until = 0.0
        self.moves_head = False

    def add(self, dt: float, cmd: str, ends: float = 0.0, **fields) -> dict:
        command = {"cmd": cmd, **fields, "dt": round(max(0.0, dt), 3)}
        self.commands.append(command)
        self.ends_at = max(self.ends_at, dt + ends)
        return command

    def face(self, dt: float, layer: str, slot: str, shapes: dict[str, float], intensity: float, attack: float,
             hold: float, release: float, curve: str, *, max_hold: float | None = None, full_mouth: bool = False,
             head: list[float] | None = None, chest: float = 0.0, shoulders: float = 0.0) -> dict:
        fields: dict = {"layer": layer, "slot": slot, "shapes": shapes, "intensity": round(_clamp(intensity, 0.0, 1.3), 3),
                        "attack": round(attack, 3), "hold": -1 if hold < 0 else round(hold, 3),
                        "release": round(release, 3), "curve": curve}
        if hold < 0 and max_hold is not None:
            fields["max_hold"] = round(max_hold, 3)
        if full_mouth:
            fields["full_mouth"] = True
        if head is not None and any(abs(a) >= 0.05 for a in head):
            fields["head"] = head
        if abs(chest) >= 0.05:
            fields["chest"] = round(chest, 2)
        if abs(shoulders) >= 0.05:
            fields["shoulders"] = round(shoulders, 2)
        self.moves_head = self.moves_head or any(k in fields for k in ("head", "chest", "shoulders"))
        if self.peak_at is None:
            self.peak_at = dt + attack
        if hold < 0:
            end = math.inf if max_hold is None else attack + max_hold + release
        else:
            end = attack + hold + release
        return self.add(dt, "face_layer", ends=end, **fields)

    def look(self, dt: float, hold: float, **fields) -> None:
        self.add(dt, "look", ends=hold, **fields, gaze_hold=round(max(0.0, hold), 3))
        self.gaze_until = max(self.gaze_until, dt + hold)

    def done(self) -> Performance:
        self.commands.sort(key=lambda c: c["dt"])
        return Performance(self.name, self.commands, self.side, round(self.peak_at or 0.0, 3), self.ends_at,
                           round(self.gaze_until, 3), self.moves_head)


class Faces:
    """Builds performances. All randomness comes from the rng brain passes in (seeded), so a replay of the
    same events gives the same faces."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self._recent: deque[tuple[str, float]] = deque(maxlen=4)  # (put-on face, side) per performance

    # --- names ---------------------------------------------------------------

    @staticmethod
    def name(tag: str) -> str:
        return ALIASES.get(tag, tag)

    def kind(self, name: str) -> str | None:
        """"put_on", "felt", or None for anything else."""
        name = self.name(name)
        return "put_on" if name in PUT_ON else "felt" if name in FELT else None

    # --- performances ----------------------------------------------------------

    def put_on(self, name: str, *, energy: float, intensity: float = 1.0, hold: float | None = None,
               max_hold: float | None = None, overplay: bool = False, simulate: bool = False,
               side: float | None = None) -> Performance:
        """A face she makes on purpose (display/face). hold: None draws the recipe's hold (outside speech),
        a number is exact, -1 holds it open until face_end, a new face, or max_hold.
        overplay (strained): x 1.2 and a late start. simulate (overplaying human things): late and long."""
        name = self.name(name)
        recipe = PUT_ON[name]
        size = (0.85 + 0.35 * energy) * intensity
        last = next((s for n, s in reversed(self._recent) if n == name), None)
        if side is None:
            side = -last if last is not None else self._side()
        if last is not None:  # the same face again so soon: the other side, smaller
            size *= 0.65
        self._recent.append((name, side))
        start = 0.0
        if overplay:
            size *= 1.2
            start = self._u(0.15, 0.3)
        nominal = self._u(*recipe["hold"])
        sim = recipe.get("simulate", {}) if simulate else {}
        if simulate:
            start += 0.3
            nominal *= 1.6
        hold_v = nominal if hold is None else (-1.0 if hold < 0 else hold)
        attack = 0.25 if name in THINKING_FACES else 0.1
        plan = _Plan(name, side)
        head = self._head(recipe.get("head"), side, size)
        plan.face(start, "display", "face", self._posed_shapes(recipe["shapes"], side), size, attack, hold_v, 0.2,
                  "deliberate", max_hold=max_hold, head=head, chest=recipe.get("chest", 0.0),
                  shoulders=recipe.get("shoulders", 0.0))
        span = self._span(recipe, hold_v, nominal, max_hold)
        self._extras(plan, recipe, start, side, attack, span, attack + span + 0.5, 1.0, hold_v < 0)
        for gesture in sim.get("then", []):
            self._gesture(plan, start, side, *gesture)
        if "slow_blink_at" in sim:
            plan.add(start + sim["slow_blink_at"], "blink_mode", mode="slow", ends=0.6)
        return plan.done()

    def felt(self, name: str, intensity: float, *, head_intensity: float | None = None, hold: float | None = None,
             max_hold: float | None = None, deliberate: bool = False, eyes: bool = False, slot: str | None = None,
             side: float | None = None) -> Performance:
        """What she feels, shown (felt layer). intensity goes to Godot (it multiplies the shapes); the head
        follows clamp(head_intensity or intensity, 0.75, 1.25). deliberate: the intensified version (snaps on,
        holds 50% longer). eyes: the sad smile reaches her eyes."""
        name = self.name(name)
        recipe = FELT[name]
        if eyes and "eyes" not in recipe:
            raise ValueError(f"eyes=True is only for the sad smile, not {name!r}")
        side = self._side() if side is None else side
        if name == "embarrassment":
            return self._embarrassment(intensity, side, slot or "felt")
        if name == "relief":
            return self._relief(intensity, head_intensity, side, slot or "felt", hold)
        head_factor = _clamp(intensity if head_intensity is None else head_intensity, 0.75, 1.25)
        shapes = dict(recipe["shapes"])
        if eyes:
            shapes.update(recipe["eyes"])
        if name == "amusement":
            shapes["Fcl_MTH_Joy"] = round(0.1 + 0.3 * _clamp((intensity - 0.4) / 0.6), 3)
            if intensity >= 0.85:
                shapes["Fcl_EYE_Joy"] = 0.8
        curve = "deliberate" if deliberate else "felt"
        attack = 0.1 if deliberate else recipe["attack"] if "attack" in recipe else self._u(0.35, 0.6)
        release = 0.2 if deliberate else recipe["release"] if "release" in recipe else self._u(1.0, 2.5)
        nominal, length = self._felt_hold(name, recipe, attack)
        if deliberate:
            nominal = min(MAX_PEAK, nominal * 1.5)
            length = attack + nominal + 0.5
        hold_v = recipe.get("hold") if isinstance(recipe.get("hold"), (int, float)) else nominal
        if hold is not None:
            hold_v = -1.0 if hold < 0 else hold
            if hold >= 0:
                length = attack + hold + 0.5
        plan = _Plan(name, side)
        start = 0.0
        full_mouth = name == "amusement" and intensity >= 0.85
        plan.face(start, "felt", slot or recipe.get("slot", "felt"), self._shapes(shapes, side), intensity, attack,
                  hold_v, release, curve, max_hold=max_hold, full_mouth=full_mouth,
                  head=self._head(recipe.get("head"), side, head_factor), chest=recipe.get("chest", 0.0) * head_factor,
                  shoulders=recipe.get("shoulders", 0.0))
        span = self._span(recipe, hold_v, nominal, max_hold)
        if hold_v < 0:
            length = attack + span + 0.5
        self._extras(plan, recipe, start, side, attack, span, length, head_factor, hold_v < 0)
        if name == "amusement" and intensity >= 0.6:
            if intensity >= 0.85:
                self._gesture(plan, start, side, "laugh", 0.7, 0.2)
            else:
                self._gesture(plan, start, side, "chuckle", 0.6, 0.2)
        if name == "fear":
            frozen = 0.5 + 0.9 * _clamp(2 * intensity - 1)
            plan.add(start, "freeze", ends=frozen + 0.5, seconds=round(frozen, 3), breath=round(frozen, 3), exhale=0.5)
            plan.add(start + frozen, "body_ramp", ends=6.0 + RAMP_SECONDS, param="breaths_per_minute", value=1.4,
                     seconds=RAMP_SECONDS, back_after=6.0)
            plan.add(start + frozen, "body_ramp", ends=6.0 + RAMP_SECONDS, param="breath_depth", value=0.7,
                     seconds=RAMP_SECONDS, back_after=6.0)
        return plan.done()

    def leak(self, emotion: str, gap: float, *, side: float | None = None) -> Performance:
        """A short, strong pulse through the region a hidden feeling escapes from. Never adds a cover:
        the squelch is brain's job. KeyError for feelings that are never hidden (surprise, interest,
        confusion)."""
        recipe = LEAKS[emotion]
        side = self._side() if side is None else side
        intensity = 0.45 + 0.35 * _clamp(gap)
        attack = 0.07
        hold = recipe["hold"] if "hold" in recipe else self._u(0.12, 0.25)
        release = self._u(0.15, 0.25)
        shapes = {s: w for s, w in self._shapes(recipe["shapes"], side).items() if w * intensity >= 0.05}
        plan = _Plan(f"leak: {emotion}", side)
        plan.face(0.0, "leak", "leak", shapes, intensity, attack, hold, release, "felt",
                  head=self._head(recipe.get("head"), side, 1.0))
        self._extras(plan, recipe, 0.0, side, attack, hold, attack + hold + release, 1.0, False)
        return plan.done()

    def check(self, name: str, *, size: float = 1.0, joyful: bool = False, side: float | None = None) -> Performance:
        """One step of the reading face (felt/check). size scales the weights and the head."""
        recipe = CHECKS[name]
        side = self._side() if side is None else side
        plan = _Plan(name, side)
        if name == "tense":
            plan.add(0.0, "head_pose", ends=recipe["pose_attack"] + recipe["pose_hold"] + recipe["pose_release"],
                     pitch=0.0, yaw=0.0, roll=0.0, hold=recipe["pose_hold"], attack=recipe["pose_attack"],
                     release=recipe["pose_release"], slot="tense", shoulders=round(recipe["shoulders"] * size, 2))
            plan.moves_head = True
            plan.add(0.0, "hold_breath", ends=recipe["breath"], seconds=recipe["breath"])
            plan.peak_at = recipe["pose_attack"]
            return plan.done()
        shapes = dict(recipe["shapes"])
        if joyful and "joyful" in recipe:
            shapes.update(recipe["joyful"])
        shapes = self._shapes({s: w * size for s, w in shapes.items()}, side)
        head = self._head(recipe.get("head"), side, size)
        a, h, r = recipe["a"], recipe["h"], recipe["r"]
        plan.face(0.0, "felt", "check", shapes, 1.0, a, h, r, "felt", head=head)
        if "suppress" in recipe:
            plan.add(0.0, "blink_mode", ends=recipe["suppress"], mode="suppress", seconds=recipe["suppress"])
        if recipe.get("gaze_held"):
            plan.gaze_until = a + h
        if "look" in recipe:
            (yaw, pitch), length = recipe["look"]
            plan.look(0.0, length, yaw=_r1(self._angle(yaw) * side), pitch=_r1(self._angle(pitch)))
            plan.look(length, 0.0, target="camera")
        return plan.done()

    def social(self, kind: str) -> Performance:
        """A social smile (display/social): greetings, thanks and goodbyes ("greet"), or the "it's fine" after
        a leak ("qualify"). It needs no feeling and never reaches EYE_Joy."""
        recipe = SOCIAL[kind]
        side = self._side()
        plan = _Plan(f"social: {kind}", side)
        hold = self._draw(recipe["hold"])
        plan.face(0.0, "display", "social", self._shapes(recipe["shapes"], side), 1.0, recipe["attack"], hold,
                  recipe["release"], "deliberate")
        for gesture in recipe.get("then", []):
            self._gesture(plan, 0.0, side, *gesture)
        return plan.done()

    def laugh(self, kind: str, length: float, *, felt: bool) -> Performance:
        """The face of a [laugh] or [chuckle] (slot "sound", full mouth) for `length` s. Felt (amusement
        >= 0.4): it reaches her eyes; otherwise a social laugh, eyes open. The gesture is brain's."""
        recipe = LAUGHS[kind]["felt" if felt else "social"]
        side = self._side()
        plan = _Plan(f"{kind} ({'felt' if felt else 'social'})", side)
        plan.face(0.0, recipe["layer"], "sound", self._shapes(recipe["shapes"], side), 1.0, recipe["attack"],
                  max(0.0, length), recipe["release"], recipe["curve"], full_mouth=True,
                  head=self._head(recipe["head"], side, 1.0))
        return plan.done()

    def blend(self, negative: str, neg_intensity: float, positive: str, pos_intensity: float, *,
              side: float | None = None) -> Performance:
        """Two feelings at once, split by region (felt/felt): the negative one in the brows and upper lids,
        the positive one in the mouth and the eye-smile, each at 70%. Jo's kindness: sad inner brows with a
        real eye-smile."""
        neg, pos = _lasting(FELT[negative]), _lasting(FELT[positive])
        side = self._side() if side is None else side
        shapes: dict[str, float] = {}
        for shape, w in neg["shapes"].items():
            if shape.startswith("Fcl_BRW_") or shape.startswith(("Fcl_EYE_Close", "Fcl_EYE_Sorrow", "Fcl_EYE_Angry",
                                                                 "Fcl_EYE_Spread", "Fcl_EYE_Surprised")):
                shapes[shape] = shapes.get(shape, 0.0) + w * 0.7 * neg_intensity
        for shape, w in pos["shapes"].items():
            if shape.startswith(("Fcl_MTH_", "Fcl_EYE_Joy", "Fcl_EYE_Fun")):
                shapes[shape] = shapes.get(shape, 0.0) + w * 0.7 * pos_intensity
        strong, strong_name = (neg, negative) if neg_intensity >= pos_intensity else (pos, positive)
        head_factor = _clamp(max(neg_intensity, pos_intensity), 0.75, 1.25)
        attack, release = self._u(0.35, 0.6), self._u(1.0, 2.5)
        hold, length = self._felt_hold(strong_name, strong, attack)
        plan = _Plan(f"blend: {negative} + {positive}", side)
        plan.face(0.0, "felt", "felt", self._shapes(shapes, side), 1.0, attack, hold, release, "felt",
                  head=self._head(strong.get("head"), side, head_factor), chest=strong.get("chest", 0.0))
        gaze_only = {k: strong[k] for k in ("gaze", "gaze_mode", "gaze_at", "back", "glide", "gaze_hold", "looks")
                     if k in strong}
        self._extras(plan, gaze_only, 0.0, side, attack, hold, length, head_factor, False)
        return plan.done()

    def failed_wink(self, variant: str, side: float) -> Performance:
        """Her clumsy wink: "shut" closes both eyes for 0.25 s; "squint" closes the lids lopsided (the side
        eye 0.7, the other 0.4) with a scrunched smile."""
        plan = _Plan(f"failed wink: {variant}", side)
        if variant == "shut":
            plan.add(0.0, "blink_mode", ends=0.5, mode="fail_wink", variant="shut")
            plan.peak_at = 0.07
        elif variant == "squint":
            plan.add(0.0, "blink_mode", ends=0.6, mode="fail_wink", variant="squint",
                     side="left" if side > 0 else "right")
            r = SQUINT_SMILE
            plan.face(0.0, "display", "slip", self._shapes(r["shapes"], side), 1.0, r["attack"], r["hold"],
                      r["release"], "deliberate", head=self._head(r["head"], side, 1.0))
        else:
            raise KeyError(variant)
        return plan.done()

    # --- sequences ---------------------------------------------------------------

    def _relief(self, intensity: float, head_intensity: float | None, side: float, slot: str,
                hold: float | None) -> Performance:
        recipe = FELT["relief"]
        first, second = recipe["phases"]
        head_factor = _clamp(intensity if head_intensity is None else head_intensity, 0.75, 1.25)
        plan = _Plan("relief", side)
        plan.face(first["at"], "felt", slot, self._shapes(first["shapes"], side), intensity, first["attack"],
                  first["hold"], 0.5, "felt", head=self._head(first["head"], side, head_factor))
        attack, release = self._u(0.35, 0.6), self._u(1.0, 2.5)
        total = self._u(*LENGTH["relief"])
        hold_v = max(0.3, min(MAX_PEAK, total - second["at"] - attack - 0.5)) if hold is None else hold
        plan.face(second["at"], "felt", slot, self._shapes(second["shapes"], side), intensity, attack, hold_v,
                  release, "felt", head=self._head(second["head"], side, head_factor))
        self._extras(plan, recipe, 0.0, side, first["attack"], hold_v, total, head_factor, False)
        return plan.done()

    def _embarrassment(self, intensity: float, side: float, slot: str) -> Performance:
        """Gaze down within 0.3 s, a smile she presses away, head away, one or two glances back."""
        a, b = FELT["embarrassment"]["phases"]
        total = self._u(*LENGTH["embarrassment"])
        head_factor = _clamp(intensity, 0.75, 1.25)
        plan = _Plan("embarrassment", side)
        plan.add(0.05, "blink_mode", ends=0.9, mode="flutter")
        plan.face(a["at"], "felt", slot, self._shapes(a["shapes"], side), intensity, a["attack"], a["hold"], 0.5,
                  "felt")
        plan.face(b["at"], "felt", slot, self._shapes(b["shapes"], side), intensity, b["attack"],
                  self._draw(b["hold"]), b["release"], "felt", head=self._head(b["head"], side, head_factor))
        down = {"yaw": _r1(self._angle(15) * side * head_factor), "pitch": _r1(self._angle(15) * head_factor)}
        first = self._u(1.2, 1.6)
        glances = 2 if self.rng.random() < 0.5 else 1
        plan.look(0.0, first, **down)
        t = first
        for i in range(glances):
            back = self._u(0.3, 0.5)
            plan.look(t, back, target="camera")  # a glance back at you
            t += back
            stay = self._u(0.8, 1.2) if i + 1 < glances else max(0.3, total - t)
            plan.look(t, stay, **down)  # then down again
            t += stay
        plan.look(t, 0.0, target="camera")
        return plan.done()

    # --- shared pieces -----------------------------------------------------------

    def _extras(self, plan: _Plan, recipe: dict, start: float, side: float, attack: float, span: float,
                length: float, factor: float, is_open: bool) -> None:
        """Gaze, gestures, blinks, breath and ramps of a recipe, timed from the face's start.
        span: the time at the peak (the hold, or its stand-in when held open); length: the display's length;
        factor: scales the gaze angles (head_intensity)."""
        opened = recipe.get("open", {}) if is_open else {}
        gaze_hold = self._gaze_hold(recipe.get("gaze_hold"), attack + span, length)
        returns_at = self._gaze(plan, recipe, start, side, factor, gaze_hold, attack + span)
        for gesture in recipe.get("then", []):
            self._gesture(plan, start, side, *gesture)
        for gesture in recipe.get("at_return", []):
            self._gesture(plan, start, side, gesture[0], gesture[1], returns_at - start)
        for at, yaw, pitch in recipe.get("nudges", []):
            plan.add(start + at, "nudge", yaw=yaw, pitch=pitch)
        if "nudges" in recipe:
            plan.gaze_until = max(plan.gaze_until, start + recipe["nudges"][-1][0])
        blink = recipe.get("blink")
        if isinstance(blink, tuple) and blink[0] == "slow":
            at = self._draw(opened["blink_at"]) if "blink_at" in opened else attack + self._draw(blink[1]) * span
            plan.add(start + at, "blink_mode", ends=0.6, mode="slow")
        elif isinstance(blink, tuple) and blink[0] == "suppress":
            seconds = attack + span if blink[1] == "hold" else length
            plan.add(start, "blink_mode", ends=seconds, mode="suppress", seconds=round(seconds, 3))
        elif blink == "flutter":
            plan.add(start + 0.05, "blink_mode", ends=0.9, mode="flutter")
        if "breath" in recipe:
            plan.add(start, "hold_breath", ends=recipe["breath"], seconds=recipe["breath"])
        if recipe.get("freeze"):
            plan.add(start, "freeze", ends=attack + span + 0.5, seconds=round(attack + span, 3),
                     breath=round(attack + span, 3), exhale=0.0)
        for param, value, back in recipe.get("ramps", []):
            if back == "hold":
                back_after = attack + span
            elif back == "length":
                back_after = length
            elif back == "stare":
                back_after = gaze_hold
            else:
                back_after = back
            plan.add(start, "body_ramp", ends=back_after + RAMP_SECONDS, param=param, value=value,
                     seconds=RAMP_SECONDS, back_after=round(back_after, 3))
        if recipe.get("gaze_hold") is not None and "looks" not in recipe and recipe.get("gaze") != "camera":
            plan.gaze_until = max(plan.gaze_until, start + gaze_hold)  # the gaze stays where it is (a leak's stare)

    def _gaze(self, plan: _Plan, recipe: dict, start: float, side: float, factor: float, gaze_hold: float,
              peak_end: float) -> float:
        """The recipe's looks. Returns when the eyes come back to the camera (for at_return)."""
        if "looks" in recipe:
            return self._script(plan, recipe["looks"], start, side, factor, peak_end)
        gaze = recipe.get("gaze")
        if gaze is None:
            return start
        if gaze == "fixed":  # the eyes stay where they are (a startle)
            plan.gaze_until = max(plan.gaze_until, start + peak_end)
            return start
        if gaze in ("camera", "chat"):
            plan.look(start, gaze_hold, target=gaze)
            return start
        at = start + recipe.get("gaze_at", 0.0)
        back = self._u(*recipe["back"])
        look = {"yaw": _r1(self._angle(gaze[0]) * side * factor), "pitch": _r1(self._angle(gaze[1]) * factor)}
        if recipe.get("gaze_mode") == "eyes":
            look["mode"] = "eyes"
        plan.look(at, back, **look)
        ret: dict = {"target": "camera"}
        if "glide" in recipe:
            ret["glide"] = recipe["glide"]
        plan.look(at + back, recipe.get("glide", 0.0), **ret)
        return at + back

    def _script(self, plan: _Plan, looks: list, start: float, side: float, factor: float, peak_end: float) -> float:
        times, t = [], 0.0
        for at, _, _ in looks:
            if isinstance(at, tuple) and at[0] == "+":
                t = t + self._u(at[1], at[2])
            else:
                t = self._draw(at)
            times.append(t)
        returns_at = start
        for i, ((_, target, options), t) in enumerate(zip(looks, times)):
            if i + 1 < len(times):
                hold = times[i + 1] - t
            elif options.get("hold") == "hold":
                hold = max(0.0, peak_end - t)
            else:
                hold = options.get("glide", 0.0)
            if target == "stay":
                plan.gaze_until = max(plan.gaze_until, start + t + hold)
                continue
            look: dict = {}
            if target in ("camera", "chat"):
                look["target"] = target
                if "offset" in options:
                    look["offset"] = [_r1(options["offset"][0] * side), _r1(options["offset"][1])]
                if target == "camera":
                    returns_at = start + t
            else:
                look["yaw"] = _r1(self._angle(target[0]) * side * factor)
                look["pitch"] = _r1(self._angle(target[1]) * factor)
            if "glide" in options:
                look["glide"] = options["glide"]
            if options.get("mode") == "eyes":
                look["mode"] = "eyes"
            plan.look(start + t, hold, **look)
        return returns_at

    def _gesture(self, plan: _Plan, start: float, side: float, name: str, strength: float, at,
                 duration: float | None = None) -> None:
        at = self._timing(at, plan, start)
        if name == "blink":
            plan.add(start + at, "blink", ends=0.3)
        elif name == "inhale":
            plan.add(start + at, "inhale", ends=0.45, strength=strength)
        else:
            signed = strength * side if name in SIDED_GESTURES else strength
            fields: dict = {"name": name, "strength": round(signed, 3)}
            if duration is not None:
                fields["duration"] = duration
            plan.add(start + at, "gesture", ends=duration or 1.0, **fields)

    def _timing(self, at, plan: _Plan, start: float) -> float:
        """A gesture time from the face's start: s, (lo, hi), or ("+", lo, hi) after the previous gesture."""
        if isinstance(at, tuple) and at[0] == "+":
            gestures = [c["dt"] - start for c in plan.commands if c["cmd"] == "gesture"]
            return (gestures[-1] if gestures else 0.0) + self._u(at[1], at[2])
        return self._draw(at)

    def _gaze_hold(self, spec, peak_end: float, length: float) -> float:
        if spec is None:
            return peak_end
        if spec == "length":
            return length
        if isinstance(spec, tuple) and spec[0] == "length":
            return length * spec[1]
        return self._draw(spec)

    def _felt_hold(self, name: str, recipe: dict, attack: float) -> tuple[float, float]:
        """(hold, length): the recipe's hold, or a draw from LENGTH minus attack minus 0.5."""
        hold = recipe.get("hold")
        if isinstance(hold, tuple):
            hold = self._u(*hold)
            return hold, attack + hold + 0.5
        if isinstance(hold, (int, float)):  # open by design (thinking): a stand-in for timings
            return 3.0, attack + 3.5
        length = self._u(*LENGTH[name])
        return max(0.3, min(MAX_PEAK, length - attack - 0.5)), length

    @staticmethod
    def _span(recipe: dict, hold: float, nominal: float, max_hold: float | None) -> float:
        """The time at the peak that the extras are timed against; held open, the recipe's in-speech value
        (deadpan and suspicious: 3 s) or the outside-speech hold, never past max_hold."""
        if hold >= 0:
            return hold
        span = recipe.get("open", {}).get("hold", nominal)
        return min(span, max_hold) if max_hold is not None else span

    def _posed_shapes(self, shapes: dict[str, float], side: float) -> dict[str, float]:
        """Varied and mirrored, then lopsided: a both-eye EYE_Close or EYE_Joy of weight w becomes w on her
        side and 0.75 w on the other; a face with neither gets EYE_Close on her side at 0.12."""
        out: dict[str, float] = {}
        split = False
        for shape, weight in shapes.items():
            w = weight * self._u(0.92, 1.08)
            if shape in EYE_PAIRS:
                split = True
                near, far = _mirror(shape + "_L", side), _mirror(shape + "_R", side)
                out[near] = out.get(near, 0.0) + w
                out[far] = out.get(far, 0.0) + 0.75 * w
            else:
                out[_mirror(shape, side)] = out.get(_mirror(shape, side), 0.0) + w
        if not split:
            lid = _mirror("Fcl_EYE_Close_L", side)
            out[lid] = out.get(lid, 0.0) + 0.12
        return {s: round(min(1.0, w), 3) for s, w in out.items()}

    def _shapes(self, shapes: dict[str, float], side: float) -> dict[str, float]:
        """Varied (x U(0.92, 1.08)), mirrored, capped at 1."""
        return {_mirror(s, side): round(min(1.0, w * self._u(0.92, 1.08)), 3) for s, w in shapes.items()}

    def _head(self, head: tuple | None, side: float, factor: float) -> list[float] | None:
        if head is None:
            return None
        pitch, yaw, roll = head
        factor = _clamp(factor, 0.75, 1.25)
        return [_r1(self._angle(pitch) * factor), _r1(self._angle(yaw) * factor * side),
                _r1(self._angle(roll) * factor * side)]

    def _angle(self, a: float) -> float:
        return a * self._u(0.85, 1.15)

    def _side(self) -> float:
        return self.rng.choice((1.0, -1.0))

    def _u(self, lo: float, hi: float) -> float:
        return self.rng.uniform(lo, hi)

    def _draw(self, v) -> float:
        return self._u(*v) if isinstance(v, tuple) else float(v)
