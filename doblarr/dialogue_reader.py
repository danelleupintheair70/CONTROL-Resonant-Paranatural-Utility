"""Who speaks each line, as a strong language model reads the script.

The plain rules (doblarr.dialogue_clues) name a voice from who answers to a
name. A capable model reading the whole script in order can go further: who
explains and who asks, who gives orders, how someone refers to themself. On
the test episode local 8-12B models could not do it (12-17 % of lines right,
confident and wrong), so this reader is off unless ``analysis.reader_model``
names a model able to: a large local one, or a cloud one. A cloud model means
the subtitle text leaves this machine; that is the person's choice, made in
the config, never a default.

The reading is evidence beside the voices, never a name by itself: the page
shows what it says about each voice, and lines where it disagrees with the
voice's name move up the question queue.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger("doblarr.dialogue_reader")

READER = "dialogue-reader/1"
WINDOW = 30
OVERLAP = 8
WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.25}

SYSTEM = """You read the script of one episode of a TV show in order and say
who speaks each line. Each line has its time, its text, the original-language
text when known, a voice group (an automatic grouping of lines that sound
alike, right about 9 times in 10) and the names the line calls out.

A name called out is the person spoken TO, never the speaker; the next line in
another voice is often that person answering. Use who asks and who explains,
orders, how people refer to themselves, speech style, and scene changes. Never
give a voice group the name of someone the scene only talks about.

Use the cast names when they fit; you may name someone the dialogue names.
Give a person's name, not a role. If a line cannot be attributed, give "".
For every line id: the speaker, a confidence (high only when a clue in the
dialogue decides it) and the clue in a few words."""


class Call(BaseModel):
    id: int
    speaker: str = Field(max_length=80)
    confidence: Literal["high", "medium", "low"]
    clue: str = Field(max_length=160)


class Reading(BaseModel):
    lines: list[Call]


def windows(count: int, size: int = WINDOW, overlap: int = OVERLAP) -> list[tuple[int, int]]:
    out, start = [], 0
    while start < count:
        end = min(count, start + size)
        out.append((start, end))
        if end == count:
            break
        start = end - overlap
    return out


def read(lines: list[dict], cast: list[str], client, *, cancel=None, progress=None) -> list[dict]:
    """One attribution per line: {speaker, confidence, clue}."""
    from . import dialogue_clues

    names = dialogue_clues.candidates(lines, cast)
    calls: list[dict | None] = [None] * len(lines)
    ranges = windows(len(lines))
    for n, (start, end) in enumerate(ranges):
        if cancel is not None and cancel.is_set():
            break
        payload = {"cast": cast, "lines": [
            {"id": i, "t": round(float(lines[i]["start"]), 1), "voice": lines[i].get("speaker"),
             "text": lines[i].get("text") or "", "original": lines[i].get("original_text") or "",
             "calls": dialogue_clues.called(lines[i].get("text") or "", names)}
            for i in range(start, end)]}
        reply = client.ask(Reading, SYSTEM, payload, max_tokens=4000)
        for call in reply.lines:
            if start <= call.id < end:
                calls[call.id] = {"speaker": " ".join(call.speaker.split()),
                                  "confidence": call.confidence, "clue": call.clue}
        if progress is not None:
            progress(n + 1, len(ranges), f"read lines {start + 1}-{end}")
    return [c or {"speaker": "", "confidence": "low", "clue": "not read"} for c in calls]


def by_voice(voices: list[str], calls: list[dict]) -> dict:
    """Per voice group: the names the reader gives its lines, weighted by confidence."""
    tally: dict[str, dict[str, float]] = {}
    for voice, call in zip(voices, calls, strict=True):
        if call.get("speaker"):
            bucket = tally.setdefault(voice, {})
            bucket[call["speaker"]] = bucket.get(call["speaker"], 0.0) + WEIGHT.get(
                call.get("confidence"), 0.25)
    out = {}
    for voice, names in tally.items():
        ranked = sorted(names.items(), key=lambda kv: -kv[1])
        total = sum(names.values())
        out[voice] = {"leading": ranked[0][0], "share": round(ranked[0][1] / total, 2),
                      "names": [{"name": n, "weight": round(w, 2)} for n, w in ranked[:3]]}
    return out


def run(job, work: Path, model: str, cast: list[str], *, original: dict | None = None,
        cancel=None, progress=None) -> Path:
    """Read the script with `model` and keep the reading beside it."""
    from . import llm
    from .artifacts import digest, read_json
    from .stages.common import work_stem

    path = Path(work) / f"{work_stem(job)}.reader.json"
    lines = [{"cue": seg.cue_id, "start": seg.start, "speaker": seg.speaker,
              "text": seg.text_src, "original_text": (original or {}).get(seg.cue_id, "")}
             for seg in job.segments]
    key = digest({"reader": READER, "model": model, "cast": sorted(cast),
                  "lines": [[ln["cue"], ln["speaker"], ln["text"]] for ln in lines]})[:16]
    saved = read_json(path)
    if saved.get("request") == key and saved.get("lines"):
        return path
    calls = read(lines, cast, llm.Client(model, timeout=600), cancel=cancel, progress=progress)
    payload = {"request": key, "reader": READER, "model": model,
               "lines": [{"cue": ln["cue"], **c} for ln, c in zip(lines, calls, strict=True)],
               "voices": by_voice([ln["speaker"] for ln in lines], calls)}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log.info("reader: %d line(s) read with %s", len(lines), model)
    return path
