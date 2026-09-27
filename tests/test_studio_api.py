"""The studio API end to end: sessions, references, alignment, media, auditions, export."""

import json
import shutil
import threading
from pathlib import Path

import pytest

from doblarr.studio import records
from tests.studio_fixtures import (
    DEFINITION,
    ENGLISH,
    JAPANESE,
    SENTINEL,
    SPANISH,
    RecordingDriver,
    echo_answer,
    install_driver,
)
from tests.test_scene_review import review_client, tone


class FakeVoicebox:
    """Speaks a tone for any text; counts every generation it was asked for."""

    def __init__(self):
        self.generated: list[dict] = []
        self.profiles: list[dict] = []
        self.gate = None

    def synthesize_to_file(self, profile, text, language, dest, cancel_event=None, **kw):
        if self.gate is not None:
            self.gate(len(self.generated))
        self.generated.append({"profile": profile, "text": text, **kw})
        return tone(Path(dest), 0.8)

    def preset_voices(self, engine):
        return [{"voice_id": "v1"}] if engine.startswith("qwen") else []

    def voice_profiles(self):
        return self.profiles

    def create_profile(self, name, language, description=""):
        pid = f"p-{len(self.profiles) + 1}"
        self.profiles.append({"id": pid, "name": name})
        return pid

    def add_sample(self, profile, path, text):
        assert Path(path).is_file()

    def transcribe(self, path, language=""):
        return {"text": "hola"}

    def list_voices(self):
        return [{"id": p["id"], "name": p["name"]} for p in self.profiles]


def studio(client, tmp_path, job=None):
    body = {"path": str(job.input_file) if job else str(tmp_path / "movie.mkv"),
            "title": "Film · E01", "job_id": "", "series_ref": "series:film"}
    return client.post("/api/studio/sessions", json=body).json()["session"]


def meaning(client, sid, work, rows=None, label="Japanese original"):
    track = tone(work / "ja-track.wav", 45.0)
    return client.post(f"/api/studio/sessions/{sid}/references", json={
        "label": label, "language": "ja", "roles": ["meaning", "performance"],
        "track": {"media_path": str(track), "audio_index": 0},
        "text": {"kind": "original_transcript"},
        "utterances": rows if rows is not None else JAPANESE}).json()["reference"]


def test_a_session_remembers_place_and_refuses_stale_edits(client_factory, tmp_path):
    client = client_factory()
    queued, job = review_client(client, tmp_path)
    found = studio(client, tmp_path, job)
    assert "path" not in found and found["media_name"] == "movie.mkv"
    moved = client.patch(f"/api/studio/sessions/{found['id']}", json={
        "base_revision": found["revision"], "view": "compare", "line": 2, "position": 3.5,
        "job_id": queued.id})
    assert moved.status_code == 200
    stale = client.patch(f"/api/studio/sessions/{found['id']}", json={
        "base_revision": found["revision"], "view": "cast"})
    assert stale.status_code == 409
    assert stale.json()["error"]["current"]["view"] == "compare"
    again = client.post("/api/studio/sessions", json={
        "path": str(job.input_file), "title": "Film · E01"}).json()["session"]
    assert again["id"] == found["id"] and again["position"] == 3.5
    overview = client.get(f"/api/studio/sessions/{found['id']}").json()
    assert overview["active_job"]["id"] == queued.id
    assert overview["export"]["unresolved"] == 4   # four open timing warnings
    assert "input_file" not in json.dumps(overview["jobs"])
    missing = client.post("/api/studio/sessions", json={"path": str(tmp_path / "nope.mkv"),
                                                        "title": "x"})
    assert missing.status_code == 422


