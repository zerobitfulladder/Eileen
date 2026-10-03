"""Eileen server: the brain and voice behind the Godot avatar.

Godot (the body) connects over a WebSocket. This process decides what she does
(brain.py) and speaks with Chatterbox Turbo, one sentence at a time:

  Godot -> here   {"type": "hello", "targets": [...]}   body connected
                  {"type": "chat", "text": "name: ..."} a chat message: her mind reads it, then
                                                        the actor writes her reply
                  {"type": "say", "text": "..."}        say exactly this
                  {"type": "stop"}                      cut her off
                  {"type": "reset"}                     forget the chat history
                  {"type": "set", "name": "jo", "liking": 0.7, "familiarity": 0.8}
                                                        debug: set how she feels about someone
                  {"type": "perform", "tag": "skeptical"}  act out one tag now (debug)
                  {"type": "camera_test", "name": "close"} run one camera shot/move now (debug)
                  {"type": "event", "name": ...}        sentence_started / finished
                  {"type": "mood", "cinematic": 0.5}    camera: 0 locked-off .. 1 very cinematic
  here -> Godot   {"type": "cmd", "cmd": "model", "name": ...}
                                                        first, on every hello: the body to load
                                                        (models.toml, --model)
                  {"type": "cmd", "cmd": ...}           do this now (see avatar/link.gd)
                  {"type": "clip", ...} + binary PCM    a sentence: audio, visemes, timed commands
                  {"type": "end"}                       no more sentences for this reply
                  {"type": "catalog", ...}              what the debug dropdowns can test
                  {"type": "mind", ...}                 her inner state, up to 5 times a second (debug panel)
                  {"type": "stage", "stage": ...}       where a reply is: "appraiser" (her mind reads the
                                                        message), "mind" (it decided how she copes: move,
                                                        gist), "actor" (her line is being written), "voice"
                                                        (a sentence is being voiced); the demo's pipeline

Text can contain Chatterbox tags ([laugh], [sigh], [whispering]...) and stage
directions ([smile], [nod], [look at chat]...), which are acted out, not spoken.

Her mind (mind/, docs/mind.md) runs alongside: it reads every chat message
before she answers, decides how she copes, tells the actor how to behave, and
drives her body (resting face, posture, energy, what leaks) on its own clock.

    uv run server.py                  (in her default body, lucy)
    uv run server.py --model miku     (any body in models.toml)
"""

import os

os.environ.setdefault("TQDM_DISABLE", "1")  # chatterbox shows progress bars per sentence
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import argparse
import asyncio
import contextlib
import io
import json
import logging
import random
import time
import warnings
from collections.abc import AsyncIterator, Callable
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*pkg_resources.*")

import numpy as np
import torch
import transformers
import websockets
from chatterbox.tts_turbo import ChatterboxTurboTTS

from brain import Brain, SentencePlan, plan_sentence
from chat import DEFAULT_PROMPT, QUIET, ChatResponder
from llm import LLM, PROVIDERS, create_llm
from mind import Coping, Mind
from mind.appraisal import SelfCheck
from mind.guard import echoes, violations
from models import DEFAULT_MODEL, load_models
from text import SentenceStream, pronounce, split_pauses
from visemes import FPS, VISEMES, Analysis, PhonemeRecognizer, analyze

_LOGGER = logging.getLogger("eileen")



def set_voice(tts: ChatterboxTurboTTS, clip: Path) -> None:
    """Clone the voice in `clip`. Chatterbox's loudness normalization turns the
    clip into float64 under NumPy 2, which its tokenizer rejects; keep float32."""
    normalize = tts.norm_loudness
    tts.norm_loudness = lambda wav, sr, **kw: normalize(wav, sr, **kw).astype(np.float32)
    tts.prepare_conditionals(str(clip))


def load_tts(device: str, voice: Path | None) -> ChatterboxTurboTTS:
    """Load Chatterbox and clone `voice` (None = its built-in voice) on the CPU, then move only what speaking
    needs to the GPU (~1.4 GB): T3, the GPT-2 that turns text into speech
    tokens, in bfloat16, plus the flow model and vocoder. Loading straight onto
    the GPU would briefly need ~3 GB. The speech tokenizer and voice encoders
    only read the voice clip, so they stay on the CPU."""
    with contextlib.redirect_stdout(io.StringIO()):
        tts = ChatterboxTurboTTS.from_pretrained(device="cpu")
    if voice is not None:
        set_voice(tts, voice)
    if device != "cpu":
        # s3gen looks up its device from the tokenizer's weights; use the flow model's.
        type(tts.s3gen).device = property(lambda self: next(self.flow.parameters()).device)
        tts.t3.to(device=device, dtype=torch.bfloat16)
        tts.s3gen.flow.to(device)
        tts.s3gen.mel2wav.to(device)
        tts.s3gen.trim_fade = tts.s3gen.trim_fade.to(device)
        tts.conds = tts.conds.to(device)
        tts.conds.t3 = tts.conds.t3.to(dtype=torch.bfloat16)
        tts.device = device
    return tts


