"""Adaptive audio through the real pipeline: envelopes, zero-TTS edits, prior path, bed policy.

These run real FFmpeg over the tone fixture. The tone engine counts every
generation request, so "a processing-only change made no speech request" is a
measured fact, not an assumption.
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from doblarr import bedpolicy, benchmarks, envelopes
from doblarr.config import Config
from doblarr.cues import LEVELED
from doblarr.models import DubJob
from doblarr.pipeline import run_job
from doblarr.services import Services
from doblarr.store import Database

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def run(root, media_root, overrides=None, engine=None, db=None, edits=None):
    media, subtitles = benchmarks.write_media(media_root, benchmarks.SCENE)
    config = Config.load(root / "config.yaml").with_overrides({
        "paths.work_dir": str(root / "work"), "paths.output_dir": str(root / "output"),
        "dub.dry_run": False, "dub.voice_mode": "preset", "dub.preset_voices": ["tone-voice"],
        "dub.preserve_versions": False, "transcribe.diarize": False,
        "translate.provider": "passthrough", "quality.asr": "off",
        **(overrides or {})})
    tone = engine or benchmarks.ToneEngine(root)
    services = Services(config)
    services._cache["speech"] = tone
    job = DubJob(input_file=media, source_lang="ja", target_lang="es", subtitle_file=subtitles)
    job.script_is_target = True
    if edits:
        job.envelope_edits = edits
    run_job(job, config, services=services, db=db)
    return job, tone


LEVELS = {"levels.mode": "consistent"}


def levelled(job):
    return {s.cue_id: s.audio.render(LEVELED).path for s in job.segments
            if s.audio.render(LEVELED)}


def test_apply_mode_renders_envelopes_through_the_level_owner(tmp_path):
    db = Database(tmp_path / "a.db")
    job, tone = run(tmp_path, tmp_path / "media", {**LEVELS, "adaptive.mode": "apply"}, db=db)
    report = json.loads(Path(job.metrics["adaptive"]["path"]).read_text(encoding="utf-8"))
    assert report["judge"] == "retrieval" and report["judge_is_model"] is False
    assert job.metrics["adaptive"]["states"]
    decided = [s for s in job.segments if s.envelope.template]
    assert decided, "every line should have a recorded choice (preserve counts)"
    assert all(s.envelope.origin in ("retrieval", "default") for s in decided)
    assert all(s.envelope.outcome in ("applied", "preserved", "unavailable")
               for s in decided)
    # The fixture has no separated dialogue: the original's shape is not
    # trustworthy evidence, so retrieval keeps every take as generated.
    assert report["lines"][decided[0].cue_id]["warnings"]
    for seg in job.segments:
        if seg.envelope.outcome == "applied":
            assert seg.envelope.peak is not None and seg.envelope.peak <= 0.89 + 1e-6
            assert seg.level.inputs and seg.audio.render(LEVELED)
    db.close()


def test_a_template_or_strength_change_reprocesses_with_zero_speech_requests(tmp_path):
    media = tmp_path / "media"
    db = Database(tmp_path / "a.db")
    engine = benchmarks.ToneEngine(tmp_path)
    first, _ = run(tmp_path, media, {**LEVELS, "adaptive.mode": "apply"}, engine=engine, db=db)
    generated = len(engine.requests)
    assert generated > 0
    cue = first.segments[0].cue_id
    before = levelled(first)
    second, _ = run(tmp_path, media, {**LEVELS, "adaptive.mode": "apply"}, engine=engine,
                    db=db, edits={cue: {"template": "voice/gradual-rise", "strength": 1.2}})
    assert len(engine.requests) == generated          # not one new speech request
    chosen = next(s for s in second.segments if s.cue_id == cue)
    assert chosen.envelope.origin == "manual" and chosen.envelope.locked
    assert chosen.envelope.template["id"] == "voice/gradual-rise"
    assert chosen.envelope.outcome in ("applied", "preserved")
    if chosen.envelope.outcome == "applied":
        assert levelled(second)[cue] != before[cue]
    third, _ = run(tmp_path, media, {**LEVELS, "adaptive.mode": "apply"}, engine=engine,
                   db=db, edits={cue: {"template": "voice/gradual-rise", "strength": 0.4}})
    assert len(engine.requests) == generated
    db.close()


def test_off_and_preserve_render_exactly_the_prior_path(tmp_path):
    # Same work folder: an identical level request reuses the identical file.
    media = tmp_path / "media"
    baseline, _ = run(tmp_path, media, LEVELS)
    off, _ = run(tmp_path, media, {**LEVELS, "adaptive.mode": "off"})
    assert levelled(baseline) == levelled(off)
    cue = baseline.segments[0].cue_id
    cleared, _ = run(tmp_path, media, LEVELS, edits={cue: {"clear": True}})
    seg = next(s for s in cleared.segments if s.cue_id == cue)
    assert seg.envelope.outcome == "preserved"
    assert levelled(cleared)[cue] == levelled(baseline)[cue]


def test_without_a_level_owner_envelopes_are_reported_not_stacked(tmp_path):
    from doblarr.cues import imported_cue_id, script_ref

    media, subtitles = benchmarks.write_media(tmp_path / "media", benchmarks.SCENE)
    cue = imported_cue_id(script_ref(media, "ja", subtitles), 0)
    job2, _ = run(tmp_path, tmp_path / "media", {"levels.mode": "legacy"},
                  edits={cue: {"template": "voice/late-emphasis"}})
    seg = next(s for s in job2.segments if s.cue_id == cue)
    assert seg.envelope.outcome == "unsupported" and "no post-fit level owner" in \
        seg.envelope.reason
    assert seg.audio.render(LEVELED) is None


def test_a_bed_policy_replaces_the_sidechain_and_keeps_the_timeline(tmp_path, monkeypatch):
    from doblarr.stages import separate

    def fake_separate(job, work_dir, **kwargs):
        bed = Path(work_dir) / "fixture.bed.wav"
        if not bed.is_file():
            seconds = 12.5
            t = np.arange(int(seconds * 48000)) / 48000
            envelopes.write_wav(bed, (0.2 * np.sin(2 * np.pi * 110 * t))[:, None]
                                .repeat(2, axis=1), 48000)
        job.vocals = job.source_audio
        job.background = bed

    monkeypatch.setattr(separate, "run", fake_separate)
    db = Database(tmp_path / "a.db")
    job, _ = run(tmp_path, tmp_path / "media", {
        **LEVELS, "adaptive.mode": "apply",
        "adaptive.background_policy": "background/strong-ducking"}, db=db)
    policy = job.metrics["background_policy"]
    assert policy["state"] == "applied" and policy["sidechain"] == "bypassed"
    assert job.metrics["mix_ducking"].startswith("bed policy")
    assert policy["stats"]["min_db"] >= -18.0 and policy["stats"]["ducked_share"] > 0
    import wave

    with wave.open(str(job.dubbed_track), "rb") as mixed:
        assert mixed.getnchannels() == 2
    db.close()


def test_the_bed_plan_is_bounded_smooth_and_holds_through_short_gaps():
    params = {"trim_db": 0.0, "duck_db": -10.0, "attack_ms": 60, "release_ms": 300,
              "hold_ms": 100, "gap_recover_s": 0.8}
    plan = bedpolicy.plan(params, [(1.0, 2.0), (2.4, 3.0), (6.0, 7.0)], 9.0,
                          max_attenuation_db=8.0)
    curve = plan["curve"]
    assert min(curve) >= -8.0                          # bounded total attenuation
    hesitation = curve[int(2.2 / bedpolicy.HOP)]
    assert hesitation < -6.0                           # stays down through a 0.4 s gap
    assert curve[int(4.8 / bedpolicy.HOP)] > -1.0      # recovers in a real pause
    # No step is faster than the attack law allows (60 ms toward -10 dB).
    import math

    assert plan["stats"]["max_step_db"] <= 10 * (1 - math.exp(-0.01 / 0.06)) + 1e-3


def test_an_impact_in_the_bed_is_not_buried():
    params = {"trim_db": 0.0, "duck_db": -10.0, "attack_ms": 20, "release_ms": 200,
              "transient_db": 8.0}
    level = [-40.0] * 600
    for i in range(300, 312):
        level[i] = -10.0                               # a sting at 3.0 s
    plan = bedpolicy.plan(params, [(1.0, 5.0)], 6.0, bed_level=level)
    assert plan["stats"]["transient_frames"] > 0
    assert plan["curve"][305] > plan["curve"][200]


def test_the_studio_reads_recommendations_selects_and_compares_the_same_take(client_factory,
                                                                           tmp_path):
    client = client_factory()
    store = client.app.state.jobs
    job, _ = run(tmp_path, tmp_path / "media", {**LEVELS, "adaptive.mode": "apply"},
                 db=store.db)
    row = store.add(title="Harbor Lights", source="test", source_lang="ja", target_lang="es",
                    input_file=str(job.input_file),
                    overrides={**LEVELS, "adaptive.mode": "apply"})
    store.update(row.id, status="done", review_file=str(job.review_file))
    config = client.app.state.worker.config
    original_work = config.work_dir
    config._data["paths"]["work_dir"] = str(tmp_path / "work")    # the run's work folder
    try:
        data = client.get("/api/adaptive/recommendations", params={"job_id": row.id}).json()
        assert data["mode"] == "apply" and data["judge"] == "retrieval"
        line = data["lines"][0]
        assert line["envelope"]["template"]["id"] and line["candidates"]
        picked = client.post("/api/adaptive/select", json={
            "job_id": row.id, "cue": line["cue"], "template": "voice/gradual-rise",
            "strength": 0.9}).json()
        assert picked["speech"] is False and picked["work"] == "processing"
        queued = store.get(picked["job"])
        assert queued.overrides["adaptive.lines"][line["cue"]]["template"] == \
            "voice/gradual-rise"
        dry = client.get("/api/adaptive/audio", params={"job_id": row.id, "cue": line["cue"],
                                                        "kind": "dry"})
        assert dry.status_code == 200 and dry.headers["x-level-matched"] == "false"
        shaped = client.get("/api/adaptive/audio", params={
            "job_id": row.id, "cue": line["cue"], "kind": "shaped", "level_matched": True})
        assert shaped.status_code == 200 and shaped.headers["x-level-matched"] == "true"
        assert client.post("/api/adaptive/select", json={
            "job_id": row.id, "cue": line["cue"]}).status_code == 422
    finally:
        config._data["paths"]["work_dir"] = str(original_work)
