"""Listen to a synthesized sentence and work out what the body should do with it.

The TTS doesn't report when each sound happens, so we analyze its output:
  * visemes   a wav2vec2 phoneme recognizer turns the audio into timed IPA
              phonemes, mapped to VRM mouth weights (aa, ih, ou, ee, oh) per frame
  * sounds     where each [laugh]/[sigh]/... tag really happened (sounds.py);
              the mouth follows loudness there instead of lip-syncing it
  * beats     emphasized syllables (loudness peaks in speech), for nods and brows
  * time_at   maps "x% through the text" to audio time, for placing other tags
"""

import json
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import torch
from huggingface_hub import hf_hub_download
from transformers import Wav2Vec2ForCTC

from sounds import locate

VISEMES = ("aa", "ih", "ou", "ee", "oh")
FPS = 60

RECOGNIZER_REPO = "facebook/wav2vec2-lv-60-espeak-cv-ft"
_RECOGNIZER_RATE = 16000
_RECOGNIZER_FRAME = 0.02  # wav2vec2 emits one prediction per 20 ms

_INTERNAL_RATE = 200  # Hz, tracks are built at 5 ms resolution
_SMOOTH_SIGMA = 0.025  # seconds, gaussian blur = coarticulation between phonemes
_LEAD = 0.03  # seconds, lips move slightly before the sound is heard
_MAX_PHONEME = 0.25  # seconds, longest a single recognized phoneme is held

# espeak IPA -> mouth shape. Anything not listed gets _DEFAULT_SHAPE.
# Bilabials (p, b, m) are intentionally empty = closed lips.
_SHAPES: dict[str, dict[str, float]] = {
    # open vowels
    "a": {"aa": 1.0},
    "ɑ": {"aa": 1.0},
    "æ": {"aa": 0.7, "ee": 0.4},
    "ʌ": {"aa": 0.7},
    "ɐ": {"aa": 0.6},
    "ɒ": {"oh": 0.8, "aa": 0.3},
    # central vowels
    "ə": {"aa": 0.35, "ee": 0.2},
    "ɚ": {"ou": 0.3, "ee": 0.3},
    "ɜ": {"ee": 0.5},
    "ɝ": {"ou": 0.3, "ee": 0.4},
    "ɵ": {"oh": 0.5},
    # front vowels
    "e": {"ee": 0.9},
    "ɛ": {"ee": 0.8, "aa": 0.2},
    "i": {"ih": 1.0},
    "ɪ": {"ih": 0.7},
    "ᵻ": {"ih": 0.6},
    "ɨ": {"ih": 0.6},
    "y": {"ou": 0.6, "ih": 0.3},
    # back / rounded vowels
    "u": {"ou": 1.0},
    "ʊ": {"ou": 0.7},
    "ʉ": {"ou": 0.8},
    "ɯ": {"ih": 0.4, "ou": 0.3},
    "o": {"oh": 1.0},
    "ɔ": {"oh": 0.9},
    "ø": {"oh": 0.6, "ou": 0.3},
    "œ": {"oh": 0.6, "ee": 0.2},
    # consonants with a visible lip shape
    "w": {"ou": 0.8},
    "ɹ": {"ou": 0.35},
    "r": {"ou": 0.3},
    "ʃ": {"ou": 0.5, "ih": 0.2},
    "ʒ": {"ou": 0.5, "ih": 0.2},
    "j": {"ih": 0.4},
    "f": {"ih": 0.15},
    "v": {"ih": 0.15},
    "s": {"ih": 0.3},
    "z": {"ih": 0.3},
    "θ": {"ee": 0.25},
    "ð": {"ee": 0.25},
    "l": {"aa": 0.25},
    "h": {"aa": 0.3},
    # lips closed
    "p": {},
    "b": {},
    "m": {},
    "ʔ": {},
}
_DEFAULT_SHAPE = {"aa": 0.2, "ee": 0.1}  # t, d, n, k, g, ŋ, ...
# Symbols inside recognizer tokens that don't change the mouth ("iː" -> "i").
_MODIFIERS = set("ːˑˈˌ̩̪̃ʲʰ͡")


def _shape_vector(phoneme: str) -> np.ndarray:
    shape = _SHAPES.get(phoneme, _DEFAULT_SHAPE)
    return np.array([shape.get(v, 0.0) for v in VISEMES], dtype=np.float32)


