"""Voice models to choose from, voice tags that remember a show's cast, and
regrouping an analysed episode without analysing it again."""

import json
import math
from types import SimpleNamespace

import pytest

from doblarr import speakers, voice_models, voice_tags


class FakeDb:
    def __init__(self):
        self.plans = {}

    def save_plan(self, key, title, plan):
        self.plans[key] = {"title": title, "plan": json.loads(json.dumps(plan))}

    def load_plan(self, key):
        return self.plans.get(key)


def _config(**speakers_section):
    return SimpleNamespace(get=lambda key, default=None: speakers_section
                           if key == "speakers" else default, work_dir="w")


def test_three_families_are_built_in_and_a_person_can_register_their_own():
    families = {m.family for m in voice_models.BUILT_IN.values()}
    assert {"WeSpeaker", "3D-Speaker (Alibaba)", "NeMo (NVIDIA)"} <= families
    config = _config(custom=[{"id": "mine", "name": "Mine", "url": "https://x/m.onnx"},
                             {"name": "no id"}])
    known = voice_models.catalog(config)
    assert known["mine"].custom and known["mine"].filename == "m.onnx"
    assert "no id" not in known
    with pytest.raises(ValueError, match="unknown voice model"):
        voice_models.resolve(["nope"], config)


def test_by_default_two_models_are_joined_and_compared_at_their_mean_distance():
    picked = voice_models.resolve(voice_models.chosen(_config()))
    assert [m.id for m in picked] == voice_models.RECOMMENDED
    assert voice_models.threshold(picked) == pytest.approx((0.7 + 0.55) / 2, abs=1e-3)
    assert voice_models.threshold(picked, 0.4) == 0.4
    assert voice_models.chosen(_config(models="nemo-titanet-large")) == ["nemo-titanet-large"]


def test_a_model_downloads_once_and_a_cut_download_is_never_used(tmp_path, monkeypatch):
    import requests

    model = voice_models.BUILT_IN["nemo-titanet-small"]
    calls = []

    class Response:
        def __init__(self, body, size):
            self.body, self.headers = body, {"content-length": str(size)}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, _):
            yield self.body

    def get(url, **kw):
        calls.append(url)
        return Response(b"onnx", 4) if len(calls) > 1 else Response(b"on", 4)

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(OSError, match="stopped"):
        voice_models.download(model, tmp_path)
    assert not list(tmp_path.iterdir())
    path = voice_models.download(model, tmp_path)
    assert path.read_bytes() == b"onnx" and voice_models.is_ready(model, tmp_path)
    voice_models.download(model, tmp_path)
    assert len(calls) == 2                       # already on disk: no third request


def _unit(*values):
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def test_in_a_full_episode_a_one_or_two_line_group_joins_its_nearest_voice():
    np = pytest.importorskip("numpy")
    a, b, a_shout = _unit(1, 0, 0), _unit(0, 1, 0), _unit(0.6, 0.1, 0.8)
    vectors = [np.array(a)] * 20 + [np.array(b)] * 20 + [np.array(a_shout)] * 2
    labels = speakers.cluster(vectors, [2.0] * len(vectors), threshold=0.3)
    assert len(set(labels)) == 2 and labels[-1] == labels[0]
    # In a short clip two lines may well be a real character.
    short = speakers.cluster(vectors[:3] + vectors[20:22] + vectors[-2:], [2.0] * 7,
                             threshold=0.3)
    assert len(set(short)) == 3


def _sidecar(model="m"):
    lines = []
    for i, (speaker, vector) in enumerate([("SPEAKER_00", _unit(1, 0, 0)),
                                           ("SPEAKER_00", _unit(1, 0.1, 0)),
                                           ("SPEAKER_01", _unit(0, 1, 0)),
                                           ("SPEAKER_02", _unit(0.9, 0.2, 0)),
                                           ("SPEAKER_03", _unit(0, 0.1, 1))]):
        lines.append({"cue": f"c{i}", "start": i * 3.0, "end": i * 3.0 + 2.0,
                      "speaker": speaker, "vector": vector})
    lines.append({"cue": "short", "start": 20.0, "end": 20.4, "speaker": "SPEAKER_01",
                  "vector": _unit(1, 0, 0)})        # too short to teach anything
    return {"model": model, "lines": lines}


