"""Line features, analysis snapshots, grouping diagnostics, baselines and track alignment."""

import json
import math
import struct
import wave

import numpy as np
import pytest

from doblarr import features, snapshots, speaker_memory, speakers, track_alignment
from doblarr.store import Database

RATE = 16000


def write(path, samples, rate=RATE):
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(np.asarray(samples, dtype=np.float64), -1, 1)
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        out.writeframes(b"".join(struct.pack("<h", int(v * 32767)) for v in clipped))
    return path


def sine(seconds, amplitude, hz=220.0, rate=RATE):
    t = np.arange(int(seconds * rate)) / rate
    return amplitude * np.sin(2 * np.pi * hz * t)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "a.db")
    yield database
    database.close()


def test_a_steady_tone_reads_its_true_sample_rms():
    result = features.measure(sine(1.0, 0.5).astype(np.float32))
    # RMS of a sine is amplitude / sqrt(2): 0.5 -> -9.03 dBFS.
    assert result["quality"] == "ok" and result["mean_db"] == pytest.approx(-9.03, abs=0.15)
    assert result["active_seconds"] == pytest.approx(1.0, abs=0.05)
    assert result["pauses"] == [] and len(result["curve"]) == features.CURVE_POINTS
    assert result["range_db"] < 1.0


def test_a_pause_and_a_late_peak_are_found_where_they_are():
    audio = np.concatenate([sine(0.6, 0.1), np.zeros(int(0.4 * RATE)), sine(0.4, 0.6)])
    result = features.measure(audio.astype(np.float32))
    assert len(result["pauses"]) == 1
    pause = result["pauses"][0]
    assert pause["start"] == pytest.approx(0.6, abs=0.06)
    assert pause["seconds"] == pytest.approx(0.4, abs=0.08)
    loudest = result["peaks"][0]
    assert loudest["position"] > 0.6           # the emphasis sits late in the line
    assert result["curve"][-3] > result["curve"][2] + 10


def test_too_little_or_no_audio_is_said_plainly_not_zeroed():
    short = features.measure(sine(0.15, 0.4).astype(np.float32))
    assert short["quality"] == "insufficient" and short["reasons"]
    empty = features.measure(np.zeros(0, dtype=np.float32))
    assert empty["quality"] == "missing" and "mean_db" not in empty
    flagged = features.measure(sine(1.0, 0.3).astype(np.float32), flags=["overlap"])
    assert flagged["quality"] == "contaminated" and flagged["mean_db"] is not None


def test_chunked_decoding_reads_the_same_samples_as_one_pass(tmp_path):
    path = write(tmp_path / "long.wav", np.concatenate([sine(3.0, 0.2), sine(3.0, 0.5, 330)]))
    reader = features.ChunkedAudio(path, chunk=2.0)
    across = reader.span(1.5, 4.5)
    direct = features.decode(path, 1.5, 3.0)
    assert len(across) == len(direct)
    assert np.allclose(across, direct, atol=1e-4)
    lines, stats = features.measure_lines(path, [(0.2, 1.0), (3.5, 4.5), (2.5, 3.5)])
    assert lines[1]["mean_db"] > lines[0]["mean_db"] + 6
    assert stats["decoded_seconds"] < 12     # chunks, not the whole file per line


def test_snapshot_stages_go_stale_only_through_their_dependencies(db):
    snapshots.record_stage(db, "rev-1", "ja", "transcribe", "done", inputs=["spans-a"])
    snapshots.record_stage(db, "rev-1", "ja", "diarize", "done", inputs=["labels-a"])
    snapshots.record_stage(db, "rev-1", "ja", "features", "done", inputs=["curves-a"])
    snapshots.record_stage(db, "rev-1", "ja", "baselines", "done", inputs=["base-a"])
    snapshots.record_stage(db, "rev-1", "ja", "diarize", "done", inputs=["labels-b"])
    stages = snapshots.get(db, "rev-1", "ja")["stages"]
    assert stages["baselines"]["state"] == "stale"      # depends on who is in each group
    assert stages["features"]["state"] == "done"        # depends on audio and spans only
    assert snapshots.rerunnable(snapshots.get(db, "rev-1", "ja")) == ["baselines"]
    # Recording the same inputs again changes nothing downstream.
    snapshots.record_stage(db, "rev-1", "ja", "baselines", "done", inputs=["base-b"])
    snapshots.record_stage(db, "rev-1", "ja", "diarize", "done", inputs=["labels-b"])
    assert snapshots.get(db, "rev-1", "ja")["stages"]["baselines"]["state"] == "done"


def test_coverage_shows_unsupported_and_missing_stages_apart(db):
    snapshots.record_stage(db, "rev-2", "", "probe", "done", inputs=[1])
    rows = {r["stage"]: r for r in snapshots.coverage(
        snapshots.get(db, "rev-2", ""), {"faces": "OpenCV is not installed"})}
    assert rows["probe"]["state"] == "done" and rows["features"]["state"] == "missing"
    assert rows["faces"]["state"] == "unsupported" and "OpenCV" in rows["faces"]["reason"]
    assert rows["faces"]["group"] == "visual"


def _unit(*values):
    v = np.asarray(values, dtype=np.float64)
    return v / np.linalg.norm(v)


def test_grouping_keeps_why_each_line_got_its_voice():
    a, b = _unit(1, 0, 0), _unit(0, 1, 0)
    vectors = [a, a, b, None, a, b]
    labels, why = speakers.cluster_detailed(vectors, [2.0, 2.0, 2.0, 0.2, 0.5, 2.0], 0.5)
    methods = [line["method"] for line in why["lines"]]
    assert methods == ["clustered", "clustered", "clustered", "inherited", "nearest",
                       "clustered"]
    assert labels[3] == labels[2]                  # no voice: takes the previous speaker
    assert why["lines"][3]["candidates"] == []     # and is never shown as heard
    assert why["lines"][0]["margin"] == pytest.approx(1.0, abs=1e-6)