Reply = tuple[str, Callable[[], AsyncIterator[str]]]  # (message, produces the reply's sentences)


class Server:
    def __init__(self, tts: ChatterboxTurboTTS, recognizer: PhonemeRecognizer | None, temperature: float,
                 brain_options: dict, responder: ChatResponder | None, llm: LLM | None, model: str):
        self.tts = tts
        self.model = model  # the body Godot loads (models.toml)
        self.recognizer = recognizer
        self.temperature = temperature
        self.responder = responder
        self.llm = llm
        self.clients: set[websockets.ServerConnection] = set()
        self.brain = Brain(self.send, **brain_options)
        self.t0 = time.monotonic()
        self.mind: Mind | None = None
        if llm is not None:
            self.new_mind()
        self.replies: asyncio.Queue[Reply] = asyncio.Queue()
        self.generation = 0  # bumped on "stop" so in-flight replies are dropped
        self.utterance = 0
        self.busy = False  # a reply is being prepared or played
        self._clip_index = 0  # clips sent in the current reply
        self._opened = False  # the current reply has passed the brain's speech gate
        self._sentences: asyncio.Queue[str | None] | None = None
        self.coping: Coping | None = None  # the move behind the reply being spoken
        self.heard_at: float | None = None  # when the message she's answering arrived (latency)
        self._last_snapshot = ""
        self._snapshot_at = -1.0

    def new_mind(self) -> None:
        """A fresh mind (startup, /reset): her state starts from her baseline."""
        log = Path(__file__).resolve().parent / "logs" / "mind" / time.strftime("%Y%m%d_%H%M%S.jsonl")
        self.mind = Mind(self.llm, now=self.clock(), log_path=log)
        self.brain.mind = self.mind

    def clock(self) -> float:
        return time.monotonic() - self.t0

    def send(self, msg: dict) -> None:
        websockets.broadcast(self.clients, json.dumps(msg))

    async def handle_client(self, ws: websockets.ServerConnection) -> None:
        _LOGGER.info("Godot connected")
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    continue
                data = json.loads(message)
                text = data.get("text", "").strip()
                match data.get("type"):
                    case "hello":  # from now on it hears everything, its body first
                        self.clients.add(ws)
                        self.send({"type": "cmd", "cmd": "model", "name": self.model})
                        self.brain.connected(data.get("targets", []))
                    case "chat" if text:
                        if self.mind:
                            arrived = self.clock()  # her windows (reception, pile-ons) count from here
                            await self.replies.put((text, lambda text=text, arrived=arrived: self.mind_reply(text, arrived)))
                        else:
                            await self.replies.put((text, lambda text=text: _sentences_of(text)))
                    case "say" if text:
                        await self.replies.put((text, lambda text=text: _sentences_of(text)))
                    case "stop":
                        self.stop()
                    case "reset" if self.responder:
                        self.responder.reset()
                        self.new_mind()
                    case "set" if self.mind and data.get("name"):
                        values = {k: float(data[k]) for k in ("liking", "familiarity", "threat") if k in data}
                        self.mind.set_person(str(data["name"]), **values)
                    case "perform" if data.get("tag"):
                        self.brain.perform_now(data["tag"])
                    case "camera_test" if data.get("name"):
                        self.brain.camera_now(data["name"])
                    case "event":
                        self.brain.on_event(data)
                    case "mood" if "cinematic" in data:
                        self.brain.set_cinematic(float(data["cinematic"]))
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)
            _LOGGER.info("Godot disconnected")
            if not self.clients:
                self.brain.disconnected()

    async def mind_reply(self, message: str, arrived: float) -> AsyncIterator[str]:
        """A chat message: her mind reads it first (her face reacts as she reads),
        then the actor writes her reply from the state it left her in."""
        sender, sep, text = message.partition(": ")
        if not sep:
            sender, text = "chat", message
        mind = self.mind
        self.heard_at = self.t0 + arrived  # first-audio latency counts from the message's arrival
        mind.tick(self.clock(), busy=True)
        self.brain.message_arrived(sender, text)  # her eyes go to chat while her mind reads it
        self.send({"type": "stage", "stage": "appraiser", "sender": sender})
        reading = await mind.read(sender, text, arrived=arrived)
        self.send({"type": "stage", "stage": "mind", "move": reading.coping.move,
                   "gist": reading.appraisal.gist if reading.appraisal else ""})
        self.coping = reading.coping
        self.brain.read_reaction(reading)
        if reading.error:  # she couldn't read it: no guessed answer (the panel shows the error)
            return
        if reading.coping.line:  # the honest answer: said as written, kept out of the actor's history
            yield reading.coping.line
            mind.spoke(reading.coping.line, reading.coping)
            await mind.check_line(reading.coping.line, reading.coping, message,
                                  stored=SelfCheck(kind="kind", target=sender, admits_ai=True))
            return
        if reading.coping.say:  # a flat line or a refusal: said exactly, and part of the conversation
            yield reading.coping.say
            mind.spoke(reading.coping.say, reading.coping)
            self.responder.remember(message, reading.coping.say)
            await mind.check_line(reading.coping.say, reading.coping, message,
                                  stored=SelfCheck(kind="plain", target=sender))
            return
        if reading.coping.pause:
            await asyncio.sleep(reading.coping.pause)  # going quiet: a beat of silence first
        brief = mind.brief(sender, reading.coping)
        self.send({"type": "stage", "stage": "actor"})
        asked = time.monotonic()
        first = True
        async with contextlib.aclosing(self.responder.reply(message, brief, reading.coping.max_tokens)) as stream:
            try:
                async for sentence in stream:
                    if first:
                        mind.timing["actor_first_sentence_ms"] = round((time.monotonic() - asked) * 1000.0)
                        first = False
                    yield sentence
            finally:
                if self.responder.last_reply and mind is self.mind:
                    mind.spoke(self.responder.last_reply, reading.coping)
                    asyncio.create_task(mind.check_line(self.responder.last_reply, reading.coping, message))

    async def initiative(self, coping: Coping) -> AsyncIterator[str]:
        """Chat has been quiet: she says something on her own."""
        mind = self.mind
        self.brain.speaking_first(coping)
        self.coping, self.heard_at = coping, None
        self.send({"type": "stage", "stage": "mind", "move": coping.move, "gist": ""})
        brief = mind.brief(None, coping)
        self.send({"type": "stage", "stage": "actor"})
        async with contextlib.aclosing(self.responder.reply(QUIET, brief, coping.max_tokens)) as stream:
            async for sentence in stream:
                yield sentence
        if mind is self.mind:
            mind.spoke(self.responder.last_reply, coping)
            mind.heard_silence()
            if self.responder.last_reply:
                asyncio.create_task(mind.check_line(self.responder.last_reply, coping, QUIET))

    async def live(self) -> None:
        """Her mind's clock: feelings fade, thoughts come, she may speak first.
        Short displays play as feelings rise; the body follows her state every
        second; the debug panel gets a snapshot 5 times a second while anything
        changes, once a second otherwise."""
        last_body = -1.0
        while True:
            await asyncio.sleep(0.2)
            if self.mind is None:
                continue
            now = self.clock()
            for intent in self.mind.tick(now, busy=self.busy):
                if intent.kind == "think":
                    asyncio.create_task(self.think(intent))
                elif intent.kind == "speak" and intent.coping and self.replies.empty() and not self.busy:
                    await self.replies.put((QUIET, lambda c=intent.coping: self.initiative(c)))
            for name, peak, rise in self.mind.phasic():
                self.brain.felt_display(name, peak, rise)
            if self.clients:
                snapshot = self.mind.snapshot()
                values = json.dumps([b["v"] for b in snapshot["bars"]] + [snapshot["seq"], len(snapshot["calc"])])
                if values != self._last_snapshot or now - self._snapshot_at >= 1.0:
                    self.send(snapshot)
                    self._last_snapshot, self._snapshot_at = values, now
                if now - last_body >= 1.0:
                    self.brain.apply_body(self.mind.body(), self.mind.tonic(), self.mind.gaze())
                    last_body = now

    async def think(self, intent) -> None:
        mind = self.mind
        thought = await mind.think(intent)
        if thought and mind is self.mind:
            self.brain.thought(thought)

    def stop(self) -> None:
        self.generation += 1
        while not self.replies.empty():
            self.replies.get_nowait()
        if self._sentences is not None:
            self._sentences.put_nowait(None)  # wake the speaker if it's waiting on the LLM
        self.send({"type": "stop"})
        self.brain.on_stop()

    def synthesize(self, plan: SentencePlan) -> tuple[np.ndarray, Analysis]:
        """Audio (float32, tts.sr) and its analysis. Runs on a worker thread."""
        started = time.monotonic()
        with torch.inference_mode(), contextlib.redirect_stdout(io.StringIO()):
            wav = self.tts.generate(pronounce(plan.text), temperature=self.temperature)
        audio = wav.squeeze(0).numpy().astype(np.float32)
        if self.recognizer is not None:
            analysis = self.recognizer.analyze(audio, self.tts.sr, plan.spoken, plan.sound_tags)
        else:
            analysis = analyze([], audio, self.tts.sr)
        _LOGGER.info("  %.2fs audio in %.2fs  %s", analysis.duration, time.monotonic() - started, plan.text)
        for (_, name), window in zip(plan.sound_tags, analysis.sounds or []):
            _LOGGER.info("    [%s] %s", name, f"at {window[0]:.2f}-{window[1]:.2f}s" if window else "skipped by the voice")
        return audio, analysis

    async def speak_forever(self) -> None:
        while True:
            message, reply = await self.replies.get()
            self.busy = True
            generation = self.generation
            self.utterance += 1
            # The reply's sentences (e.g. streaming from the LLM) are produced in
            # the background while earlier ones are synthesized and played.
            sentences: asyncio.Queue[str | None] = asyncio.Queue()
            self._sentences = sentences
            producer = asyncio.create_task(_produce(reply, sentences))
            self._clip_index = 0
            self._opened = False
            while (sentence := await sentences.get()) is not None and generation == self.generation:
                # Words become clips; pauses and expressions without words
                # ("[suspicious] [pause]") become silent clips, so everything plays in order.
                silence: list[tuple[float, SentencePlan]] = []
                silence_length = 0.0
                for item in split_pauses(sentence):
                    if isinstance(item, tuple):
                        silence_length += random.uniform(*item)
                        continue
                    plan = plan_sentence(item)
                    if not plan.has_speech:
                        silence.append((silence_length, plan))
                        continue
                    move = self.coping.move if self.coping is not None else ""
                    bad = violations(plan.spoken, honest=move == "honest", move=move)
                    fixed = self.coping is not None and (self.coping.say or self.coping.line)  # meant to be said
                    if self.coping is not None and not fixed and echoes(plan.spoken, self.coping.template):
                        bad.append("says her instruction out loud")
                    if bad and self.mind is not None:  # the hard guard: it never reaches her voice
                        self.mind.guard_hit(plan.spoken, bad)
                        continue
                    if (silence or silence_length > 0.0) and not await self._open_reply(generation):
                        break
                    self.send_silence(silence, silence_length)
                    silence, silence_length = [], 0.0
                    plan.text = self.brain.voice_text(plan, self._clip_index)  # the engine may add [fear] / [happy]
                    self.send({"type": "stage", "stage": "voice"})
                    audio, analysis = await asyncio.to_thread(self.synthesize, plan)
                    if generation != self.generation:
                        break
                    skipped = [name for (_, name), window in zip(plan.sound_tags, analysis.sounds or [])
                               if window is None]
                    if self.mind is not None and skipped:
                        self.mind.glitch(skipped[0])  # the voice skipped a sound she meant to make
                    if not await self._open_reply(generation):
                        break
                    if self._clip_index == 0 and self.mind is not None and self.heard_at is not None:
                        self.mind.first_audio((time.monotonic() - self.heard_at) * 1000.0)
                    commands = self.brain.sentence_commands(plan, analysis, self.utterance, self._clip_index)
                    self.send_clip(audio, analysis, commands, plan.spoken)
                if generation == self.generation and (silence or silence_length > 0.0) \
                        and await self._open_reply(generation):
                    self.send_silence(silence, silence_length)
            producer.cancel()
            for result in await asyncio.gather(producer, return_exceptions=True):  # let it finish cleaning up
                if isinstance(result, Exception):
                    _LOGGER.error("the reply failed", exc_info=result)
            self._sentences = None
            self.busy = False
            if generation == self.generation:
                self.send({"type": "end"})

    async def _open_reply(self, generation: int) -> bool:
        """Before the first sound of a reply, once: the brain's gate (she finishes a freeze, hesitates when
        she's of two minds), then reply_starting. False if she was stopped meanwhile."""
        if not self._opened:
            self._opened = True
            await self.brain.speech_gate()
            if generation != self.generation:
                return False
            self.brain.reply_starting()
        return generation == self.generation

    def send_silence(self, pieces: list[tuple[float, SentencePlan]], length: float) -> None:
        """A silent clip: a dramatic pause, and/or expressions held without words."""
        if not pieces and length <= 0.0:
            return
        length = max(length, 0.3)
        audio = np.zeros(int(length * self.tts.sr), dtype=np.float32)
        analysis = analyze([], audio, self.tts.sr)
        commands = self.brain.silent_commands(pieces, length, self.utterance, self._clip_index)
        _LOGGER.info("  %.2fs silence  %s", length, " ".join(f"[{t.name}]" for _, p in pieces for t in p.tags))
        self.send_clip(audio, analysis, commands)

    def send_clip(self, audio: np.ndarray, analysis: Analysis, commands: list[dict], text: str = "") -> None:
        """One sentence for Godot; `text` is its words without tags ("" for a silent clip)."""
        header = {
            "type": "clip",
            "text": text,
            "utterance": self.utterance,
            "index": self._clip_index,
            "sample_rate": self.tts.sr,
            "fps": FPS,
            "names": VISEMES,
            "visemes": [[round(float(w), 3) for w in row] for row in analysis.visemes],
            "commands": commands,
        }
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        self.send(header)
        websockets.broadcast(self.clients, pcm)
        self._clip_index += 1

    async def serve(self, host: str, port: int) -> None:
        async with websockets.serve(self.handle_client, host, port, max_size=None):
            _LOGGER.info("Listening on ws://%s:%d", host, port)
            await asyncio.gather(self.speak_forever(), self.live())