def test_a_named_voice_is_offered_for_the_unnamed_groups_that_sound_like_it():
    pytest.importorskip("numpy")
    db, path = FakeDb(), "M:/Shows/Harbor Lights (2007)/Season 01/e02.mkv"
    names = {"SPEAKER_00": "Kaito", "SPEAKER_01": "Mina"}
    assert voice_tags.remember(db, path, _sidecar(), names) == {"Kaito": 2, "Mina": 1}
    assert "voice-tags:harbor lights (2007)" in db.plans
    offered = voice_tags.suggest(db, path, _sidecar(), names)
    assert offered["SPEAKER_02"][0]["name"] == "Kaito"
    assert "SPEAKER_03" not in offered                     # nobody named sounds like it
    assert "SPEAKER_00" not in offered                     # already named


def test_the_next_episode_is_offered_the_names_taught_by_the_last_one():
    pytest.importorskip("numpy")
    db = FakeDb()
    voice_tags.remember(db, "M:/Show/Season 01/e01.mkv", _sidecar(), {"SPEAKER_00": "Kaito"})
    voice_tags.remember(db, "M:/Show/Season 01/e01.mkv", _sidecar(), {"SPEAKER_00": "Kaito"})
    known = voice_tags.prints(db, "M:/Show/Season 02/e30.mkv", "m")
    assert known["Kaito"]["lines"] == 2 and known["Kaito"]["episodes"] == 1   # not twice
    offered = voice_tags.suggest(db, "M:/Show/Season 02/e30.mkv", _sidecar(), {})
    assert offered["SPEAKER_00"][0]["name"] == "Kaito"
    # Another model's vectors cannot be compared with these.
    assert voice_tags.suggest(db, "M:/Show/Season 02/e30.mkv", _sidecar("other"), {}) == {}


def test_names_follow_their_lines_into_a_new_grouping():
    old = ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00", "SPEAKER_02"]
    new = ["SPEAKER_03", "SPEAKER_03", "SPEAKER_03", "SPEAKER_00"]
    carried = voice_tags.carry_names(old, new, [3.0, 1.0, 3.0, 2.0],
                                     {"SPEAKER_00": "Kaito", "SPEAKER_01": "Mina"})
    assert carried == {"SPEAKER_03": "Kaito"}        # the new SPEAKER_00 was never named


def test_an_analysed_episode_can_be_regrouped_and_keeps_its_names(client_factory, monkeypatch):
    np = pytest.importorskip("numpy")
    from tests.test_analysis import _episode

    client = client_factory()
    path = _episode(client.app.state.worker.config.work_dir, client)
    client.put("/api/analysis/names", json={"path": path, "names": {"SPEAKER_00": "Kaito"}})
    used = []

    def embed(audio, spans, device, models, models_dir):
        used.append([m.id for m in models])
        return [np.array(_unit(1, 0, 0)), np.array(_unit(0, 1, 0)), np.array(_unit(1, 0.05, 0))]

    monkeypatch.setattr(speakers, "embed", embed)
    result = client.post("/api/analysis/regroup", json={
        "path": path, "models": ["nemo-titanet-large"]}).json()
    assert used == [["nemo-titanet-large"]] and result["voices"] == 2
    data = client.get("/api/analysis", params={"path": path}).json()
    assert data["model"] == "nemo-titanet-large"
    assert data["lines"][0]["character"] == "Kaito"
    assert data["lines"][2]["speaker"] == data["lines"][0]["speaker"]
    bad = client.post("/api/analysis/regroup", json={"path": path, "models": ["nope"]})
    assert bad.status_code == 422
    listed = client.get("/api/voice-models").json()["models"]
    assert {m["id"] for m in listed} >= set(voice_models.RECOMMENDED)


def test_a_model_that_cannot_be_fetched_falls_back_to_the_default(tmp_path, monkeypatch):
    from doblarr.models import DubJob, Segment
    from doblarr.stages import diarize

    monkeypatch.delenv("HF_TOKEN", raising=False)
    job = DubJob(tmp_path / "e.mkv", "ja", "es")
    job.segments = [Segment(0, 0, 2, "a")]
    job.vocals = tmp_path / "e.vocals.wav"
    tried = []

    def assign(j, audio, sidecar=None, device="cpu", threshold=None, models=None,
               models_dir=None, tracks=None, track_evidence=None):
        tried.append([m.id for m in models])
        if len(models) > 1:
            raise OSError("offline")
        j.segments[0].speaker = "SPEAKER_00"
        j.speakers = {"SPEAKER_00": SimpleNamespace(label="SPEAKER_00")}
        return ["SPEAKER_00"]

    monkeypatch.setattr(diarize.speakers, "assign", assign)
    diarize.run(job, enabled=True, voices={
        "models": voice_models.resolve(voice_models.RECOMMENDED), "models_dir": tmp_path})
    assert tried == [voice_models.RECOMMENDED, [voice_models.DEFAULT]]
    assert set(job.speakers) == {"SPEAKER_00"}


