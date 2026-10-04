"""quality.voice_check — flag a take that drifted from its voice, keep the best attempt."""

from pathlib import Path

from doblarr import voice_check
from doblarr.cues import RAW, Artifact, Selection, Take
from doblarr.models import DubJob, Segment, Speaker
from doblarr.stages import quality
from tests.test_audio_quality import wav


def _job(tmp_path: Path) -> DubJob:
    job = DubJob(tmp_path / "movie.mkv", "ja", "es")
    job.speakers = {"SPEAKER_00": Speaker("SPEAKER_00", reference_clip=tmp_path / "ref.wav")}
    first = wav(tmp_path / "take0.wav", 5000)
    seg = Segment(0, 0, 1, "Mina, ven", speaker="SPEAKER_00", audio_clip=first)
    seg.audio.takes.append(Take(take_id="t0", raw=Artifact(role=RAW, path=str(first))))
    seg.audio.selection = Selection(take_id="t0")
    job.segments = [seg]
    return job


def _similarity(monkeypatch, by_file: dict[str, float]):
    monkeypatch.setattr(voice_check.VoiceCheck, "similarity",
                        lambda self, speaker, take: by_file[Path(take).name])


def _regenerate(tmp_path):
    def regenerate(seg):
        n = len(seg.audio.takes)
        path = wav(tmp_path / f"take{n}.wav", 5000)
        seg.audio.takes.append(Take(take_id=f"t{n}", raw=Artifact(role=RAW, path=str(path))))
        seg.audio.selection = Selection(take_id=f"t{n}")
        seg.audio_clip = path
    return regenerate


def test_off_by_default_measures_nothing(tmp_path, monkeypatch):
    job = _job(tmp_path)
    monkeypatch.setattr(voice_check.VoiceCheck, "similarity",
                        lambda *a: (_ for _ in ()).throw(AssertionError("measured")))
    quality.run(job, normalize=False)
    assert "voice_drift" not in job.segments[0].issues


def test_drifted_take_is_retried_and_the_closer_one_kept(tmp_path, monkeypatch):
    job = _job(tmp_path)
    _similarity(monkeypatch, {"take0.wav": 0.1, "take1.wav": 0.55})
    quality.run(job, normalize=False, regenerate=_regenerate(tmp_path), voice_check=True)
    seg = job.segments[0]
    assert seg.audio.selection.take_id == "t1"
    assert "voice_drift" not in seg.issues
    assert seg.audio.take("t1").checks["voice_similarity"] == 0.55


def test_a_worse_retry_does_not_replace_the_better_take(tmp_path, monkeypatch):
    job = _job(tmp_path)
    # Both drift; the first is closer to the voice, so it stays.
    _similarity(monkeypatch, {"take0.wav": 0.2, "take1.wav": 0.05})
    quality.run(job, normalize=False, regenerate=_regenerate(tmp_path), voice_check=True)
    seg = job.segments[0]
    assert seg.audio.selection.take_id == "t0"
    assert seg.audio.selection.reason == "best of attempts"
    assert Path(seg.audio_clip).name == "take0.wav"
    assert "voice_drift" in seg.issues
    assert job.metrics["quality_best_kept"] == 1


def test_unknown_similarity_is_not_a_drift(tmp_path, monkeypatch):
    job = _job(tmp_path)
    monkeypatch.setattr(voice_check.VoiceCheck, "similarity", lambda *a: None)
    quality.run(job, normalize=False, voice_check=True)
    assert "voice_drift" not in job.segments[0].issues


def test_missing_reference_measures_as_unknown(tmp_path):
    check = voice_check.VoiceCheck({"SPEAKER_00": tmp_path / "missing.wav"})
    assert check.similarity("SPEAKER_00", tmp_path / "take.wav") is None
    assert not check.drifted(None) and check.drifted(0.1) and not check.drifted(0.4)
