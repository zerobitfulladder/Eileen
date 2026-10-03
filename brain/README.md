# Eileen

The brain, voice and inner life of the Eileen avatar. The Godot project in
[`../body`](../body) is her body: it connects here, plays what this sends,
and runs all per-frame motion (saccades, blinks, breathing, gestures, face,
lip sync). This side decides what she feels, says and does.

```sh
uv run server.py                        # start this first, leave it running (body: lucy)
uv run server.py --model miku           # another body: lucy, eileen, miku (models.toml)
uv run server.py --llm none             # no LLM: chat lines are spoken as typed
uv run server.py --voice voices/lucy_clean.wav  # clone a voice instead of the built-in one
```

Startup takes ~20 s (models load and warm up). Then run the Godot scene and use
the chat box at the bottom of the window (all commands are in the Godot
README): type `hi eileen` to talk as yourself (the chat box's username), `jo: hi` to talk as someone else,
`/set jo liking 0.7 familiarity 0.8` to set how she feels about someone. F2
shows or hides her inner-state panel, F1 all debug UI.

## How she works

Her inner life is specified in [`docs/mind.md`](docs/mind.md) and built in
`mind/`. For every chat message:

1. **The appraiser** (an LLM with her private core) reads the message and
   answers fixed questions about it: is it a reminder of what she is, how it's
   framed, how deniable, good or bad for her goals, what the sender did by her
   standards, which of her tastes it touches, someone's news... It never says
   what she feels.
2. **The engine** (plain code, `mind/`) turns those answers into feelings with
   fixed rules: two-part emotions with sources, mood, the wound (threat,
   composure, doubt), drives, how she feels about each person, prospects. It
   picks how she copes (the ladder: composed, strained, overwhelmed, the
   crack) and the move.
3. **The actor** (an LLM, `prompts/actor.md`) writes her line from a short
   "Right now" note: behavior only, never her feelings, wants or reasons.
4. **The body** (`brain.py`, `mimics.py`, Godot) shows what she feels: the
   reading face, freezes, short displays, leaks through the faces she puts on,
   her resting face, breathing, blinks and gaze.

Between messages time passes: feelings fade, drives build, thoughts come (a
small LLM call), and she fills dead air. She hears herself too: a self-check
reads each of her lines (a joke waiting for its laugh, guilt after a snap).

## Files

| File | What it does |
|------|--------------|
| `server.py` | WebSocket server; reply pipeline (mind → actor → sentences → hard guard → TTS → Godot); her mind's clock |
| `mind/` | Her inner life: `engine.py` (orchestrator, snapshot, log), `appraisal.py` (appraiser and self-check), `rules.py` (appraisal → feelings), `coping.py` (the ladder, moves, comedy, stubbornness, slips, speaking first), `dispositions.py` ("Right now" and the word check), `expression.py` (display rules, leaks, resting face, body), `thoughts.py`, `guard.py` (the hard guard and reply checks), `state.py`, `persona.py` |
| `models.toml`, `models.py` | The bodies she can stream in (`--model`): each name is a Godot scene (`res://models/NAME/NAME.tscn`) the server tells Godot to load on connect, plus how she describes her looks to the actor |
| `mind/persona.toml` | Every number of her personality: emotions, mood, wound, drives, tastes, what she knows, the things she's sure of, comedy. Tune her here |
| `brain.py` | Her body's behavior: the reading face, reactions, idle routines, gaze, leaks, held faces while she talks |
| `mimics.py` | Face recipes: the faces she puts on (the actor's tags), felt faces, leaks, social smiles |
| `camera.py` | Cinematographer: moves only on her mind's events (a horror startle, the crack, felt moments) |
| `chat.py` | The actor: chat message + "Right now" → LLM → speakable sentences; keeps this run's chat history |
| `prompts/` | `actor.md` (her lines), `appraiser.md` (her private core and the questions), `self.md` (the self-check), `thoughts.md`, and the test judges (`judge.md`, `comedy_judge.md`). Re-read on every call, so edits apply live |
| `simulate.py`, `shape.py`, `scenarios/` | Behavioral tests (see below) |
| `sounds.py` | Finds where the voice really laughed/sighed (or skipped it); a skip is a glitch her mind notices |
| `llm/` | LLM providers. `deepseek.py` is a preset of `openai_compatible.py` |
| `text.py` | Sentence splitting (also while streaming), cleanup of LLM output |
| `visemes.py` | Audio analysis: mouth shapes, where laughs/sighs are, emphasis beats |
| `voices/` | Clips to clone with `--voice` (must be clean: Chatterbox copies their noise too), and `pronunciations.txt` for names the voice gets wrong |
| `logs/mind/` | One JSON line per event of every stream: appraisals, calculations, moves, her lines, thoughts (replayable) |

## Testing her

Tests are behavioral: what her inner state does and what she says, through the
real LLMs, plus offline checks of the engine. See
[`scenarios/README.md`](scenarios/README.md). In short:

```sh
uv run simulate.py scenarios/*.txt --out runs/today --parallel 7    # scenarios through her mind and the actor
uv run simulate.py --appraiser scenarios/appraiser_battery.json --runs 3   # does she read messages right?
uv run shape.py --checks                    # offline: the spec's scenes, invariants (no LLM)
uv run shape.py                             # offline: 3-hour streams, normal / troll / kind (no LLM)
uv run simulate.py --replay logs/mind/<stream>.jsonl --params my.toml     # re-run a stream with other numbers
```

## Chat history and memory

She remembers the whole stream while the server runs: every chat message and
her reply go along with the next message. It lives only in memory, so
restarting the server (or `/reset`) starts fresh, and everyone (you
included) is a stranger again. Persistent memory of people is planned. The
chat box sends your lines as `<username>: ...`; the username is the project
setting `eileen/chat/username` (see the body README to set your own without
committing it).

## Options

- `--model` (default `lucy`): the body she streams in, from `models.toml`.
  Only her looks change; she's Eileen in every body. To add one, add the model
  in Godot (see its README), then a `[name]` entry with `looks` in
  `models.toml`.
- `--cinematic` (0 locked-off tripod … 1 very cinematic, default 0.6): how
  often and how strongly the camera moves on her mind's events. Any client can
  change it live: `{"type": "mood", "cinematic": 0.4}`.
- `--llm-temperature`: the actor's temperature (default 1.0; her mind's calls
  set their own).
- `--temperature`: the voice (lower = steadier).

How she moves, smiles and reacts follows her mind; there are no personality
dials any more.

## Tags

The actor writes tags inline, lowercase (the list is in `prompts/actor.md`):

- Faces she puts on, held while she talks until the next face: `[deadpan]
  [side eye] [smug] [eye roll] [teasing] [skeptical] [suspicious] [bored]
  [recall] [considering] [unsure] [smile] [grin] [pout]`
- Gestures: `[wink] [nod] [shake head] [tilt head] [shrug] [look away]
  [look down] [look at chat] [look at camera]`
- Sounds the voice makes: `[chuckle] [laugh] [sigh] [groan] [gasp] [sniff]
  [clear throat] [shush]`; delivery: `[whispering] [sarcastic] [dramatic]
  [narration]`
- Pauses: `[pause]` (~1 s), `[long pause]` (~2 s). Any tag takes a strength:
  `[smug:0.5]`.

Felt faces (what she really feels: tenderness, a wince, the realization...)
are not tags: only her mind makes them. Sound reactions follow the real sound:
`[laugh]` animates when and as long as the voice actually laughs, and if the
voice skips a sound, her mind notices the glitch.

## Another LLM

Most providers speak the OpenAI format. Add a preset like `llm/deepseek.py` and
register it in `PROVIDERS` in `llm/__init__.py`; then `--llm yourprovider`.
The DeepSeek key is read from `DEEPSEEK_KEY` (or the `DEEPSEEK_API_KEY` env var).

## Notes

- VRAM: ~2.3 GB (Chatterbox T3 in bfloat16, its tokenizer on CPU, recognizer
  fp16). `--recognizer-device cpu` frees another ~0.7 GB.
- Chatterbox adds Resemble AI's inaudible Perth watermark to everything it generates.
