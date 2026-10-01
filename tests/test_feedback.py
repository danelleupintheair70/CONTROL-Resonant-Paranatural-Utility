"""Verdicts, approved examples, the held-out set and portable guidance."""

import pytest

from doblarr import feedback, identity, profiles, templates
from doblarr.store import Database
from doblarr.studio import records


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "f.db")
    templates.ensure_builtins(database)
    yield database
    database.close()


def _verdict(db, **extra):
    body = feedback.VerdictIn(**{"job_id": "j1", "cue": "c1", "revision_id": "rev-a",
                                 "artifact": "fp1",
                                 "template": {"id": "voice/late-emphasis", "version": 1},
                                 "params": {"strength": 0.8}, "verdict": "accept",
                                 "problems": [], **extra})
    return feedback.record_verdict(db, body)


def test_a_verdict_names_what_went_wrong_and_corrections_name_the_fix(db):
    with pytest.raises(ValueError):
        _verdict(db, problems=["vibes"])
    with pytest.raises(ValueError):
        _verdict(db, verdict="correct")
    saved = _verdict(db, verdict="reject", problems=["acting", "envelope"],
                     reason="the shout was the wrong performance, not the wrong curve")
    assert saved["problems"] == ["acting", "envelope"]


def test_one_example_per_line_never_duplicated_and_corrections_supersede(db):
    verdict = _verdict(db)
    first = feedback.approve_example(db, verdict, source_curve=[0, 1], take_curve=[0, 0],
                                     target_lang="es", series_id="show:tvdb:1")
    again = feedback.approve_example(db, verdict, source_curve=[0, 1], take_curve=[0, 0],
                                     target_lang="es", series_id="show:tvdb:1")
    assert first["id"] == again["id"] and again["revision"] == 2
    assert len(feedback.examples(db, "show:tvdb:1")) == 1
    corrected = _verdict(db, verdict="correct", artifact="fp2",
                         correction={"template": "voice/gradual-rise", "strength": 1.0})
    feedback.approve_example(db, corrected, source_curve=[0, 1], take_curve=[0, 0],
                             target_lang="es", series_id="show:tvdb:1")
    rows = feedback.examples(db, "show:tvdb:1")
    assert len(rows) == 1 and rows[0]["template"] == "voice/gradual-rise"
    rejected = _verdict(db, verdict="reject", artifact="fp3")
    with pytest.raises(ValueError):
        feedback.approve_example(db, rejected, source_curve=[], take_curve=[],
                                 target_lang="es")


def test_retiring_an_example_stops_new_use_and_keeps_history(db):
    example = feedback.approve_example(db, _verdict(db), source_curve=[1], take_curve=[0],
                                       target_lang="es", series_id="s")
    records.put(db, "decision", "dec-1", {"examples_used": {"c9": [example["id"]]}})
    assert feedback.dependents(db, example["id"]) == [{"decision": "dec-1", "job": None,
                                                       "cues": ["c9"]}]
    feedback.retire_example(db, example["id"], base_revision=example["revision"])
    assert feedback.examples(db, "s") == []
    assert len(feedback.examples(db, "s", include_retired=True)) == 1
    assert len(records.history(db, "example", example["id"])) == 2


def test_a_held_out_revision_cannot_become_an_example_until_promoted(db):
    feedback.hold_out(db, "rev-a")
    assert feedback.held_out(db) == {"rev-a"}
    with pytest.raises(ValueError, match="held out"):
        feedback.approve_example(db, _verdict(db), source_curve=[], take_curve=[],
                                 target_lang="es")
    promoted = feedback.hold_out(db, "rev-a", held=False, note="moved to development")
    assert promoted["was_held_out"] and feedback.held_out(db) == set()
    feedback.approve_example(db, _verdict(db), source_curve=[], take_curve=[],
                             target_lang="es")


def test_guidance_travels_without_media_and_imports_once(db, tmp_path):
    kaito = identity.ensure_character(db, "show:tvdb:1", "Kaito")
    profiles.update(db, kaito["id"], base_revision=0, set_fields={
        "templates.favored": [{"template": "voice/late-emphasis"}],
        "delivery.direction": "dry, understated"})
    feedback.approve_example(db, _verdict(db), source_curve=[0, 2], take_curve=[0, 0],
                             target_lang="es", series_id="show:tvdb:1")
    bundle = feedback.export_guidance(db, template_ids=["voice/late-emphasis"],
                                      series_id="show:tvdb:1")
    text = str(bundle)
    assert "rev-a" not in text and "reviewer" not in text and "path" not in text
    other = Database(tmp_path / "o.db")
    templates.ensure_builtins(other)
    report = feedback.import_guidance(other, bundle, series_id="show:tvdb:2")
    assert report["characters"] == ["Kaito"] and report["examples"] == 1
    again = feedback.import_guidance(other, bundle, series_id="show:tvdb:2")
    assert again["examples"] == 0
    imported = identity.find_character(other, "show:tvdb:2", "Kaito")
    assert profiles.get(other, imported["id"])["delivery"]["direction"] == "dry, understated"
    missing = {**bundle, "templates": [], "examples": [{**bundle["examples"][0],
                                                        "template": "voice/not-here"}]}
    assert feedback.import_guidance(other, missing, series_id="show:tvdb:2")["skipped"]
    other.close()


def test_feedback_routes_record_verdicts_and_examples(client_factory):
    client = client_factory()
    saved = client.post("/api/adaptive/feedback", json={
        "job_id": "j1", "cue": "c1", "verdict": "reject", "problems": ["level"],
        "reason": "too loud"})
    assert saved.status_code == 200
    bad = client.post("/api/adaptive/feedback", json={"job_id": "j1", "cue": "c1",
                                                      "verdict": "nope"})
    assert bad.status_code == 422
    assert client.get("/api/adaptive/impact", params={"change": "template"}).json()[
        "speech"] is False
    assert client.get("/api/adaptive/impact", params={"change": "voice"}).json()["speech"]
    listed = client.get("/api/adaptive/examples").json()
    assert listed["examples"] == [] and listed["held_out"] == []
