"""Visual evidence: shots, tracks, corrections, references, scenes, mouth motion, fusion."""

import shutil
import subprocess

import numpy as np
import pytest

from doblarr.store import Database
from doblarr.vision import active, association, capability, media, references, scenes, tracks

ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "v.db")
    yield database
    database.close()


def det(t, box, vector=None, detector="lbpcascade-animeface", embedder="dinov2-small"):
    return {"t": t, "box": list(box), "score": None, "detector": detector, "domain": "anime",
            "vector": vector, "embedder": embedder if vector else "", "crop": f"{t}.jpg"}


SHOTS = [{"id": "shot-0000", "start": 0.0, "end": 5.0},
         {"id": "shot-0001", "start": 5.0, "end": 10.0}]


def test_tracks_link_overlapping_faces_and_end_at_a_cut():
    found = tracks.build([det(1.0, (10, 10, 40, 40)), det(1.5, (12, 11, 40, 40)),
                          det(2.0, (14, 12, 40, 40)), det(1.0, (200, 10, 40, 40)),
                          det(5.5, (14, 12, 40, 40))], SHOTS, "rev-1")
    assert len(found) == 3
    longest = max(found, key=lambda t: t["frames"])
    assert longest["frames"] == 3 and longest["shot"] == "shot-0000"
    assert any(t["shot"] == "shot-0001" for t in found)  # same place, after the cut: new track


def test_detectors_are_never_mixed_in_one_track():
    found = tracks.build([det(1.0, (10, 10, 40, 40)),
                          det(1.5, (10, 10, 40, 40), detector="yunet-2023mar")], SHOTS, "r")
    assert len(found) == 2


def test_corrections_survive_reanalysis_and_find_a_renamed_track(db):
    built = tracks.build([det(1.0, (10, 10, 40, 40)), det(1.5, (10, 10, 40, 40)),
                          det(2.0, (10, 10, 40, 40)), det(3.0, (10, 10, 40, 40))], SHOTS, "rev")
    track = built[0]
    tracks.correct(db, "rev", base_revision=0, assign={track["id"]: "chr-mina"},
                   tracks=built)
    tracks.correct(db, "rev", base_revision=1, split={track["id"]: 2.5}, tracks=built)
    applied = tracks.apply(db, "rev", built)
    assert len(applied) == 2 and all(t["character"] == "chr-mina" for t in applied[:1])
    # A model update renamed the track: its anchor finds it again.
    renamed = [{**built[0], "id": "trk-new"}]
    again = tracks.apply(db, "rev", renamed)
    assert again[0]["character"] == "chr-mina" and again[0]["assigned"] == "manual"
    # "Unknown" is a decision too: the track stays unnamed.
    tracks.correct(db, "rev", base_revision=2, assign={track["id"]: None}, tracks=built)
    assert tracks.apply(db, "rev", built)[0]["character"] is None


def test_references_match_only_approved_faces_of_the_same_embedder(db):
    vector = list(np.ones(4) / 2)
    track = {"id": "trk-a", "vector": vector, "embedder": "dinov2-small", "start": 0, "end": 1,
             "domain": "anime"}
    references.add_from_track(db, "show:tvdb:1", track, "chr-kaito", revision_id="rev-1")
    refs = references.load(db, "show:tvdb:1")["references"]
    probe = {"id": "trk-b", "vector": vector, "embedder": "dinov2-small"}
    found = references.match(probe, refs, threshold=0.5)
    assert found[0]["character_id"] == "chr-kaito" and found[0]["proposed"]
    other = {"id": "trk-c", "vector": vector, "embedder": "sface-2021dec"}
    assert references.match(other, refs, 0.5) == []
    unapproved = [{**r, "approved": False} for r in refs]
    assert references.match(probe, unapproved, 0.5) == []
    # A track never matches a reference made from itself.
    assert references.match(track, refs, 0.5) == []


def _track(track_id, start, end, character=None, manual=False):
    row = {"id": track_id, "start": start, "end": end, "boxes": [[start, 0, 0, 40, 40]],
           "frames": 3}
    if manual:
        row.update(character=character, assigned="manual")
    elif character:
        row["matches"] = [{"character_id": character, "proposed": True}]
    return row


LINE = {"cue": "c1", "start": 1.0, "end": 3.0}


def test_a_hand_assigned_line_is_never_overridden():
    out = association.fuse(LINE, audio_character="chr-kaito", why={"method": "clustered",
                                                                    "margin": 0.3},
                           locked="chr-mina", tracks=[], speaking={})
    assert out["decision"] == {"state": "manual", "character_id": "chr-mina",
                               "reason": out["decision"]["reason"]}


def test_clear_voice_evidence_decides_and_a_disagreeing_face_is_recorded():
    tracks_ = [_track("t1", 0.5, 3.5, "chr-ren", manual=True)]
    out = association.fuse(LINE, audio_character="chr-kaito",
                           why={"method": "clustered", "margin": 0.2}, locked=None,
                           tracks=tracks_, speaking={"t1": {"state": "measured", "score": 0.8,
                                                            "correlation": 0.5}})
    assert out["decision"]["state"] == "audio" and out["decision"]["character_id"] == "chr-kaito"
    assert out["conflicts"] and out["screen"] == "onscreen-speaking"


