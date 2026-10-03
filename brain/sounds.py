"""Finds where the voice really made the sounds its tags asked for ([laugh], [sigh]...).

Chatterbox doesn't say where it laughed, sometimes skips a tag (often one at the
very end of a sentence), and its laughs are breathy enough that the phoneme
recognizer hears them as syllables ("h ə h ɔ"). So we compare what she should
have said with what was heard: espeak-ng gives the expected phonemes of the
words, alignment finds where the words before the tag end and the words after
it begin. If that gap is longer than the punctuation explains and has sound in
it, that's the laugh, with its real start and length. Otherwise the voice
skipped it, and she shouldn't act one out.
"""

import difflib
import re
import subprocess
from functools import lru_cache

import numpy as np

_IGNORE = set("ˈˌːˑ")  # stress and length marks: not used for matching
_RATE = 100  # level measurements per second
_MIN_EXTRA = 0.35  # seconds of gap beyond the punctuation pause
# Sound in the gap, in dB below the speech level, and how much of it is needed:
# laughs and coughs are loud; sighs and sniffs are just breath.
_LOUD = (-21.0, 0.3)
_BREATHY = (-42.0, 0.15)
BREATHY_TAGS = {"sigh", "sniff", "shush"}


@lru_cache(maxsize=512)
def _expected(text: str) -> tuple[str, ...]:
    """The phonemes espeak-ng expects for `text`, one character each."""
    if not re.search(r"\w", text):
        return ()
    out = subprocess.run(["espeak-ng", "-q", "--ipa", "--sep= ", "-v", "en-us", text],
                         capture_output=True, text=True, check=True).stdout
    return tuple(c for c in out if c not in _IGNORE and not c.isspace())


def _pause_after(text: str) -> float:
    """How long a natural pause the punctuation before a tag would cause."""
    end = text.rstrip()
    if end.endswith(("?", ".", "!")):
        return 0.5
    if end.endswith((",", ";", ":")):
        return 0.25
    return 0.08


def _level_db(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Loudness per 10 ms, in dB relative to the speech level (95th percentile)."""
    hop = sample_rate // _RATE
    n = len(audio) // hop
    rms = np.sqrt((audio[: n * hop].reshape(n, hop).astype(np.float64) ** 2).mean(1))
    return 20.0 * np.log10(rms / max(np.percentile(rms, 95), 1e-9) + 1e-9)


def locate(spoken: str, tags: list[tuple[int, str]], heard: list[tuple[float, str]],
           audio: np.ndarray, sample_rate: int) -> list[tuple[float, float] | None]:
    """For each (offset, name) tag in `spoken` (the sentence without tags), the
    (start, end) of its sound in the audio, or None if the voice skipped it.
    heard: recognized phonemes as (start time, token)."""
    chars = [(t, c) for t, token in heard for c in token if c not in _IGNORE]
    match = difflib.SequenceMatcher(a=[c for _, c in chars], b=_expected(spoken), autojunk=False)
    # Only runs of 2+ matching phonemes count; single matches are often coincidences.
    pairs = [(m.a + i, m.b + i) for m in match.get_matching_blocks() if m.size >= 2 for i in range(m.size)]
    level = _level_db(audio, sample_rate)
    audible = np.flatnonzero(level > _BREATHY[0])
    last_sound = audible[-1] / _RATE if len(audible) else len(level) / _RATE

    found: list[tuple[float, float] | None] = []
    for offset, name in tags:
        before = spoken[:offset]
        boundary = len(_expected(before))
        said_before = [chars[i][0] for i, j in pairs if j < boundary]
        said_after = [chars[i][0] for i, j in pairs if j >= boundary]
        start = said_before[-1] + 0.08 if said_before else 0.0  # the last phoneme before the tag ends
        end = said_after[0] if said_after else last_sound
        threshold, needed = _BREATHY if name in BREATHY_TAGS else _LOUD
        sounding = np.flatnonzero(level[int(start * _RATE):int(end * _RATE)] > threshold)
        extra = (end - start) - (_pause_after(before) if said_before else 0.0)
        if extra < _MIN_EXTRA or len(sounding) / _RATE < needed:
            found.append(None)
            continue
        # Trim to where the sound actually is inside the gap.
        found.append((start + sounding[0] / _RATE, start + (sounding[-1] + 1) / _RATE))
    return found