def test_a_small_group_merged_into_a_larger_one_is_recorded():
    rng = np.random.default_rng(3)
    main = [_unit(*(np.array([1.0, 0, 0]) + rng.normal(0, 0.05, 3))) for _ in range(30)]
    other = [_unit(*(np.array([0, 1.0, 0]) + rng.normal(0, 0.05, 3))) for _ in range(5)]
    brief = [_unit(0.3, 0.3, 1.0)]
    labels, why = speakers.cluster_detailed(main + other + brief, [2.0] * 36, 0.3)
    assert len(set(labels)) == 2
    assert why["merges"] and why["merges"][0]["lines"] == 1
    assert why["lines"][-1]["method"] == "merged_small"


def _script(path, rows):
    segments = []
    for i, (speaker, start, end, db_) in enumerate(rows):
        segments.append({"index": i, "start": start, "end": end, "speaker": speaker,
                         "text_src": "", "issues": [], "cue": {
                             "cue_id": f"c{i}", "source": {"spans": [
                                 {"start": start, "end": end, "domain": "source"}]},
                             "measurement": {"state": "measured", "speech_db": db_,
                                             "units": "dBFS-rms-speech",
                                             "method": "speech-rms/1"}}})
    path.write_text(json.dumps({"segments": segments}), encoding="utf-8")
    return path


def test_moving_lines_recomputes_baselines_but_reuses_raw_measurements(tmp_path):
    rows = [("A", i * 2.0, i * 2.0 + 1.5, -20.0) for i in range(6)]
    rows += [("B", 20 + i * 2.0, 21.5 + i * 2.0, -10.0) for i in range(6)]
    rows += [("A", 40.0, 41.5, -10.0)]           # a B line filed under A
    script = _script(tmp_path / "e.script.json", rows)
    first = speaker_memory.refresh_baselines(script)
    data = json.loads(script.read_text(encoding="utf-8"))
    misfiled = data["segments"][-1]["cue"]["measurement"]
    assert misfiled["relative_db"] == pytest.approx(10.0)    # loud against A's baseline
    data["segments"][-1]["speaker"] = "B"
    script.write_text(json.dumps(data), encoding="utf-8")
    second = speaker_memory.refresh_baselines(script)
    after = json.loads(script.read_text(encoding="utf-8"))["segments"][-1]["cue"]["measurement"]
    assert after["speech_db"] == -10.0 and after["relative_db"] == pytest.approx(0.0)
    assert second["changed"] >= 1 and first["baseline"]["scope"] == "speaker"


def test_overlap_follows_the_groups_it_depends_on(tmp_path):
    rows = [("A", 0.0, 2.0, -20.0), ("B", 1.0, 3.0, -20.0)]
    script = _script(tmp_path / "o.script.json", rows)
    speaker_memory.refresh_baselines(script)
    first = json.loads(script.read_text(encoding="utf-8"))["segments"][0]["cue"]["measurement"]
    assert first["overlapped"] and first["state"] == "contaminated"
    data = json.loads(script.read_text(encoding="utf-8"))
    data["segments"][1]["speaker"] = "A"         # one person, not cross-talk
    script.write_text(json.dumps(data), encoding="utf-8")
    speaker_memory.refresh_baselines(script)
    now = json.loads(script.read_text(encoding="utf-8"))["segments"][0]["cue"]["measurement"]
    assert not now["overlapped"] and now["state"] == "measured"


def _envelope(seed, frames):
    rng = np.random.default_rng(seed)
    base = rng.normal(-30, 8, frames)
    return list(np.convolve(base, np.ones(5) / 5, mode="same"))


def test_an_offset_dub_is_verified_with_its_offset():
    reference = _envelope(1, 6000)
    lag = 12                      # 0.6 s late
    track = [-60.0] * lag + reference[:-lag]
    result = track_alignment.align(reference, track, max_offset=2.0, min_correlation=0.4)
    assert result["state"] == "verified"
    assert result["offset"] == pytest.approx(-0.6, abs=0.06) and result["rate"] == 1.0


def test_a_track_from_another_edit_is_rejected():
    reference = _envelope(2, 6000)
    track = reference[:3000] + _envelope(9, 3000)
    result = track_alignment.align(reference, track, max_offset=2.0, min_correlation=0.3)
    assert result["state"] in ("rejected", "uncertain")


def test_commentary_and_evaluation_tracks_are_never_used(tmp_path):
    ref = write(tmp_path / "ref.wav", sine(3.0, 0.3))
    rows = track_alignment.check_tracks(ref, [
        {"stream": 2, "path": ref, "lang": "en", "title": "Director commentary"},
        {"stream": 3, "path": ref, "lang": "es", "title": "Latino"},
    ], evaluation_streams={3})
    assert [r["state"] for r in rows] == ["excluded", "excluded"]
    assert track_alignment.usable(rows) == set()


def test_alignment_maps_a_line_onto_the_dub_timeline(monkeypatch, tmp_path):
    seen = {}

    def fake_embed(path, spans, *args, **kwargs):
        seen[str(path)] = spans
        return [np.ones(3) / math.sqrt(3) for _ in spans]

    monkeypatch.setattr(speakers, "embed", fake_embed)
    speakers.embed_with(tmp_path / "main.wav", [tmp_path / "dub.wav"], [(10.0, 12.0)],
                        maps=[{"offset": -0.5, "rate": 1.0}])
    assert seen[str(tmp_path / "dub.wav")] == [(10.5, 12.5)]