async def _sentences_of(text: str) -> AsyncIterator[str]:
    stream = SentenceStream()
    for chunk in stream.feed(text) + stream.flush():
        yield chunk


async def _produce(reply: Callable[[], AsyncIterator[str]], sentences: asyncio.Queue) -> None:
    try:
        # aclosing: if the reply is cut off, its generator still finishes up
        # (e.g. the chat history records what she had said so far).
        async with contextlib.aclosing(reply()) as stream:
            async for sentence in stream:
                await sentences.put(sentence)
    finally:
        sentences.put_nowait(None)


async def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Eileen server")
    models = load_models()
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(models),
                        help=f"the body she streams in (models.toml; default {DEFAULT_MODEL})")
    parser.add_argument("--voice", default="builtin",
                        help='"builtin" (Chatterbox\'s own voice) or a clean 5-10 s wav to clone')
    parser.add_argument("--temperature", type=float, default=0.8, help="TTS: lower = steadier, higher = more varied")
    parser.add_argument("--cinematic", type=float, default=0.6, help="camera: 0 locked-off .. 1 very cinematic")
    parser.add_argument("--llm", default="deepseek", choices=[*PROVIDERS, "none"],
                        help="her mind and her lines; none = no mind, chat lines are spoken as typed")
    parser.add_argument("--llm-model", default=None, help="override the provider's default model")
    parser.add_argument("--llm-temperature", type=float, default=None, help="the actor's temperature")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT, help="the actor's prompt (re-read per message)")
    parser.add_argument("--mode", choices=["phonemes", "audio"], default="phonemes",
                        help="phonemes = mouth shapes from a phoneme recognizer, audio = loudness only")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--recognizer-device", default=None,
                        help="device for the phoneme recognizer (default: same as --device); "
                             "cpu frees ~0.7 GB VRAM but adds latency")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    voice = None if args.voice == "builtin" else Path(args.voice)
    if voice is not None and not voice.is_file():
        parser.error(f"voice clip not found: {voice}")

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    _LOGGER.setLevel(logging.INFO)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    transformers.logging.set_verbosity_error()

    responder, llm = None, None
    if args.llm != "none":
        llm = create_llm(args.llm, model=args.llm_model, temperature=args.llm_temperature)
        responder = ChatResponder(llm, models[args.model]["looks"], args.prompt)
        _LOGGER.info("Mind and lines by %s (%s), actor prompt: %s", llm.name, getattr(llm, "model", "?"), args.prompt)

    _LOGGER.info("Body: %s", args.model)
    _LOGGER.info("Loading Chatterbox Turbo (%s), voice: %s...", args.device, args.voice)
    tts = load_tts(args.device, voice)
    recognizer = None
    if args.mode == "phonemes":
        _LOGGER.info("Loading phoneme recognizer...")
        recognizer = PhonemeRecognizer(args.recognizer_device or args.device)

    brain_options = {"cinematic": args.cinematic}
    server = Server(tts, recognizer, args.temperature, brain_options, responder, llm, args.model)
    _LOGGER.info("Warming up (first generation is slow)...")
    await asyncio.to_thread(server.synthesize, plan_sentence("Hello."))
    if torch.cuda.is_available():
        _LOGGER.info("VRAM held by this server: %.1f GB", torch.cuda.memory_reserved() / 1e9)
    await server.serve(args.host, args.port)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