def _loudness(audio: np.ndarray, sample_rate: int, n: int) -> np.ndarray:
    """0..1 loudness envelope with n points at _INTERNAL_RATE."""
    hop = sample_rate // _INTERNAL_RATE
    frames = np.zeros(n * hop, dtype=np.float32)
    frames[: min(len(audio), len(frames))] = audio[: len(frames)]
    rms = np.sqrt(np.mean(frames.reshape(n, hop) ** 2, axis=1))
    loud = np.percentile(rms, 95)
    if loud < 1e-6:
        return np.zeros(n, dtype=np.float32)
    # Gate out the noise floor, then compress so quiet syllables still show.
    return np.clip((rms / loud - 0.08) / 0.92, 0.0, 1.0) ** 0.6


def _gaussian_blur(track: np.ndarray, sigma_frames: float) -> np.ndarray:
    radius = int(3 * sigma_frames)
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (x / sigma_frames) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(track, ((radius, radius), (0, 0)), mode="edge")
    return np.stack(
        [np.convolve(padded[:, c], kernel, mode="valid") for c in range(track.shape[1])],
        axis=1,
    )


@dataclass
class Analysis:
    visemes: np.ndarray  # (frames, 5) at FPS
    # Per sound tag: (start, end) seconds where the voice made it, or None if it
    # skipped it. None as a whole: not measured (no recognizer).
    sounds: list[tuple[float, float] | None] | None
    beats: list[tuple[float, float]]  # (time, strength 0..1)
    duration: float
    speech_cum: np.ndarray  # seconds of speech so far, per internal step

    def time_at(self, fraction: float) -> float:
        """Audio time by which `fraction` of the speech has been said."""
        total = self.speech_cum[-1]
        if total <= 0.0:
            return fraction * self.duration
        i = int(np.searchsorted(self.speech_cum, fraction * total))
        return min(i / _INTERNAL_RATE, self.duration)

    def pauses(self, min_len: float = 0.4) -> list[tuple[float, float]]:
        """(start, end) seconds of each stretch between words where no speech
        is heard, at least `min_len` long. The silence before the first word
        and after the last one doesn't count."""
        speech = np.diff(self.speech_cum, prepend=0.0) > 0.0
        heard = np.flatnonzero(speech)
        if heard.size == 0:
            return []
        out: list[tuple[float, float]] = []
        start = None
        for i in range(int(heard[0]), int(heard[-1]) + 1):
            if not speech[i] and start is None:
                start = i
            elif speech[i] and start is not None:
                if (i - start) / _INTERNAL_RATE >= min_len:
                    out.append((start / _INTERNAL_RATE, i / _INTERNAL_RATE))
                start = None
        return out


def analyze(phonemes: list[tuple[float, str]], audio: np.ndarray, sample_rate: int,
            sounds: list[tuple[float, float]] = ()) -> Analysis:
    """phonemes: (start seconds, IPA token) in order. Empty = loudness only.
    sounds: stretches that are laughs, sighs... rather than words."""
    duration = len(audio) / sample_rate
    n = int(np.ceil(duration * _INTERNAL_RATE)) + 1
    env = _loudness(audio, sample_rate, n)
    track = np.zeros((n, len(VISEMES)), dtype=np.float32)
    covered = np.zeros(n, dtype=bool)

    for k, (start, token) in enumerate(phonemes):
        end = phonemes[k + 1][0] if k + 1 < len(phonemes) else duration
        end = min(end, start + _MAX_PHONEME)
        # Multi-symbol tokens ("aɪ", "tʃ") split their time between the symbols.
        symbols = [c for c in token if c not in _MODIFIERS]
        step = (end - start) / max(1, len(symbols))
        for j, symbol in enumerate(symbols):
            i0 = int(round((start + j * step) * _INTERNAL_RATE))
            i1 = max(i0 + 1, int(round((start + (j + 1) * step) * _INTERNAL_RATE)))
            track[i0:i1] = _shape_vector(symbol)
            covered[i0:i1] = True

    # Laughs and sighs aren't words even if the recognizer heard "h ə h ɔ":
    # there the mouth follows the sound itself.
    for start, end in sounds:
        i0, i1 = int(start * _INTERNAL_RATE), int(end * _INTERNAL_RATE)
        track[i0:i1] = 0.0
        covered[i0:i1] = False

    # Sound with no phonemes (laughs, sighs, breaths): open with loudness.
    track[~covered, VISEMES.index("aa")] = env[~covered] * 0.7
    track[~covered, VISEMES.index("oh")] = env[~covered] * 0.2
    # Silence closes the mouth even if a phoneme was held too long.
    track *= np.clip(env * 4.0, 0.0, 1.0)[:, None]
    track = _gaussian_blur(track, _SMOOTH_SIGMA * _INTERNAL_RATE)

    # Sample at FPS, shifted so the mouth leads the audio by _LEAD.
    t_out = np.arange(int(np.ceil(duration * FPS)) + 1) / FPS + _LEAD
    t_src = np.arange(n) / _INTERNAL_RATE
    visemes = np.stack([np.interp(t_out, t_src, track[:, c]) for c in range(len(VISEMES))], axis=1)

    speech = covered & (env > 0.1) if phonemes else env > 0.1
    return Analysis(
        visemes=np.clip(visemes, 0.0, 1.0),
        sounds=None,
        beats=_beats(env, speech),
        duration=duration,
        speech_cum=np.cumsum(speech) / _INTERNAL_RATE,
    )