def test_notes_link_to_cues_and_turn_stale_when_the_audio_changes(client_factory, tmp_path):
    client = client_factory()
    queued, job = review_client(client, tmp_path)
    sid = studio(client, tmp_path, job)["id"]
    review = client.get(f"/api/jobs/{queued.id}/review").json()
    cue = review["segments"][1]["cue"]["cue_id"]
    note = client.post(f"/api/studio/sessions/{sid}/notes", json={
        "job_id": queued.id, "cue": cue, "line": 1, "at": 2.9, "source": "dub",
        "category": "Rushed", "severity": "major", "note": "second line rushed",
        "snapshot_revision": review["revision"]}).json()["note"]
    listed = client.get(f"/api/studio/sessions/{sid}/notes?job_id={queued.id}").json()
    assert listed["notes"][0]["note"] == "second line rushed"
    assert listed["notes"][0]["stale"] is False
    resolved = client.patch(f"/api/studio/notes/{note['id']}", json={
        "base_revision": note["revision"], "resolution": "repair_queued",
        "linked_edit": {"job": "next", "cue": cue}}).json()["note"]
    assert resolved["history"][-1]["resolution"] == "repair_queued"
    conflict = client.patch(f"/api/studio/notes/{note['id']}", json={
        "base_revision": note["revision"], "resolution": "resolved"})
    assert conflict.status_code == 409
    # A note taken against an older snapshot is shown as stale, never silently current.
    records.put(client.app.state.jobs.db, "annotation", note["id"],
                {**resolved, "snapshot_revision": "older"})
    listed = client.get(f"/api/studio/sessions/{sid}/notes?job_id={queued.id}").json()
    assert listed["notes"][0]["stale"] is True


def test_evaluation_only_text_and_audio_stay_hidden(client_factory, tmp_path):
    client = client_factory()
    _queued, job = review_client(client, tmp_path)
    work = client.app.state.worker.config.work_dir
    sid = studio(client, tmp_path, job)["id"]
    ja = meaning(client, sid, work)
    held = client.post(f"/api/studio/sessions/{sid}/references", json={
        "label": "Official Latin American dub", "language": "es-MX", "roles": ["evaluation"],
        "track": {"media_path": str(tone(work / "es.wav", 45.0)), "audio_index": 0},
        "text": {"kind": "dub_transcript"}, "utterances": SPANISH}).json()["reference"]
    assert held["evaluation_only"] and "artifact" not in held["text"]
    assert client.get(f"/api/studio/references/{held['id']}/utterances").status_code == 403
    assert client.get(f"/api/studio/sessions/{sid}/media/audio", params={
        "source": f"reference:{held['id']}", "start": 1, "end": 5}).status_code == 403
    both = client.post(f"/api/studio/sessions/{sid}/references", json={
        "label": "x", "language": "es", "roles": ["evaluation", "voice"],
        "track": {"media_path": str(work / "es.wav")}, "text": {"kind": "none"}})
    assert both.status_code == 422
    ok = client.get(f"/api/studio/references/{ja['id']}/utterances").json()
    assert len(ok["utterances"]) == len(JAPANESE)


def test_alignment_maps_playback_and_refuses_a_cut(client_factory, tmp_path):
    client = client_factory()
    _queued, job = review_client(client, tmp_path)
    work = client.app.state.worker.config.work_dir
    sid = studio(client, tmp_path, job)["id"]
    ja = meaning(client, sid, work)
    en = client.post(f"/api/studio/sessions/{sid}/references", json={
        "label": "English dub", "language": "en", "roles": ["adaptation", "performance"],
        "track": {"media_path": str(tone(work / "en.wav", 60.0)), "audio_index": 0},
        "text": {"kind": "dub_transcript"}, "utterances": ENGLISH}).json()["reference"]
    made = client.post(f"/api/studio/sessions/{sid}/alignments", json={
        "source": ja["id"], "reference": en["id"],
        "time_map": {"segments": [{"start": 0, "end": 30, "offset": -2.0, "confidence": 0.9},
                                  {"start": 40, "end": 80, "offset": -2.0,
                                   "confidence": 0.3, "method": "xcorr"}]}})
    assert made.status_code == 200, made.text
    body = made.json()["alignment"]
    merged = next(g for g in body["groups"] if g["source"] == ["ja-2", "ja-3"])
    assert merged["reference_text"].startswith("You took forever")
    window = client.get(f"/api/studio/sessions/{sid}/media/window", params={
        "source": f"reference:{en['id']}", "start": 10, "end": 14}).json()
    assert window["mapped_start"] == 12.0 and window["state"] == "mapped"
    assert window["peaks"]
    weak = client.get(f"/api/studio/sessions/{sid}/media/window", params={
        "source": f"reference:{en['id']}", "start": 45, "end": 47}).json()
    assert weak["state"] == "uncertain"
    cut = client.get(f"/api/studio/sessions/{sid}/media/audio", params={
        "source": f"reference:{en['id']}", "start": 30, "end": 34})
    assert cut.status_code == 409 and "cut" in cut.json()["error"]
    audio = client.get(f"/api/studio/sessions/{sid}/media/audio", params={
        "source": "original", "start": 1, "end": 3}, headers={"Range": "bytes=0-99"})
    assert audio.status_code == 206 and audio.headers["content-type"] == "audio/wav"
    excluded = client.post(f"/api/studio/alignments/{body['id']}/overrides", json={
        "base_revision": body["revision"], "action": "exclude", "group_id": merged["group_id"]})
    assert excluded.status_code == 200
    stale = client.post(f"/api/studio/alignments/{body['id']}/overrides", json={
        "base_revision": body["revision"], "action": "include", "group_id": merged["group_id"]})
    assert stale.status_code == 409


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_video_context_is_a_browser_playable_proxy(client_factory, tmp_path):
    import subprocess

    client = client_factory()
    media = tmp_path / "episode.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=320x240:rate=10:duration=4", "-c:v", "mpeg4", str(media)],
                   check=True)
    sid = client.post("/api/studio/sessions", json={"path": str(media),
                                                    "title": "Ep"}).json()["session"]["id"]
    video = client.get(f"/api/studio/sessions/{sid}/media/video",
                       params={"start": 1, "end": 3})
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    probe = client.get(f"/api/studio/sessions/{sid}/probe").json()
    assert probe["streams"][0]["type"] == "video"
    too_long = client.get(f"/api/studio/sessions/{sid}/media/video",
                          params={"start": 0, "end": 900})
    assert too_long.status_code == 422


