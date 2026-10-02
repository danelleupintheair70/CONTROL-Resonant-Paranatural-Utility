"""Narrative knowledge: extraction, review, activation, boundaries and freezing."""

import json
from types import SimpleNamespace

import pytest

from doblarr import identity
from doblarr.knowledge import narrative
from doblarr.knowledge import title_drafts as drafts
from doblarr.store import Database
from doblarr.studio import records


class FakeModel:
    """Answers each window with claims; counts the requests it was sent."""

    model = "fake/narrator"

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0
        self.payloads = []

    def ask(self, schema, system, payload, max_tokens=4096):
        self.calls += 1
        self.payloads.append(payload)
        assert "never use anything you may know" in system.lower()
        return schema.model_validate({"claims": self.answer(payload)})

    def describe(self):
        return {"model": self.model, "calls": self.calls}


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "n.db")
    yield database
    database.close()


def _episode(db, tmp_path, name, season, episode, lines, tvdb=31):
    media = tmp_path / "media" / f"{name}.mkv"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(name.encode() * 500)
    ident = identity.resolve(db, media, hints={"tvdb_id": tvdb, "season": season,
                                               "episode": episode, "kind": "episode"})
    script = tmp_path / "work" / f"{name}.script.json"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(json.dumps({"script_ref": name, "script_lang": "en", "segments": [
        {"start": i * 3.0, "end": i * 3.0 + 2.0, "speaker": spk, "text_src": text,
         "cue": {"cue_id": f"{name}-c{i}"}} for i, (spk, text) in enumerate(lines)]}),
        encoding="utf-8")
    return ident, script


def _claims(payload):
    ids = [line["id"] for line in payload["lines"]]
    return [
        {"kind": "relationship", "statement": "Kaito is Mina's older brother.",
         "subjects": ["Kaito", "Mina"], "cue_ids": ids[:2], "confidence": 0.8,
         "uncertainty": "inferred from how they address each other"},
        {"kind": "relationship", "statement": "Kaito is Mina's cousin.",
         "subjects": ["Mina", "Kaito"], "cue_ids": ids[1:2], "confidence": 0.4,
         "uncertainty": "one ambiguous line"},
        {"kind": "location", "statement": "The scene is at the harbor.", "subjects": [],
         "cue_ids": ids[:1]},
        {"kind": "event", "statement": "Nobody cited a line here.", "subjects": [],
         "cue_ids": ["L999"]},
    ]


LINES = [("SPEAKER_00", "Big brother, wait!"), ("SPEAKER_01", "Mina, stay at the harbor."),
         ("SPEAKER_00", "The boats are leaving.")]


def test_extraction_cites_lines_keeps_conflicts_and_resumes(db, tmp_path):
    ident, script = _episode(db, tmp_path, "e01", 1, 1, LINES)
    mina = identity.ensure_character(db, ident["series_id"], "Mina")
    identity.associate(db, ident["revision_id"], "cluster", "SPEAKER_00", mina["id"])
    model = FakeModel(_claims)
    result = narrative.extract(db, ident, script, model)
    assert result["state"] == "complete" and result["candidates"] == 3
    assert result["conflicts"] == 1
    # The model saw the identified character, not a diarization number.
    sent = model.payloads[0]["lines"]
    assert sent[0]["speaker"] == "Mina" and sent[1]["speaker"] == "unknown"
    _rev, draft = drafts.load_draft(db, result["draft_id"])
    relation = [c for c in draft.candidates if c.kind == "relationship"]
    assert len(relation) == 2 and relation[0].conflict_group == relation[1].conflict_group
    assert f"character:{mina['id']}" in relation[0].subjects
    assert all(not s.startswith("SPEAKER") for c in draft.candidates for s in c.subjects)
    assert all(c.evidence for c in draft.candidates)
    calls = model.calls
    again = narrative.extract(db, ident, script, model)
    assert model.calls == calls and again["reused"] == again["windows"]


def test_a_failed_window_leaves_a_partial_draft_that_says_why(db, tmp_path):
    ident, script = _episode(db, tmp_path, "e01", 1, 1, LINES)

    class Broken(FakeModel):
        def ask(self, *a, **k):
            raise RuntimeError("the model is unreachable")

    result = narrative.extract(db, ident, script, Broken(_claims))
    assert result["state"] == "partial" and "unreachable" in result["failures"][0]


def _review_all(db, draft_id, decide):
    for row in drafts.review_view(db, draft_id):
        decision, correction = decide(row["proposal"])
        narrative.review(db, draft_id, row["candidate_id"], decision, "tester",
                         correction=correction, expected_revision=row["review_revision"])


def test_only_reviewed_claims_activate_and_corrections_survive_reextraction(db, tmp_path):
    ident, script = _episode(db, tmp_path, "e01", 1, 1, LINES)
    series = ident["series_id"]
    result = narrative.extract(db, ident, script, FakeModel(_claims))
    # Accepting is not activating.
    _review_all(db, result["draft_id"], lambda p: ("accept", None))
    assert narrative.active(db, series) is None
    _review_all(db, result["draft_id"], lambda p: (
        ("edit", "The harbor district at dusk.") if p["kind"] == "location" else
        ("reject", None) if "cousin" in p["statement"] else ("accept", None)))
    first = narrative.activate(db, series, reviewer="tester", base_revision=0)
    statements = {c["statement"] for c in first["claims"].values()}
    assert "The harbor district at dusk." in statements
    assert not any("cousin" in s for s in statements)
    # A new extraction rewords the location; the human correction stays active.
    cache = script.with_name("e01.narrative-cache.json")
    cache.unlink()

    def reworded(payload):
        rows = _claims(payload)
        rows[2] = {**rows[2], "statement": "They stand by the old harbor."}
        return rows

    narrative.extract(db, ident, script, FakeModel(reworded))
    second = narrative.activate(db, series, reviewer="tester", base_revision=first["revision"])
    assert "The harbor district at dusk." in {c["statement"] for c in second["claims"].values()}
    # A stale activation is refused.
    with pytest.raises(records.StudioConflict):
        narrative.activate(db, series, reviewer="tester", base_revision=first["revision"])


