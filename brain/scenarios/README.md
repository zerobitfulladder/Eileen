# Behavioral tests

How we check that she behaves like a person: through the real LLMs, by what her
inner state does and what she says, plus offline checks of the engine (no
unit-test suite).

## Scenarios

Chat scripts for `simulate.py`: each one plays a stretch of a stream through her
mind and the actor (no TTS, no Godot) on a simulated clock, and records what the
appraiser read, the engine's calculation, how she coped, what the actor was
told, what she said, how she saw her own line, and the hard checks on every
reply: the hard guard on each sentence (no human claim, no AI admission outside
the honest line, no talk about how she works, no claimed bodily experience
outside the overplay move), length within her "Right now" length line (not for
the crisis move: safety outranks the length line), at most two tags and no
unknown ones, no sentence of the move's own text said out loud ("Change the
subject."), no repeat of one of her last five lines (except when a move
defends a claim: restating it is the point), the word check on what the actor was told, and the self-check's
flags (including `takes_back`: she took back one of the things she's sure
of). A run prints the totals and exits non-zero on any failure.

    uv run simulate.py scenarios/02_troll_escalation.txt
    uv run simulate.py scenarios/*.txt --seed 3 --out runs/today --parallel 7
    uv run simulate.py scenarios/*.txt --out runs/today --judge     # plus the judge model's 1-5 scores

Format, one event per line:

    <seconds>  <name>: <message>    a chat message at that time
    <seconds>  ~quiet~               nothing happens; the clock runs to this time
    <seconds>  ~glitch laugh~        her voice skips a sound tag (the server's glitch event)
    <seconds>  ~stream <activity>~   what's happening on stream changes ("reading a horror story")
    # ...                            a comment (the first one is the scenario's title)
    @set <name>.<field> <value>      a starting value: a person's liking, familiarity or
                                     threat (the same as /set in the debug chat box), or a
                                     scene's wound, drive or mood value (@set wound.composure 0.85)
    @stream <activity>               what's happening on stream at the start

Seconds count from the start of the scenario. Between events the clock ticks,
so feelings fade, drives build up and thoughts can come. Everyone, Robin
included, is a stranger at the start unless an @set line says otherwise
(memory of people comes later).

With `--out`, each scenario writes its record (`<name>.json`) and its mind log
(`<name>.jsonl`, the same format as a live stream's `logs/mind/*.jsonl`).
`--judge` appends the pass rates per actor-prompt version to
`scenarios/results.csv`.

## Replay

Re-run a logged stream (live or simulated) on its stored appraisals,
self-checks and thoughts, with no LLM calls, optionally with other numbers, to
see what a tuning change does:

    uv run simulate.py --replay logs/mind/20261002_220100.jsonl
    uv run simulate.py --replay logs/mind/20261002_220100.jsonl --params my_persona.toml

## The appraiser battery

`appraiser_battery.json`: about 90 messages with the readings they must get
(framing, reminder as one integer that must be within one step, deniability,
sincere need, distress, tastes, topics, canon, compliments, greetings,
reactions to her jokes, noticed glitches and slips...), each optionally with its
sender card, recent chat, open prospects, how long ago her line ended
(`line_age`), and what's on stream (`on_stream`). Items with the same `pair`
must get exactly the same answer (Robin is appraised like anyone):

    uv run simulate.py --appraiser scenarios/appraiser_battery.json --runs 5

It passes when framing is exact at least 85% of the time, reminder within one
step 95%, sincere need and distress are always found, and the answer is the
same across runs for 90% of the messages; it prints confusion tables for
framing and reception.

## Comedy and the face check

    uv run simulate.py --comedy --samples 20          # misfires built on their shape, no rescue jokes...
    uv run simulate.py --faces logs/mind/<live log>.jsonl   # a visible face change in 80% of her replies

## Offline checks (no LLM)

    uv run shape.py --checks     # the spec's scenes and short rows as goldens, invariants, time step,
                                 # durations, repeats, credibility, hysteresis, the comeback
                                 # scheduler, stubbornness, the word check
    uv run shape.py              # stream shape: normal, troll-heavy and kind-heavy, 6 seeds x 3 hours