def test_export_reuses_takes_and_refuses_surprise_generation(client_factory, tmp_path):
    client = client_factory()
    queued, job = review_client(client, tmp_path)
    sid = studio(client, tmp_path, job)["id"]
    plan = client.get(f"/api/studio/sessions/{sid}/export",
                      params={"job_id": queued.id}).json()
    assert plan["stale"] == 0 and len(plan["unresolved"]) == 4 and not plan["version_saved"]
    nothing = client.post(f"/api/studio/sessions/{sid}/export", params={"job_id": queued.id},
                          json={})
    assert nothing.status_code == 409          # no saved version to hand over
    cue = plan["lines"][1]["cue"]
    queued_export = client.post(f"/api/studio/sessions/{sid}/export",
                                params={"job_id": queued.id},
                                json={"takes": {cue: plan["lines"][1]["take"]}}).json()
    assert queued_export["exported"] == "queued" and queued_export["generated"] == 0
    exported = client.app.state.jobs.get(queued_export["job"])
    edit = exported.overrides["dub.line_edits"]["1"]
    assert edit["take"] == plan["lines"][1]["take"] and edit["text"] == "linea 1"
    # A pending wording change on the run would generate speech: never by surprise.
    client.app.state.jobs.update(queued.id, overrides={"dub.line_edits": {
        "2": {"cue": plan["lines"][2]["cue"], "text": "otra cosa"}}})
    refused = client.post(f"/api/studio/sessions/{sid}/export", params={"job_id": queued.id},
                          json={"takes": {cue: plan["lines"][1]["take"]}})
    assert refused.status_code == 409 and refused.json()["error"]["lines"] == ["2"]
    allowed = client.post(f"/api/studio/sessions/{sid}/export", params={"job_id": queued.id},
                          json={"takes": {cue: plan["lines"][1]["take"]},
                                "allow_generation": True}).json()
    assert allowed["generated"] == 1


def run_studio_job(client, job_id, cancel=None):
    """Run one queued studio job synchronously through the real worker path."""
    worker = client.app.state.worker
    job = client.app.state.jobs.get(job_id)
    config = worker.config
    cancel_evt = cancel or threading.Event()
    worker._studio(job, config, cancel_evt, lambda *a: None)
    return client.app.state.jobs.get(job_id)