def test_weak_voice_evidence_only_yields_a_proposal_from_a_speaking_face():
    tracks_ = [_track("t1", 0.5, 3.5, "chr-ren", manual=True)]
    out = association.fuse(LINE, audio_character="chr-kaito",
                           why={"method": "inherited", "margin": None}, locked=None,
                           tracks=tracks_, speaking={"t1": {"state": "measured", "score": 0.8,
                                                            "correlation": 0.4}})
    assert out["decision"]["state"] == "proposal" and out["decision"]["character_id"] == "chr-ren"


def test_a_silent_face_in_a_reaction_shot_never_takes_the_line():
    tracks_ = [_track("t1", 0.5, 3.5, "chr-ren", manual=True)]
    out = association.fuse(LINE, audio_character=None, why=None, locked=None, tracks=tracks_,
                           speaking={"t1": {"state": "measured", "score": 0.05,
                                            "correlation": -0.1}})
    assert out["decision"]["state"] == "unknown" and out["screen"] == "onscreen-silent"


def test_offscreen_and_unknown_are_different_answers():
    off = association.fuse(LINE, audio_character=None, why=None, locked=None, tracks=[],
                           speaking={})
    unknown = association.fuse(LINE, audio_character=None, why=None, locked=None, tracks=[],
                               speaking={}, visual_state="unsupported")
    assert off["screen"] == "offscreen" and unknown["screen"] == "unknown"


def test_calibration_needs_enough_evidence_to_set_a_threshold():
    rows = [{"cue": f"c{i}", "character_id": "a", "score": 0.5 + i / 100} for i in range(6)]
    truth = {f"c{i}": "a" for i in range(6)}
    assert association.calibrate(rows, truth)["threshold"] == 0.2
    assert association.calibrate(rows[:3], truth)["calibrated"] is False


def test_a_conversation_across_cuts_is_one_scene_and_a_long_gap_is_two():
    shot_rows = [{"id": f"shot-{i}", "start": float(i * 4), "end": float(i * 4 + 4)}
                 for i in range(6)]
    lines = [{"cue": "a", "start": 0.5, "end": 4.5}, {"cue": "b", "start": 5.0, "end": 7.5},
             {"cue": "c", "start": 8.2, "end": 9.0}, {"cue": "d", "start": 20.5, "end": 22.0}]
    found = scenes.group(shot_rows, lines, 24.0)
    assert [s["lines"] for s in found] == [["a", "b", "c"], ["d"]]
    manual = scenes.group(shot_rows, lines, 24.0, {"add": [8.0], "remove": []})
    assert [s["lines"] for s in manual] == [["a", "b"], ["c"], ["d"]]
    removed = scenes.group(shot_rows, lines, 24.0, {"add": [], "remove": [found[1]["start"]]})
    assert len(removed) == 1


def test_a_mouth_moving_with_the_speech_scores_higher_than_a_still_face():
    pytest.importorskip("cv2")
    times = [i / 8 for i in range(24)]
    energy_frames = [(-20.0 if (i // 25) % 2 == 0 else -50.0) for i in range(160)]
    feature = {"frames": energy_frames}
    track = {"boxes": [[0.0, 10, 10, 60, 60]]}

    def frames(moving):
        # Articulation: while there is speech the mouth opens and shuts from
        # frame to frame; in the pauses it stays closed.
        out = []
        for n, t in enumerate(times):
            frame = np.full((100, 100, 3), 120, dtype=np.uint8)
            if moving and active.energy_at(feature, 0.0, [t])[0] > -30 and n % 2:
                frame[50:70, 20:60] = 250        # an open mouth
            out.append((t, frame))
        return out

    talking = active.score(frames(True), track, feature, 0.0, 1.0)
    still = active.score(frames(False), track, feature, 0.0, 1.0)
    assert talking["state"] == "measured" and talking["correlation"] > 0.5
    assert still["correlation"] is None and talking["score"] > still["score"]


def test_missing_model_files_make_the_visual_stages_unsupported(tmp_path):
    from types import SimpleNamespace

    config = SimpleNamespace(get=lambda k, d=None: {"models_dir": str(tmp_path / "none")}
                             if k == "vision" else d, work_dir=tmp_path)
    found = capability.unsupported_stages(config)
    status = capability.status(config)
    if status["live_action"]["detector"] or status["anime"]["detector"]:
        pytest.skip("model files exist in this environment")
    assert set(found) >= {"faces", "tracks", "active_speaker", "association"}
    assert any("not downloaded" in r or "OpenCV" in r for r in status["reasons"])


@ffmpeg
def test_a_hard_cut_is_found_and_frames_stream_at_the_asked_rate(tmp_path):
    video = tmp_path / "cut.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=160x120:d=2,format=yuv420p", "-f", "lavfi", "-i",
                    "color=c=blue:s=160x120:d=2,format=yuv420p", "-filter_complex",
                    "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-r", "25", str(video)],
                   check=True)
    found = media.shots(video)
    assert found["cuts"] == 1
    assert abs(found["shots"][1]["start"] - 2.0) < 0.2
    streamed = list(media.frames(video, fps=2, height=120))
    assert 7 <= len(streamed) <= 9 and streamed[0][1].shape == (120, 160, 3)