def _beats(env: np.ndarray, speech: np.ndarray) -> list[tuple[float, float]]:
    """Emphasized syllables: prominent loudness peaks inside speech."""
    smooth = _gaussian_blur(env[:, None], 0.03 * _INTERNAL_RATE)[:, 0]
    window = int(0.15 * _INTERNAL_RATE)
    candidates = []
    for i in range(1, len(smooth) - 1):
        if not speech[i] or smooth[i] < 0.45 or smooth[i] < smooth[i - 1] or smooth[i] < smooth[i + 1]:
            continue
        prominence = smooth[i] - smooth[max(0, i - window): i + window + 1].min()
        if prominence > 0.15:
            candidates.append((float(min(1.0, prominence / 0.5) * smooth[i]), i / _INTERNAL_RATE))
    # Strongest first, at least 0.35 s apart.
    beats: list[tuple[float, float]] = []
    for strength, t in sorted(candidates, reverse=True):
        if all(abs(t - other) >= 0.35 for other, _ in beats):
            beats.append((t, strength))
    return sorted(beats)


class PhonemeRecognizer:
    """wav2vec2 fine-tuned to output espeak IPA phonemes, with frame timings."""

    def __init__(self, device: str):
        vocab = json.loads(Path(hf_hub_download(RECOGNIZER_REPO, "vocab.json")).read_text())
        self._tokens = {index: token for token, index in vocab.items()}
        self._device = device
        self._dtype = torch.float16 if device == "cuda" else torch.float32
        self._model = Wav2Vec2ForCTC.from_pretrained(RECOGNIZER_REPO, dtype=self._dtype)
        self._model.to(device).eval()

    def phonemes(self, audio: np.ndarray, sample_rate: int) -> list[tuple[float, str]]:
        x = librosa.resample(audio, orig_sr=sample_rate, target_sr=_RECOGNIZER_RATE)
        x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
        with torch.inference_mode():
            logits = self._model(torch.from_numpy(x)[None].to(self._device, self._dtype)).logits[0]

        # Greedy CTC: a phoneme starts where the argmax changes to a real token.
        result = []
        previous = None
        for frame, index in enumerate(logits.argmax(-1).tolist()):
            token = self._tokens[index]
            if index != previous and not token.startswith("<"):
                result.append((frame * _RECOGNIZER_FRAME, token))
            previous = index
        return result

    def analyze(self, audio: np.ndarray, sample_rate: int, spoken: str = "",
                sound_tags: tuple[tuple[int, str], ...] = ()) -> Analysis:
        """sound_tags: (offset in `spoken`, name) of each [laugh]/[sigh]/... in the sentence."""
        heard = self.phonemes(audio, sample_rate)
        found = locate(spoken, list(sound_tags), heard, audio, sample_rate) if sound_tags else []
        result = analyze(heard, audio, sample_rate, sounds=[w for w in found if w])
        result.sounds = found
        return result
