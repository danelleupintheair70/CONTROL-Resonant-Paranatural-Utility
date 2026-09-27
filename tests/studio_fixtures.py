"""Synthetic, authored multilingual scenes for studio tests.

Nothing here comes from real media. The Japanese, English and Spanish lines are
written for the tests; the Spanish "official adaptation" carries sentinel
phrases that exist nowhere else, so finding one in a request proves a leak.
"""

from __future__ import annotations

import json

import prompture
from prompture.drivers.base import Driver

from doblarr.studio import records
from doblarr.studio.sources import ReferenceIn, reference_id, write_utterances

SESSION = "sess-test"

JAPANESE = [
    {"utt_id": "ja-1", "start": 10.0, "end": 12.5, "speaker": "NARUTO",
     "text": "ただいま、みんな元気にしてたか"},
    {"utt_id": "ja-2", "start": 13.0, "end": 15.0, "speaker": "SAKURA",
     "text": "遅いよ、二年半も待ったんだから"},
    {"utt_id": "ja-3", "start": 15.2, "end": 16.4, "speaker": "SAKURA",
     "text": "背が伸びたね"},
    {"utt_id": "ja-4", "start": 40.0, "end": 43.0, "speaker": "KAKASHI",
     "text": "この鈴を取れたら合格だ、時間は日没まで"},
    {"utt_id": "ja-5", "start": 44.0, "end": 45.5, "speaker": "NARUTO",
     "text": "今度こそ絶対に取ってみせる"},
]

# The English dub, offset by +2.0 s and merging Sakura's two lines into one.
ENGLISH = [
    {"utt_id": "en-1", "start": 12.1, "end": 14.4,
     "text": "I'm back everybody did you miss the future hokage"},
    {"utt_id": "en-2", "start": 15.0, "end": 18.3,
     "text": "You took forever two and a half years and look how tall you got"},
    {"utt_id": "en-3", "start": 42.0, "end": 45.1,
     "text": "Grab one of these bells before sundown and you pass the test"},
    {"utt_id": "en-4", "start": 46.0, "end": 47.4,
     "text": "This time I am definitely getting one believe it"},
    {"utt_id": "en-5", "start": 70.0, "end": 72.0,
     "text": "An added line the original never had at all today"},
]

# The official Spanish adaptation: evaluation-only. Sentinel phrases included.
SENTINEL = "el zorro plateado duerme bajo la luna de papel"
SPANISH = [
    {"utt_id": "es-1", "start": 10.1, "end": 12.6,
     "text": f"Ya volví, {SENTINEL} y nadie me esperaba"},
    {"utt_id": "es-2", "start": 13.1, "end": 16.3,
     "text": "Tardaste una eternidad, mira nada más cuánto creciste campanita dorada"},
    {"utt_id": "es-3", "start": 40.1, "end": 43.1,
     "text": "Quien tome un cascabel antes del ocaso aprueba la prueba del cerezo"},
]


def add_reference(db, root, label, language, roles, rows, kind, track=True):
    data = ReferenceIn(
        label=label, language=language, roles=roles,
        track=({"media_path": "episode.mkv", "media_key": "m1", "stream_index": 1}
               if track else None),
        text={"kind": kind, "provenance": "authored-test"})
    ref_id = reference_id(SESSION, data)
    identity = write_utterances(root / f"{ref_id}.json", rows)
    document = data.model_dump()
    document["text"].update(identity)
    return records.put(db, "reference", ref_id, {**document, "session": SESSION},
                       scope=SESSION)


def scene(db, root):
    """Meaning (ja), adaptation (en) and evaluation-only (es-MX) references + alignment."""
    from doblarr.studio import alignment

    ja = add_reference(db, root, "Japanese original", "ja", ["meaning"], JAPANESE,
                       "original_transcript")
    en = add_reference(db, root, "English dub", "en", ["adaptation"], ENGLISH,
                       "dub_transcript")
    es = add_reference(db, root, "Official Latin American dub", "es-MX", ["evaluation"],
                       SPANISH, "dub_transcript")
    body = alignment.align(JAPANESE, ENGLISH, alignment.TimeMap(
        [alignment.MapSegment(0, 1000, -2.0, 1.0, 0.9, "manual")]))
    aligned = records.put(db, "alignment", "al-en", {**body, "reference": en["id"],
                                                     "source_ref": ja["id"]}, scope=SESSION)
    return ja, en, es, aligned


class RecordingDriver(Driver):
    """An offline driver that records every prompt and answers from a script."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []

    def generate(self, prompt, options):
        self.prompts.append(prompt)
        return {"text": self.answer(prompt, len(self.prompts)),
                "meta": {"total_tokens": 10, "cost": None}}

    def generate_messages(self, messages, options):
        text = "\n".join(m["content"] for m in messages)
        self.prompts.append(text)
        return {"text": self.answer(text, len(self.prompts)),
                "meta": {"total_tokens": 10, "cost": None}}


def echo_answer(line_text=lambda slot: f"Linea para {slot}"):
    """Answer every writing request with one line per slot; repairs get a short line."""

    def answer(prompt, n):
        body = prompt[prompt.index("{"):]
        try:
            payload, _ = json.JSONDecoder().raw_decode(body)
        except ValueError:
            return "{}"
        if "line" in payload:
            return json.dumps({"text": "Corto."})
        return json.dumps({"units": [
            {"unit_id": u["unit_id"],
             "lines": [{"slot_id": s["slot_id"], "text": line_text(s["slot_id"])}
                       for s in u["slots"]],
             "reference_used": "adaptation_reference" in u, "note": ""}
            for u in payload["units"]]})
    return answer


def install_driver(monkeypatch, driver):
    monkeypatch.setattr(prompture, "get_driver_for_model", lambda model, **kw: driver)


def translator():
    from doblarr.clients.translator import PromptureTranslator

    return PromptureTranslator("local/test")


DEFINITION = {
    "name": "pilot",
    "excerpts": [{"excerpt_id": "x1", "title": "Homecoming", "start": 5, "end": 20},
                 {"excerpt_id": "x2", "title": "Bell test", "start": 35, "end": 50}],
    "decision_criteria": "C passes if no critical meaning regression and it is preferred "
                         "or needs fewer corrections on most excerpts.",
    "target_locale": "es-MX",
    "provider": "prompture", "model": "local/test",
    "shared": {"scene_notes": {"x1": "A gate at dusk; a boy with a backpack walks in."},
               "character_notes": {"NARUTO": "loud, earnest"}},
}