def _two_language_video(folder):
    import subprocess

    video = folder / "e02.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=300",
                    "-f", "lavfi", "-i", "sine=frequency=500", "-t", "4",
                    "-map", "0:v", "-map", "1:a", "-map", "2:a",
                    "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=jpn",
                    "-c:v", "libx264", "-c:a", "aac", str(video)], check=True)
    return video


def test_a_watched_line_is_a_small_clip_in_the_language_asked_for(client_factory, tmp_path):
    from tests.test_analysis import _episode

    client = client_factory()
    work = client.app.state.worker.config.work_dir
    path = _episode(work, client)
    script = next((work / "media").glob("**/e02.script.json"))
    data = json.loads(script.read_text(encoding="utf-8"))
    data["identity"] = {"input": str(_two_language_video(tmp_path)), "source_lang": "ja"}
    script.write_text(json.dumps(data), encoding="utf-8")
    tracks = client.get("/api/analysis/tracks", params={"path": path}).json()
    assert [(t["stream"], t["lang"]) for t in tracks["tracks"]] == [(1, "en"), (2, "ja")]
    assert tracks["default"] == 2
    clip = client.get("/api/analysis/video", params={"path": path, "start": 1, "end": 2.5,
                                                      "audio": 1})
    assert clip.status_code == 200 and clip.content[4:8] == b"ftyp"
    again = client.get("/api/analysis/video", params={"path": path, "start": 1, "end": 2.5,
                                                       "audio": 1})
    assert again.content == clip.content                                  # cut once, kept
    assert client.get("/api/analysis/video", params={
        "path": path, "start": 1, "end": 2, "audio": 7}).status_code == 422
    assert client.get("/api/analysis/video", params={
        "path": path, "start": 0, "end": 45}).status_code == 422


def test_the_dub_tracks_are_read_once_and_the_original_is_left_to_the_dialogue(tmp_path):
    video = _two_language_video(tmp_path)
    found = speakers.other_tracks(video, "ja", tmp_path / "w", "e02")
    assert [stream for stream, _ in found] == [1]                          # English only
    assert found[0][1].is_file()
    assert speakers.other_tracks(video, "ja", tmp_path / "w", "e02", ["es"]) == []
    assert speakers.other_tracks(video, "ja", tmp_path / "w", "e02", []) == []


def test_a_line_filed_under_the_wrong_voice_can_be_given_to_someone_else(client_factory,
                                                                        monkeypatch):
    np = pytest.importorskip("numpy")
    from tests.test_analysis import _episode

    client = client_factory()
    path = _episode(client.app.state.worker.config.work_dir, client)
    client.put("/api/analysis/names", json={"path": path, "names": {
        "SPEAKER_00": "Doran", "SPEAKER_01": "Ren"}})
    # The grouping put a guard's line under Doran; nobody named the guard yet.
    moved = client.put("/api/analysis/line", json={"path": path, "cue": "c0",
                                                    "character": "Harbor guard"}).json()
    assert {k: moved[k] for k in ("speaker", "character", "new_voice")} == {
        "speaker": "SPEAKER_03", "character": "Harbor guard", "new_voice": True}
    data = client.get("/api/analysis", params={"path": path}).json()
    assert data["lines"][0]["character"] == "Harbor guard" and data["lines"][0]["moved"]
    assert data["names"]["SPEAKER_03"] == "Harbor guard"
    # To a character the episode already has: their group, no new voice.
    again = client.put("/api/analysis/line", json={"path": path, "cue": "c2",
                                                    "character": "ren"}).json()
    assert {k: again[k] for k in ("speaker", "character", "new_voice")} == {
        "speaker": "SPEAKER_01", "character": "Ren", "new_voice": False}
    assert client.put("/api/analysis/line", json={"path": path, "cue": "nope",
                                                  "character": "x"}).status_code == 404
    # Regrouping puts every line back in a group, then moved lines follow their person.
    monkeypatch.setattr(speakers, "embed", lambda *a, **k: [
        np.array(_unit(1, 0, 0)), np.array(_unit(1, 0.02, 0)), np.array(_unit(1, 0.05, 0))])
    client.post("/api/analysis/regroup", json={"path": path, "models": ["nemo-titanet-large"]})
    after = client.get("/api/analysis", params={"path": path}).json()
    assert after["lines"][0]["character"] == "Harbor guard"
    assert after["lines"][2]["character"] == "Ren"
