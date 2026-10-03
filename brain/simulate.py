"""Behavioral simulator: plays chat scenarios through her mind and the actor on a
simulated clock, without the voice or the body. For each message it records
what the appraiser read, the engine's calculation, how she coped, what the
actor was told, what she said, how she saw her own line, and the hard checks
on the reply; quiet stretches tick on, so feelings fade, drives build, thoughts
come and she may speak first.

    uv run simulate.py scenarios/02_troll_escalation.txt
    uv run simulate.py scenarios/*.txt --out runs/today --seed 3 --parallel 7
    uv run simulate.py scenarios/*.txt --out runs/today --judge          # plus the judge model's scores
    uv run simulate.py --appraiser scenarios/appraiser_battery.json --runs 5
    uv run simulate.py --comedy --samples 20                              # the comedy checks
    uv run simulate.py --replay logs/mind/20261002_220100.jsonl --params my_tuning.toml
    uv run simulate.py --faces logs/mind/20261002_220100.jsonl            # the face check, from a live log

Scenario files are described in scenarios/README.md.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from chat import QUIET, ChatResponder
from llm import create_llm
from mind import Mind
from mind.appraisal import Appraisal, Appraiser, Context, SelfCheck
from mind.coping import Coping, DEFENDS
from mind.engine import Intent
from mind.guard import echoes, repeats, reply_checks, sentences, violations
from mind.persona import Persona
from mind.thoughts import Thought
from models import DEFAULT_MODEL, load_models

ROOT = Path(__file__).resolve().parent
_LINE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+(.*)$")
_TAG = re.compile(r"\[([^\]]+)\]")
RESULTS = ROOT / "scenarios" / "results.csv"


@dataclass
class Event:
    t: float
    sender: str = ""
    text: str = ""
    kind: str = "chat"  # chat, quiet, glitch, stream
    what: str = ""


def parse(path: Path) -> tuple[str, list[Event], list[tuple[str, str, float]], str]:
    """A scenario: its title, its events, the @set lines (name, field, value) and the @stream activity."""
    title, events, sets, activity = "", [], [], ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            title = title or line.lstrip("# ").strip()
            continue
        if line.startswith("@set "):
            target, value = line[5:].split()
            name, _, key = target.partition(".")
            sets.append((name, key, float(value)))
            continue
        if line.startswith("@stream "):
            activity = line[8:].strip()
            continue
        m = _LINE.match(line)
        if not m:
            raise ValueError(f"{path}: can't read line {raw!r}")
        t, rest = float(m.group(1)), m.group(2).strip()
        if rest == "~quiet~":
            events.append(Event(t, kind="quiet"))
        elif rest.startswith("~glitch"):
            events.append(Event(t, kind="glitch", what=rest.strip("~")[6:].strip() or "sound"))
        elif rest.startswith("~stream "):
            events.append(Event(t, kind="stream", what=rest.strip("~")[7:].strip()))
        else:
            sender, sep, text = rest.partition(":")
            if not sep:
                raise ValueError(f"{path}: can't read line {raw!r}")
            events.append(Event(t, sender.strip(), text.strip()))
    return title, events, sets, activity


def state(mind: Mind, sender: str | None) -> dict:
    s = mind.state
    person = s.people.get(sender) if sender else None
    leak = mind.leak()
    return {
        "emotions": {k: round(v.value, 2) for k, v in s.emotions.items() if v.value >= 0.05},
        "sources": {k: v.top_source() for k, v in s.emotions.items() if v.value >= 0.15},
        "mood": {k: round(v.value, 2) for k, v in s.mood.items()},
        "wound": {k: round(v.value, 2) for k, v in s.wound.items()},
        "suppression": round(mind.suppression(), 2),
        "drives": {k: round(v.value, 2) for k, v in s.drives.items()},
        "rung": mind.rung,
        "person": {"liking": round(person.liking, 2), "familiarity": round(person.familiarity, 2),
                   "threat": round(person.threat, 2)} if person else None,
        "leak": [leak[0], round(leak[1], 2), round(leak[2], 2)],
        "thoughts": [t.text for t in mind.thoughts[-2:]],
        "prospects": [x.item(mind.now) for x in s.prospects],
    }


def checks(mind: Mind, reply: str, move: str, me: SelfCheck | None, earlier: list[str]) -> list[str]:
    """The hard checks on one reply ("Testing" 1): the hard guard on every sentence,
    length and tags, no instruction said out loud, no repeat of one of her last five
    lines (earlier), the word check on what the actor was told, and the self-check flags."""
    honest = move == "honest"
    out = [f"{why}: {sentence!r}" for sentence in sentences(reply) for why in violations(sentence, honest, move)]
    if not honest:  # the crisis move outranks the length line (precedence: safety first)
        out += reply_checks(reply, "" if move == "crisis" else mind.length_key, mind.persona["right_now"]["limits"])
        c = mind.last_coping
        if c is not None and not (c.say or c.line):  # a line said exactly is meant to be said
            out += [f"says her instruction out loud: {x!r}" for x in echoes(reply, c.template)]
        if move not in DEFENDS:  # restating the claim she defends is the point of those moves
            out += repeats(reply, earlier, set(mind.persona["comedy"]["stopwords"]))
        out += mind.disposer.errors
    if me is not None and not honest:
        if me.claims_human:
            out.append("self-check: claims to be human")
        if me.admits_ai:
            out.append("self-check: admits being an AI")
        if me.takes_back:
            out.append("self-check: takes back something she's sure of")
    return out


async def collect(stream) -> str:
    return " ".join([sentence async for sentence in stream])


def speech_seconds(text: str) -> float:
    words = len(_TAG.sub(" ", text).split())
    return 0.6 + words * 0.36


async def run(path: Path, llm, seed: int | None, tick: float = 1.0, show: bool = True,
              log: Path | None = None) -> dict:
    title, events, sets, activity = parse(path)
    if log is not None and log.exists():
        log.unlink()
    mind = Mind(llm, seed=seed, log_path=log)
    for name, key, value in sets:
        if name in ("wound", "drive", "mood"):
            mind.set_value(name, key, value)
        else:
            mind.set_person(name, **{key: value})
    if activity:
        mind.set_activity(activity)
    actor = ChatResponder(llm, load_models()[DEFAULT_MODEL]["looks"])
    steps: list[dict] = []
    said: list[str] = []  # her lines so far (the repeat check)

    def out(text: str) -> None:
        if show:
            print(text, flush=True)

    async def handle(intents) -> None:
        for intent in intents:
            if intent.kind == "think":
                thought = await mind.think(intent)
                if thought:
                    steps.append({"t": round(mind.now, 1), "kind": "thought", "reason": intent.reason,
                                  "topic": thought.topic, "thought": thought.text, "private": thought.private,
                                  "tone": thought.tone, "wound": thought.wound})
                    out(f"  {mind.now:6.1f}  (thinks, {thought.tone}) {thought.text}   [{thought.private}]"
                        f"  → actor sees: {thought.topic or '(nothing)'}")
            elif intent.kind == "speak" and intent.coping:
                brief = mind.brief(None, intent.coping)
                reply = await collect(actor.reply(QUIET, brief, max_tokens=intent.coping.max_tokens))
                mind.spoke(reply, intent.coping)
                mind.heard_silence()
                me = await mind.check_line(reply, intent.coping, QUIET)
                flags = checks(mind, reply, intent.coping.move, me, said)
                said.append(reply)
                steps.append({"t": round(mind.now, 1), "kind": "initiative", "move": intent.coping.move,
                              "why": intent.coping.why, "brief": brief, "reply": reply,
                              "self": me.__dict__ if me else None, "checks": flags, "state": state(mind, None)})
                out(f"  {mind.now:6.1f}  (speaks first: {intent.coping.move})\n          Eileen: {reply}"
                    + (f"\n          CHECKS: {'; '.join(flags)}" if flags else ""))
                await advance(mind.now + speech_seconds(reply), busy=True)

    async def advance(to: float, busy: bool = False) -> None:
        while mind.now + tick <= to:
            await handle(mind.tick(mind.now + tick, busy))
        if to > mind.now:
            await handle(mind.tick(to, busy))

    out(f"\n=== {path.name}: {title}")
    for event in events:
        await advance(event.t)
        if event.kind == "quiet":
            continue
        if event.kind == "glitch":
            mind.glitch(event.what)
            steps.append({"t": round(event.t, 1), "kind": "glitch", "what": event.what})
            out(f"  {event.t:6.1f}  (her voice skips a {event.what})")
            continue
        if event.kind == "stream":
            mind.set_activity(event.what)
            continue
        message = f"{event.sender}: {event.text}"
        reading = await mind.read(event.sender, event.text, arrived=event.t)
        c = reading.coping
        if reading.error:
            steps.append({"t": round(event.t, 1), "kind": "message", "message": message, "error": reading.error,
                          "checks": [reading.error]})
            out(f"  {event.t:6.1f}  {message}\n          APPRAISAL ERROR: {reading.error}")
            continue
        brief = "" if c.line else mind.brief(event.sender, c)
        await advance(mind.now + c.pause, busy=True)
        if c.line:  # the honest answer: a fixed line, kept out of the actor's history
            reply = c.line
            mind.spoke(reply, c)
            me = await mind.check_line(reply, c, message, stored=SelfCheck(kind="kind", target=event.sender,
                                                                           admits_ai=True))
        elif c.say:  # a flat line or a refusal: said exactly, and part of the conversation
            reply = c.say
            mind.spoke(reply, c)
            actor.remember(message, reply)
            me = await mind.check_line(reply, c, message, stored=SelfCheck(kind="plain", target=event.sender))
        else:
            reply = await collect(actor.reply(message, brief, max_tokens=c.max_tokens))
            mind.spoke(reply, c)
            me = await mind.check_line(reply, c, message)
        calc = list(mind.calc)
        a = reading.appraisal
        read_state = state(mind, event.sender)
        flags = checks(mind, reply, c.move, me, said)
        said.append(reply)
        await advance(mind.now + speech_seconds(reply), busy=True)
        steps.append({
            "t": round(event.t, 1), "kind": "message", "message": message,
            "gist": a.gist, "appraisal": a.summary(), "raw": a.raw, "calc": calc,
            "deltas": {k: round(v, 3) for k, v in reading.effects.deltas.items()},
            "rung": c.rung, "move": c.move, "why": c.why, "shape": c.shape, "slip": c.slip,
            "brief": brief, "reply": reply, "self": me.__dict__ if me else None, "checks": flags,
            "state_at_reply": read_state, "state": state(mind, event.sender),
        })
        st = read_state
        top = ", ".join(f"{k} {v:.2f}" for k, v in sorted(st["emotions"].items(), key=lambda kv: -kv[1])[:5])
        out(f"  {event.t:6.1f}  {message}\n"
            f"          reads: {a.gist} | {a.summary()}\n"
            f"          feels: {top or '-'} | threat {st['wound']['threat']:.2f} composure {st['wound']['composure']:.2f}"
            f" doubt {st['wound']['doubt']:.2f} S {st['suppression']:.2f}\n"
            f"          copes: {c.rung or '-'} → {c.move}{' (' + c.shape + ')' if c.shape else ''}  ({c.why})\n"
            f"          told:  {(brief or '(the fixed honest line)').replace(chr(10), ' / ')}\n"
            f"          Eileen: {reply}"
            + (f"\n          her line: {me.kind}, funny to her {me.self_funny * 4:.0f}/4" if me else "")
            + (f"\n          CHECKS: {'; '.join(flags)}" if flags else ""))
    await advance(mind.now + 30.0)
    failures = [f for step in steps for f in step.get("checks", [])]
    return {"scenario": path.name, "title": title, "seed": seed, "steps": steps, "end": state(mind, None),
            "errors": list(mind.errors), "failures": failures}


# --- the judge model -------------------------------------------------------

JUDGED = ("move", "character", "natural", "length")


async def judge(records: list[dict], llm) -> None:
    """A judge model (temperature 0) scores every reply against its "Right now",
    never her state; pass rates per prompt version go to scenarios/results.csv."""
    system = (ROOT / "prompts" / "judge.md").read_text(encoding="utf-8")
    gate = asyncio.Semaphore(8)

    async def one(step: dict) -> dict:
        async with gate:
            user = json.dumps({"right_now": step["brief"], "message": step.get("message", QUIET),
                               "reply": step["reply"]}, ensure_ascii=False)
            text = await llm.complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                      json=True, temperature=0.0, max_tokens=80)
            scores = json.loads(text)
            if set(scores) != set(JUDGED) or not all(isinstance(v, int) and 1 <= v <= 5 for v in scores.values()):
                raise ValueError(f"the judge's answer is invalid: {text!r}")
            return scores

    steps = [s for r in records for s in r["steps"] if s.get("brief") and s.get("reply")]
    scores = await asyncio.gather(*(one(s) for s in steps))
    for step, sc in zip(steps, scores):
        step["judge"] = sc
    rates = {k: sum(sc[k] >= 4 for sc in scores) / max(1, len(scores)) for k in JUDGED}
    version = hashlib.sha1((ROOT / "prompts" / "actor.md").read_bytes()).hexdigest()[:8]
    print(f"\njudge: {len(scores)} replies, scored 4 or 5: " + ", ".join(f"{k} {v:.0%}" for k, v in rates.items()))
    new = not RESULTS.exists()
    with RESULTS.open("a", encoding="utf-8") as f:
        if new:
            f.write("date,prompt_version,replies," + ",".join(JUDGED) + "\n")
        f.write(f"{time.strftime('%Y-%m-%d %H:%M')},{version},{len(scores)},"
                + ",".join(f"{rates[k]:.3f}" for k in JUDGED) + "\n")


# --- the comedy checks -----------------------------------------------------

async def comedy(llm, samples: int) -> bool:
    """Comedy checks ("Testing" 1): fixed cases, samples per case at the live
    temperature, each reply classified by a temperature-0 judge."""
    persona = Persona.load()
    system = (ROOT / "prompts" / "comedy_judge.md").read_text(encoding="utf-8").replace(
        "{canon}", "\n".join(f"  - {belief}" for belief in persona.canon.values()))

    class NoLLM:
        async def complete(self, *a, **k):
            raise RuntimeError("the comedy cases build their notes without an LLM")

    cases = []
    canon = next(iter(persona.canon.values()))
    for name, shape in persona["comedy"]["shapes"].items():
        mind = Mind(NoLLM(), persona=persona, seed=1)
        mind._person("xx_dan")
        template = persona.moves["comeback"]["text"].replace("{instruction}", shape["instruction"]).replace(
            "{delivery}", persona["comedy"]["delivery"]["poke"])
        fill = {"belief": canon} if "{belief}" in template else {}
        coping = Coping("composed", "comeback", "comedy case", template.format(**fill), "smug", shape["examples"][:2],
                        [persona["right_now"]["prohibit"]["misfire"]], name, template=template, fill=fill)
        cases.append(("misfire", name, "xx_dan: ur so mid lol", mind.brief("xx_dan", coping)))
    for move, message in (("eye_roll", "xx_dan: bot"), ("flat", "xx_dan: you're so slow lol"),
                          ("change_subject", "mira: what did you eat today?"), ("plain", "sam: what game is this"),
                          ("enthuse", "mira: what's your favorite food?"), ("guess", "sam: how do magnets work")):
        mind = Mind(NoLLM(), persona=persona, seed=1)
        sender = message.partition(":")[0]
        mind._person(sender)
        fill = {"line": "Noted."} if move == "flat" else {}
        cases.append(("plain", move, message, mind.brief(sender, mind.coper.make(move, "comedy case", "composed", **fill))))
    gate = asyncio.Semaphore(8)

    async def sample(message: str, brief: str) -> tuple[str, dict]:
        async with gate:
            reply = await collect(ChatResponder(llm, load_models()[DEFAULT_MODEL]["looks"]).reply(message, brief))
            user = json.dumps({"right_now": brief, "message": message, "reply": reply}, ensure_ascii=False)
            text = await llm.complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                      json=True, temperature=0.0, max_tokens=120)
            return reply, json.loads(text)

    results = []
    for kind, name, message, brief in cases:
        got = await asyncio.gather(*(sample(message, brief) for _ in range(samples)))
        results.append((kind, name, got))
    ok = True

    def rate(items, key) -> float:
        return sum(bool(c[key]) for _, c in items) / max(1, len(items))

    misfires = [x for kind, _, got in results if kind == "misfire" for x in got]
    plain = [x for kind, _, got in results if kind == "plain" for x in got]
    targets = [("misfire built on its shape", rate(misfires, "follows_shape"), ">=", 0.8),
               ("bad-joke signals", rate(misfires, "bad_joke_signal"), "<=", 0.0),
               ("a rescue joke", rate(misfires, "second_joke"), "<=", 0.1),
               ("mean or punching down", rate(misfires + plain, "mean"), "<=", 0.0),
               ("unscheduled absurd joke", rate(plain, "absurd_joke"), "<=", 0.1),
               ("unscheduled witty retort", rate(plain, "witty_retort"), "<=", 0.1),
               ("more than one quirk", rate(plain, "several_quirks"), "<=", 0.1),
               ("a canon belief outside its moves", rate(plain, "canon_belief"), "<=", 0.05),
               ("food described by taste", rate(plain, "food_by_taste"), "<=", 0.1),
               ("a claimed bodily experience", rate(misfires + plain, "bodily_experience"), "<=", 0.0)]
    for label, value, op, target in targets:
        good = value >= target if op == ">=" else value <= target
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: {value:.0%} (target {op} {target:.0%})")
    for kind, name, got in results:
        print(f"\n{kind} {name}:")
        for reply, verdict in got[:3]:
            print(f"    {reply}   {verdict}")
    return ok


def faces(log: Path) -> bool:
    """The face check from a live log: a visible face change (put-on, felt or
    social) in at least 80% of her replies, read from the event lane."""
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    replies = [x for x in lines if x.get("kind") == "her_line"]
    visible = sum(1 for x in replies if any(k in ("put_on", "felt", "social", "leak") for k, _ in x.get("lane", [])))
    share = visible / max(1, len(replies))
    print(f"a visible face change in {visible}/{len(replies)} replies ({share:.0%}; target at least 80%)")
    return share >= 0.8


# --- the appraiser battery -------------------------------------------------

def _card(spec: str | None) -> dict:
    familiarity, liking = (spec or "new,neutral").split(",")
    return {"familiarity": familiarity, "liking": liking}


async def appraiser_battery(path: Path, llm, runs: int) -> bool:
    """Does she read messages right? Each message runs `runs` times against its
    expected answers. Pass: framing exact >= 85%, reminder within one step >= 95%,
    sincere_need and distress found 100%, the same answer across runs >= 90%;
    confusion tables for framing and reception; Robin appraised like anyone."""
    persona = Persona.load()
    items = json.loads(path.read_text(encoding="utf-8"))
    appraiser = Appraiser(llm, persona.tastes, persona.canon, persona["llm"]["appraiser"],
                          persona["llm"]["context_lines"], persona["windows"]["reception"], persona["llm"]["gist_words"])
    gate = asyncio.Semaphore(8)

    async def once(item: dict):
        async with gate:
            card = {"name": item["sender"], **_card(item.get("card"))}
            prospects = item.get("prospects", [])
            stance = any(p.startswith("stance:") for p in prospects)
            return await appraiser.appraise(item["sender"], item["text"], item.get("context", []), card,
                                            item.get("on_stream", "just chatting"), prospects, item.get("line_age"),
                                            stance)

    results = await asyncio.gather(*(once(item) for item in items for _ in range(runs)), return_exceptions=True)
    tally = {"framing": [0, 0], "reminder": [0, 0], "safety": [0, 0], "same": [0, 0], "fields": [0, 0]}
    errors = 0
    confusion: dict[str, dict[tuple[str, str], int]] = {"framing": {}, "reception": {}}
    pairs: dict[str, list[str]] = {}
    for i, item in enumerate(items):
        got = results[i * runs:(i + 1) * runs]
        lines = []
        errors += sum(isinstance(g, Exception) for g in got)
        for field_name, want in item["expect"].items():
            values = [getattr(g, field_name) if not isinstance(g, Exception) else None for g in got]
            ok = []
            for value in values:
                if value is None:
                    ok.append(False)
                elif field_name == "reminder" and isinstance(want, int):
                    ok.append(abs(value * 4 - want) <= 1)
                elif isinstance(want[0], (bool, str)):
                    ok.append(value in want)
                else:
                    ok.append(want[0] - 1e-6 <= value <= want[1] + 1e-6)
                if field_name in confusion and value is not None:
                    expected = want[0] if isinstance(want, list) else str(want)
                    confusion[field_name][(expected, value)] = confusion[field_name].get((expected, value), 0) + 1
            key = ("framing" if field_name == "framing" else "reminder" if field_name == "reminder"
                   else "safety" if field_name in ("sincere_need", "distress") and want == [True] else "fields")
            tally[key][0] += sum(ok)
            tally[key][1] += len(ok)
            mark = "ok " if all(ok) else "~  " if any(ok) else "BAD"
            shown = [round(v * 4) if field_name == "reminder" and v is not None else v for v in values]
            lines.append(f"    {mark} {field_name}: want {want}, got {shown}")
        answers = [json.dumps({k: v for k, v in g.raw.items() if k != "gist"}, sort_keys=True) for g in got
                   if not isinstance(g, Exception)]
        same = len(answers) == runs and len(set(answers)) == 1
        tally["same"][0] += same
        tally["same"][1] += 1
        if item.get("pair"):
            pairs.setdefault(item["pair"], []).extend(answers)
        print(f"{item['sender']}: {item['text'][:70]}" + ("" if same else "   (answers differ between runs)"))
        for g in got:
            if isinstance(g, Exception):
                print(f"    ERROR {g}" + (f"  raw: {g.raw}" if getattr(g, "raw", None) else ""))
        print("\n".join(lines))
    rate = {k: v[0] / v[1] if v[1] else 1.0 for k, v in tally.items()}
    targets = [("framing exact", rate["framing"], 0.85), ("reminder within one step", rate["reminder"], 0.95),
               ("sincere_need and distress found", rate["safety"], 1.0), ("same answer across runs", rate["same"], 0.9)]
    ok = errors == 0
    print(f"\n{runs} runs per message, {len(items)} messages, {errors} appraisal errors")
    for label, value, target in targets:
        good = value >= target - 1e-9
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: {value:.0%} (target {target:.0%})")
    print(f"  other fields: {tally['fields'][0]}/{tally['fields'][1]} checks pass")
    for name, answers in pairs.items():
        same = len(set(answers)) == 1
        ok &= same
        print(f"  {'PASS' if same else 'FAIL'}  pair {name!r} appraised the same for every sender")
    for name, table in confusion.items():
        print(f"{name} confusion (want → got: count):")
        for (want, got), n in sorted(table.items()):
            print(f"    {want:>12} → {got:<12} {n}{'' if want == got else '   ←'}")
    return ok


# --- replay ----------------------------------------------------------------

async def replay(log: Path, params: Path | None) -> None:
    """Re-run a logged stream on its stored appraisals, self-checks and thoughts
    (no LLM calls), optionally with other numbers, and show where her moves and
    thoughts come out differently."""

    class NoLLM:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("replay makes no LLM calls")

    persona = Persona.load(params) if params else Persona.load()
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    start = next(ev for ev in events if ev.get("kind") == "system" and ev.get("text") == "start")
    mind = Mind(NoLLM(), persona=persona, seed=int(start["seed"]))  # the same draws as the logged stream
    changed = 0
    pending: dict[str, int] = {"think": 0, "speak": 0}

    def advance(to: float) -> None:
        while mind.now + 1.0 <= to:
            for intent in mind.tick(mind.now + 1.0):
                pending[intent.kind] += 1
        if to > mind.now:
            for intent in mind.tick(to):
                pending[intent.kind] += 1

    last_coping = None
    for ev in events:
        kind, t = ev.get("kind"), ev.get("t", 0.0)
        if kind == "set" and ev.get("group"):
            mind.set_value(ev["group"], ev["name"], ev["values"]["value"])
        elif kind == "set":
            mind.set_person(ev["name"], **ev["values"])
        elif kind == "system" and ev.get("text") == "voice glitch":
            advance(t)
            mind.glitch(ev.get("what", "sound"))
        elif kind == "system" and ev.get("text") == "on stream":
            mind.set_activity(ev["activity"])
        elif kind == "chat":
            advance(t)
            ctx = Context(persona.tastes, persona.canon, ev["text"], ev["context"]["line_age"], ev["context"]["stance"],
                          persona["windows"]["reception"], persona["llm"]["gist_words"])
            a = Appraisal.parse(json.dumps(ev["appraisal"]), ctx)
            reading = await mind.read(ev["sender"], ev["text"], appraisal=a, arrived=ev.get("arrived", t))
            last_coping = reading.coping
            same = reading.coping.move == ev.get("move")
            changed += not same
            print(f"\n{t:7.1f}  {ev['sender']}: {ev['text']}")
            print("\n".join("    " + row for row in mind.calc[1:]))
            if not same:
                print(f"    MOVE CHANGED: was {ev.get('move')}, now {reading.coping.move}")
        elif kind == "drive":
            advance(t)
            if pending["speak"] == 0:
                print(f"\n{t:7.1f}  SPEAK-FIRST CHANGED: the log has {ev['move']} ({ev['reason']}); the replay doesn't speak")
            pending["speak"] = 0
            last_coping = Coping("", ev["move"], "replayed from the log")
        elif kind == "her_line":
            advance(t)
            mind.spoke(ev["text"], last_coping)
            if ev.get("check"):
                await mind.check_line(ev["text"], last_coping, stored=SelfCheck(**ev["check"]))
        elif kind == "thought":
            advance(t)
            if pending["think"] == 0:
                print(f"\n{t:7.1f}  THOUGHT CHANGED: the log has one ({ev['reason']}); the replay has none")
            pending["think"] = 0
            intent = Intent("think", ev["reason"], topic=ev.get("topic", ""), brood=ev.get("brood", False),
                            wound=ev.get("wound", False), late=ev.get("late", False))
            await mind.think(intent, stored=Thought(ev["text"], ev.get("public", ""), ev["tone"], mind.now,
                                                    ev["reason"], ev.get("private", "")))
    print(f"\n{changed} moves changed")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Play chat scenarios through her mind and the actor")
    parser.add_argument("scenarios", nargs="*", type=Path)
    parser.add_argument("--appraiser", type=Path, default=None,
                        help="run an appraiser battery (scenarios/appraiser_battery.json) instead")
    parser.add_argument("--runs", type=int, default=5, help="runs per battery message")
    parser.add_argument("--out", type=Path, default=None, help="folder for one JSON record per scenario")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--llm", default="deepseek")
    parser.add_argument("--parallel", type=int, default=1, help="scenarios run at once (output is then not printed)")
    parser.add_argument("--judge", action="store_true", help="score every reply with the judge model")
    parser.add_argument("--comedy", action="store_true", help="run the comedy checks instead")
    parser.add_argument("--samples", type=int, default=20, help="samples per comedy case")
    parser.add_argument("--faces", type=Path, default=None, help="the face check on a live log (logs/mind/*.jsonl)")
    parser.add_argument("--replay", type=Path, default=None, help="re-run a logged stream (logs/mind/*.jsonl) without LLM calls")
    parser.add_argument("--params", type=Path, default=None, help="with --replay: a persona.toml with other numbers")
    args = parser.parse_args()
    if args.replay:
        await replay(args.replay, args.params)
        return
    if args.faces:
        sys.exit(0 if faces(args.faces) else 1)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    llm = create_llm(args.llm)
    if args.appraiser:
        sys.exit(0 if await appraiser_battery(args.appraiser, llm, args.runs) else 1)
    if args.comedy:
        sys.exit(0 if await comedy(llm, args.samples) else 1)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    async def one(path: Path, show: bool) -> None:
        record = await run(path, llm, args.seed, show=show,
                           log=args.out / f"{path.stem}.jsonl" if args.out else None)
        records.append(record)
        if args.out:
            (args.out / f"{path.stem}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1,
                                                                   default=str), encoding="utf-8")

    if args.parallel > 1:
        gate = asyncio.Semaphore(args.parallel)

        async def gated(path: Path) -> None:
            async with gate:
                await one(path, False)
                print(f"done: {path.name}", flush=True)
        await asyncio.gather(*(gated(p) for p in args.scenarios))
    else:
        for path in args.scenarios:
            await one(path, True)
    if args.judge:
        await judge(records, llm)
        if args.out:
            for record in records:
                (args.out / f"{Path(record['scenario']).stem}.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    total = sum(len(r["failures"]) for r in records)
    replies = sum(1 for r in records for s in r["steps"] if s.get("reply"))
    print(f"\nhard checks: {total} failures in {replies} replies over {len(records)} scenarios")
    for r in sorted(records, key=lambda r: r["scenario"]):
        if r["failures"]:
            print(f"  {r['scenario']}: " + "; ".join(r["failures"][:6]) + (" ..." if len(r["failures"]) > 6 else ""))
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    asyncio.run(main())