def test_audition_is_bounded_resumable_and_honest_about_engines(client_factory, tmp_path):
    client = client_factory()
    queued, job = review_client(client, tmp_path)
    vb = FakeVoicebox()
    client.app.state.services._cache["voicebox"] = vb
    sid = studio(client, tmp_path, job)["id"]
    made = client.post(f"/api/studio/sessions/{sid}/auditions", json={
        "character": "B", "job_id": queued.id, "per_category": 2,
        "candidates": [
            {"name": "current", "kind": "current"},
            {"name": "preset", "kind": "preset", "engine": "qwen_custom_voice", "voice": "vb-9"},
            {"name": "told", "kind": "directed", "engine": "chatterbox", "voice": "vb-9",
             "direction": "whisper it"},
            {"name": "clone", "kind": "clone_character", "engine": "chatterbox"}]})
    assert made.status_code == 200, made.text
    audition = made.json()["audition"]
    plan = audition["plan"]
    assert set(plan["missing"]) == {"calm", "quiet", "intense"}   # no measurements here
    assert any("no source level measurement" in n for n in plan["notes"])
    lines = len(plan["excerpts"])
    assert lines == 2
    # Stop after the first generated take, then resume.
    stop = threading.Event()
    vb.gate = lambda n: stop.set()   # cancelled while the first take is generating
    run = client.post(f"/api/studio/auditions/{audition['id']}/run").json()["job"]
    first = run_studio_job(client, run["id"], cancel=stop)
    assert first.status == "cancelled"
    before = len(vb.generated)
    vb.gate = None
    again = client.post(f"/api/studio/auditions/{audition['id']}/run").json()["job"]
    done = run_studio_job(client, again["id"])
    assert done.status == "done", done.message
    result = client.get(f"/api/studio/auditions/{audition['id']}").json()["audition"]
    states = {c["name"]: c["status"] for c in result["candidates"]}
    assert states["told"] == "unsupported"          # chatterbox takes no direction
    assert states["clone"] == "unavailable"         # no original-language stem on disk
    assert states["preset"] == "generated"
    # Only the preset generated, once per excerpt; the resume paid only for what was missing.
    assert len(vb.generated) == lines
    assert before >= 1 and len(vb.generated) - before == lines - before
    assert all("instruct" not in g for g in vb.generated)
    take = result["takes"]["preset"][plan["excerpts"][0]["cue_id"]]
    assert take["available"] and "path" not in take
    audio = client.get(f"/api/studio/auditions/{audition['id']}/takes/preset/"
                       f"{plan['excerpts'][0]['cue_id']}")
    assert audio.status_code == 200
    # Choosing the preset casts B only, and queues only B's lines.
    chosen = client.post(f"/api/studio/auditions/{audition['id']}/select", json={
        "candidate": "preset", "scope": "episode", "apply": True}).json()
    rerun = client.app.state.jobs.get(chosen["rerender"]["job"])
    edits = rerun.overrides["dub.line_edits"]
    speakers = {e["cue"] for e in edits.values() if e.get("voice") == "vb-9"}
    assert len(speakers) == chosen["rerender"]["generating"] == 2     # lines 0 and 2 are B
    assert all(e.get("voice") in (None, "vb-9") for e in edits.values())
    cast = client.get(f"/api/studio/sessions/{sid}/casting").json()
    row = next(r for r in cast["speakers"] if r["speaker"] == "B")
    assert row["source"] == "episode" and row["voice"] == "vb-9"
    saved = client.app.state.jobs.db.load_cast(__import__("doblarr.voices", fromlist=[
        "cast_key"]).cast_key(path=str(job.input_file)))
    assert next(e for e in saved["cast"] if e["speaker_id"] == "B")["voice"] == "vb-9"


