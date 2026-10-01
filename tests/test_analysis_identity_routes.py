"""Analysis routes keyed by content: names, hand-moved lines, regroups and coverage."""

import json
import struct
import wave

import numpy as np


def _unit(*values):
    v = np.asarray(values, dtype=np.float64)
    return v / np.linalg.norm(v)


def _episode(tmp_path, work, payload=b"harbor-lights-e02" * 400):
    media_file = tmp_path / "library" / "Harbor Lights" / "Season 01" / "e02.mkv"
    media_file.parent.mkdir(parents=True, exist_ok=True)
    media_file.write_bytes(payload)
    folder = work / "media" / "abc"
    locale = folder / "es-419"
    locale.mkdir(parents=True)
    rows = [("SPEAKER_00", 0.0, 3.0, -18.0), ("SPEAKER_01", 4.0, 6.0, -20.0),
            ("SPEAKER_00", 7.0, 9.0, -12.0)]
    (locale / "e02.script.json").write_text(json.dumps({
        "script_lang": "en", "identity": {"input": str(media_file), "source_lang": "ja"},
        "segments": [{"index": i, "speaker": spk, "start": a, "end": b, "text_src": "line",
                      "issues": [], "cue": {
                          "cue_id": f"c{i}",
                          "source": {"spans": [{"start": a, "end": b, "domain": "source"}]},
                          "measurement": {"state": "measured", "speech_db": level}}}
                     for i, (spk, a, b, level) in enumerate(rows)]}), encoding="utf-8")
    with wave.open(str(folder / "e02.vocals.wav"), "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        out.writeframes(b"".join(struct.pack("<h", 0) for _ in range(16000 * 10)))
    (folder / "e02.speakers.json").write_text(json.dumps({
        "model": "m", "lines": [
            {"cue": f"c{i}", "start": a, "end": b, "speaker": spk,
             "vector": list(_unit(1, i * 0.1, 0)),
             "why": {"method": "clustered", "candidates": [], "margin": 0.2}}
            for i, (spk, a, b, _l) in enumerate(rows)]}), encoding="utf-8")
    return media_file


def test_names_follow_the_content_not_the_file_name(client_factory, tmp_path):
    client = client_factory()
    work = client.app.state.worker.config.work_dir
    episode = _episode(tmp_path, work)
    saved = client.put("/api/analysis/names", json={"path": str(episode), "names": {
        "SPEAKER_00": "Kaito", "SPEAKER_01": "Mina"}}).json()
    assert saved["identity"]["revision_id"].startswith("rev-c")
    data = client.get("/api/analysis", params={"path": str(episode)}).json()
    assert data["names_from"] == "identity" and data["lines"][1]["character"] == "Mina"
    assert {c["name"] for c in data["cast"]} >= {"Kaito", "Mina"}
    # A copy of the same file elsewhere is the same episode.
    copy = tmp_path / "elsewhere" / "copy-of-e02.mkv"
    copy.parent.mkdir()
    copy.write_bytes(episode.read_bytes())
    # (its analysis is found through the revision's snapshot or the exact script)
    other = tmp_path / "other-show" / "e02.mkv"
    other.parent.mkdir()
    other.write_bytes(b"a different episode" * 300)
    stranger = client.get("/api/analysis", params={"path": str(other)}).json()
    assert stranger["names"] == {}            # same file name, different content
    assert stranger["script_match"] in ("name", "ambiguous")


def test_a_moved_line_stays_moved_and_baselines_follow(client_factory, tmp_path, monkeypatch):
    from doblarr import speakers

    client = client_factory()
    work = client.app.state.worker.config.work_dir
    episode = _episode(tmp_path, work)
    client.put("/api/analysis/names", json={"path": str(episode), "names": {
        "SPEAKER_00": "Kaito", "SPEAKER_01": "Mina"}})
    moved = client.put("/api/analysis/line", json={"path": str(episode), "cue": "c2",
                                                    "character": "mina"}).json()
    assert moved["character"] == "Mina" and moved["speaker"] == "SPEAKER_01"
    data = client.get("/api/analysis", params={"path": str(episode)}).json()
    assert data["lines"][2]["locked"] and data["lines"][2]["character"] == "Mina"
    stages = {r["stage"]: r["state"] for r in data["coverage"]}
    assert stages["baselines"] == "done" and stages["speaker_memory"] == "done"
    # A regroup that puts every line in one voice: Mina's hand-moved line moves back.
    monkeypatch.setattr(speakers, "embed", lambda *a, **k: [
        _unit(1, 0, 0), _unit(1, 0.01, 0), _unit(1, 0.02, 0)])
    result = client.post("/api/analysis/regroup", json={
        "path": str(episode), "models": ["nemo-titanet-large"], "tracks": []}).json()
    assert result["relocked"] == 1
    after = client.get("/api/analysis", params={"path": str(episode)}).json()
    assert after["lines"][2]["character"] == "Mina" and after["lines"][2]["locked"]
    assert after["lines"][0]["character"] == "Kaito"
    # Unlocking hands the line back to the grouping for the next regroup.
    assert client.post("/api/analysis/line/unlock", json={
        "path": str(episode), "cue": "c2"}).status_code == 200
    client.post("/api/analysis/regroup", json={
        "path": str(episode), "models": ["nemo-titanet-large"], "tracks": []})
    final = client.get("/api/analysis", params={"path": str(episode)}).json()
    assert not final["lines"][2]["locked"]


def test_coverage_and_the_rerun_request_never_queue_a_dub(client_factory, tmp_path):
    client = client_factory()
    work = client.app.state.worker.config.work_dir
    episode = _episode(tmp_path, work)
    coverage = client.get("/api/analysis/coverage", params={"path": str(episode)}).json()
    assert {r["stage"] for r in coverage["coverage"]} >= {"features", "faces"}
    bad = client.post("/api/analysis/rerun", json={"path": str(episode), "stages": ["dub"]})
    assert bad.status_code == 422
    queued = client.post("/api/analysis/rerun", json={"path": str(episode),
                                                     "stages": ["features"]}).json()
    job = client.app.state.jobs.get(queued["job_id"])
    assert job.kind == "analyze" and job.overrides == {"analysis.stages": ["features"]}


def test_visual_tracks_can_be_named_and_the_evidence_is_fused_again(client_factory, tmp_path):
    client = client_factory()
    work = client.app.state.worker.config.work_dir
    episode = _episode(tmp_path, work)
    folder = work / "media" / "abc"
    crops = work / "vision" / "crops"
    crops.mkdir(parents=True)
    (crops / "00001000-0-lbpcas.jpg").write_bytes(b"\xff\xd8\xff")
    vector = [0.5, 0.5, 0.5, 0.5]
    detections = [{"t": t, "box": [10, 10, 40, 40], "score": None,
                   "detector": "lbpcascade-animeface", "domain": "anime", "vector": vector,
                   "embedder": "dinov2-small", "crop": "00001000-0-lbpcas.jpg"}
                  for t in (0.5, 1.0, 1.5, 2.0, 2.5)]
    (folder / "es-419" / "e02.visual.json").write_text(json.dumps({
        "shots": {"shots": [{"id": "shot-0000", "start": 0.0, "end": 10.0}],
                  "video": {"duration": 10.0}, "method": "ffmpeg-scene/1"},
        "faces": {"detections": detections, "sampled": 20, "crops": str(crops)},
        "active": {"lines": {"c0": {}}}, "tracks": [], "scenes": [], "associations": []}),
        encoding="utf-8")
    data = client.get("/api/analysis/visual", params={"path": str(episode)}).json()
    assert data["analysed"] and data["tracks"] == []      # nothing fused yet
    client.post("/api/analysis/visual/scenes", json={"path": str(episode), "add": [5.0]})
    # Editing scenes re-fused the saved pass: tracks exist now, from the same detections.
    saved = json.loads((folder / "es-419" / "e02.visual.json").read_text(encoding="utf-8"))
    track_id = saved["tracks"][0]["id"]
    named = client.post("/api/analysis/visual/tracks", json={
        "path": str(episode), "assign": {track_id: "Kaito"}})
    assert named.status_code == 200
    data = client.get("/api/analysis/visual", params={"path": str(episode)}).json()
    track = next(t for t in data["tracks"] if t["id"] == track_id)
    assert track["character_name"] == "Kaito" and track["assigned"] == "manual"
    assert [s["start"] for s in data["scenes"]] == [0.0, 5.0]
    first = next(a for a in data["associations"] if a["cue"] == "c0")
    assert first["screen"] in ("onscreen-silent", "onscreen-speaking")
    thumb = client.get("/api/analysis/visual/thumb", params={
        "path": str(episode), "name": "00001000-0-lbpcas.jpg"})
    assert thumb.status_code == 200
    assert client.get("/api/analysis/visual/thumb", params={
        "path": str(episode), "name": "../secret.jpg"}).status_code == 422