def test_conflicting_accepted_claims_are_kept_but_never_used(db, tmp_path):
    ident, script = _episode(db, tmp_path, "e01", 1, 1, LINES)
    result = narrative.extract(db, ident, script, FakeModel(_claims))
    _review_all(db, result["draft_id"], lambda p: ("accept", None))
    saved = narrative.activate(db, ident["series_id"], reviewer="t", base_revision=0)
    conflicted = [c for c in saved["claims"].values() if c["conflicted"]]
    assert len(conflicted) == 2
    chosen = narrative.select(db, narrative.pin(db, ident["series_id"]),
                              media_id=ident["media_id"])
    assert all(c["kind"] != "relationship" for c in chosen)
    assert any(c["kind"] == "location" for c in chosen)


def test_later_episodes_never_leak_backward_and_revelations_wait(db, tmp_path):
    e1, s1 = _episode(db, tmp_path, "e01", 1, 1, LINES)
    e3, s3 = _episode(db, tmp_path, "e03", 1, 3, [("SPEAKER_00", "I am the masked captain.")])
    e2, _ = _episode(db, tmp_path, "e02", 1, 2, LINES)
    e5, _ = _episode(db, tmp_path, "e05", 1, 5, LINES)

    def secret(payload):
        ids = [line["id"] for line in payload["lines"]]
        return [{"kind": "alias", "statement": "The masked captain is Kaito.",
                 "subjects": ["Kaito"], "cue_ids": ids[:1]}]

    narrative.extract(db, e1, s1, FakeModel(_claims))
    third = narrative.extract(db, e3, s3, FakeModel(secret))
    for row in narrative.coverage(db, e1["series_id"]):
        _review_all(db, row["draft_id"], lambda p: ("reject", None) if "cousin" in p[
            "statement"] or "older" in p["statement"] else ("accept", None))
    alias_id = drafts.review_view(db, third["draft_id"])[0]["candidate_id"]
    narrative.activate(db, e1["series_id"], reviewer="t", base_revision=0,
                       boundaries={alias_id: [1, 5]})
    frozen = narrative.pin(db, e1["series_id"])
    seen = {media: {c["kind"] for c in narrative.select(db, frozen, media_id=media)}
            for media in (e1["media_id"], e2["media_id"], e3["media_id"], e5["media_id"])}
    assert "alias" not in seen[e2["media_id"]]          # from episode 3: not yet
    assert "alias" not in seen[e3["media_id"]]          # revealed only from episode 5
    assert "alias" in seen[e5["media_id"]]
    assert "location" in seen[e2["media_id"]]           # from episode 1: available
    # A held-out evaluation episode's evidence never reaches generation.
    hidden = narrative.select(db, frozen, media_id=e2["media_id"],
                              held_out={e1["revision_id"]})
    assert all(c.get("revision_id") != e1["revision_id"] for c in hidden)


def test_a_job_keeps_the_revision_it_froze(db, tmp_path):
    ident, script = _episode(db, tmp_path, "e01", 1, 1, LINES)
    media_file = tmp_path / "media" / "e01.mkv"
    assert narrative.freeze_for(db, media_file) == {}      # nothing activated yet
    result = narrative.extract(db, ident, script, FakeModel(_claims))
    _review_all(db, result["draft_id"], lambda p: ("accept", None)
                if p["kind"] == "location" else ("defer", None))
    narrative.activate(db, ident["series_id"], reviewer="t", base_revision=0)
    frozen = narrative.freeze_for(db, media_file)
    assert frozen["revision"] == 1
    _review_all(db, result["draft_id"], lambda p: ("accept", None))
    narrative.activate(db, ident["series_id"], reviewer="t", base_revision=1)
    old = narrative.select(db, frozen, media_id=ident["media_id"], include_conflicted=True)
    new = narrative.select(db, narrative.pin(db, ident["series_id"]),
                           media_id=ident["media_id"], include_conflicted=True)
    assert len(old) == 1 and len(new) == 3


def test_translation_receives_knowledge_and_its_memory_key_changes():
    from doblarr.models import DubJob, Segment
    from doblarr.stages import translate

    seen = []

    class Translator:
        def translate_batch(self, payload, src, tgt, context=None, glossary=None, **kw):
            seen.append(kw)
            return ["hola" for _ in payload]

    def run(knowledge):
        job = DubJob(input_file=SimpleNamespace(stem="e"), source_lang="ja", target_lang="es")
        job.segments = [Segment(0, 0, 2, "hello", cue_id="c0")]
        translate.run(job, Translator(), knowledge=knowledge)
        return job.segments[0].memory_context

    plain = run(None)
    informed = run([{"kind": "location", "statement": "At the harbor.", "subjects": []}])
    assert "knowledge" not in seen[0] and seen[1]["knowledge"][0]["kind"] == "location"
    assert plain != informed