def test_experiment_runs_through_the_queue_with_the_guard(client_factory, tmp_path,
                                                          monkeypatch):
    client = client_factory()
    _queued, job = review_client(client, tmp_path)
    work = client.app.state.worker.config.work_dir
    sid = studio(client, tmp_path, job)["id"]
    ja = meaning(client, sid, work)
    en = client.post(f"/api/studio/sessions/{sid}/references", json={
        "label": "English dub", "language": "en", "roles": ["adaptation"],
        "text": {"kind": "dub_transcript"}, "utterances": ENGLISH}).json()["reference"]
    es = client.post(f"/api/studio/sessions/{sid}/references", json={
        "label": "Official dub", "language": "es-MX", "roles": ["evaluation"],
        "text": {"kind": "dub_transcript"}, "utterances": SPANISH}).json()["reference"]
    aligned = client.post(f"/api/studio/sessions/{sid}/alignments", json={
        "source": ja["id"], "reference": en["id"],
        "time_map": {"segments": [{"start": 0, "end": 1000, "offset": -2.0}]}}).json()
    created = client.post(f"/api/studio/sessions/{sid}/experiments", json={
        **DEFINITION, "meaning": ja["id"], "adaptation": en["id"], "evaluation": [es["id"]],
        "alignment": aligned["alignment"]["id"], "sentinels": [SENTINEL]})
    assert created.status_code == 200, created.text
    eid = created.json()["experiment"]["id"]
    # Roles frozen into an experiment cannot change under it.
    ref = client.get(f"/api/studio/sessions/{sid}").json()["references"]
    en_rev = next(r for r in ref if r["id"] == en["id"])["revision"]
    assert client.patch(f"/api/studio/references/{en['id']}", json={
        "base_revision": en_rev, "roles": ["meaning"]}).status_code in (409, 422)
    driver = RecordingDriver(echo_answer())
    install_driver(monkeypatch, driver)
    monkeypatch.setattr("doblarr.studio.runner.translator_for",
                        lambda experiment, services: __import__(
                            "tests.studio_fixtures", fromlist=["translator"]).translator())
    run = client.post(f"/api/studio/experiments/{eid}/run", json={}).json()["job"]
    finished = run_studio_job(client, run["id"])
    assert finished.status == "done", finished.message
    assert "A1:complete" in finished.message and "C1:complete" in finished.message
    assert all(SENTINEL not in p for p in driver.prompts)
    detail = client.get(f"/api/studio/experiments/{eid}").json()
    assert {v["condition"] for v in detail["variants"]} == {"A", "B", "C"}
    assert all(v["frozen"] for v in detail["variants"])
    evaluation = client.post(f"/api/studio/experiments/{eid}/evaluations", json={}).json()
    vid = evaluation["evaluation"]["id"]
    assert evaluation["evaluation"]["mapping"] is None
    early = client.get(f"/api/studio/evaluations/{vid}/holdout")
    assert early.status_code == 409
    rev = evaluation["evaluation"]["revision"]
    revealed = client.post(f"/api/studio/evaluations/{vid}/reveal/holdout",
                           params={"base_revision": rev, "actor": "tester"})
    assert revealed.status_code == 200
    assert client.get(f"/api/studio/evaluations/{vid}/holdout").status_code == 200
    exported = client.get(f"/api/studio/evaluations/{vid}/export").json()
    assert exported["summary"]["gate"]["state"] == "insufficient"
    assert any("training" in x for x in exported["experiment"]["limitations"])


def test_legacy_import_through_the_api(client_factory, tmp_path):
    from tests.test_studio_core import legacy

    client = client_factory()
    _queued, job = review_client(client, tmp_path)
    sid = studio(client, tmp_path, job)["id"]
    work = client.app.state.worker.config.work_dir
    path = legacy(work.parent)
    preview = client.post(f"/api/studio/sessions/{sid}/imports/preview",
                          json={"path": str(path)})
    assert preview.status_code == 200, preview.text
    found = preview.json()["preview"]
    unmapped = client.post(f"/api/studio/sessions/{sid}/imports", json={"path": str(path)})
    assert unmapped.status_code == 422
    applied = client.post(f"/api/studio/sessions/{sid}/imports", json={
        "path": str(path), "mapping": {
            "speakers": {s: s for s in found["speakers"]},
            "tracks": {t["key"]: t["legacy_role"] for t in found["tracks"]}}}).json()
    iid = applied["import"]["id"]
    played = client.get(f"/api/studio/imports/{iid}/media",
                        params={"scene": 0, "kind": "mixed", "name": "baseline"})
    assert played.status_code == 200
    missing = client.get(f"/api/studio/imports/{iid}/media",
                         params={"scene": 0, "kind": "mixed", "name": "improved"})
    assert missing.status_code == 404
    results = client.post(f"/api/studio/imports/{iid}/results", json={
        "name": "results.md", "text": "# Listening results — cmp-1\n\n## Scene 1 — Talk\n\n"
                                      "- Best: **A**\n- Issues: (none marked)\n- Note: ok\n"})
    assert results.json()["import"]["judgments"] == 1
    outside = client.post(f"/api/studio/sessions/{sid}/imports/preview",
                          json={"path": str(tmp_path / "elsewhere.json")})
    assert outside.status_code == 403


def test_worker_dispatch_keeps_one_queue(client_factory, tmp_path):
    client = client_factory()
    store = client.app.state.jobs
    job = store.add(title="Transcribe", source="studio", source_lang="en", target_lang="und",
                    kind="studio_transcribe", task={"reference": "missing", "session": "s"})
    assert store.next_queued().id == job.id           # same queue as any dub
    finished = run_studio_job(client, job.id)
    assert finished.status == "failed" and "no longer exists" in finished.message

