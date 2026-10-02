"""Subtitle cues moved to where their speech starts, and only there."""

import math
import struct
import wave

import pytest

from doblarr import onsets
from doblarr.cues import SOURCE, Span, ensure_identity
from doblarr.models import DubJob, Segment

RATE = 16000


def _stem(path, bursts, seconds=12.0):
    frames = bytearray()
    for index in range(int(RATE * seconds)):
        t = index / RATE
        loud = any(a <= t < b for a, b in bursts)
        value = 0.3 * 32000 * math.sin(2 * math.pi * 220 * t) if loud else 0.0
        frames += struct.pack("<h", int(value))
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        out.writeframes(bytes(frames))
    return path


def _job(tmp_path, cues, bursts):
    pytest.importorskip("numpy")
    media = tmp_path / "episode.mkv"
    media.write_text("video", encoding="utf-8")
    job = DubJob(input_file=media, source_lang="ja", target_lang="es")
    job.segments = [Segment(i, a, b, "line") for i, (a, b) in enumerate(cues)]
    for seg in job.segments:
        seg.source.spans = [Span(seg.start, seg.end, SOURCE)]
        seg.source.method = "subtitle"
    ensure_identity(job)
    job.source_audio = tmp_path / "source.wav"
    job.vocals = _stem(tmp_path / "vocals.wav", bursts)
    return job


def test_a_late_cue_moves_back_to_its_speech(tmp_path):
    job = _job(tmp_path, [(2.3, 4.0)], [(2.0, 3.8)])
    onsets.snap(job)
    assert job.segments[0].start == pytest.approx(2.0, abs=0.02)
    assert job.segments[0].source.spans[0].start == 2.3     # the subtitle is kept


def test_snapping_twice_does_not_move_a_cue_again(tmp_path):
    job = _job(tmp_path, [(2.3, 4.0)], [(2.0, 3.8)])
    onsets.snap(job)
    onsets.snap(job)
    assert job.segments[0].start == pytest.approx(2.0, abs=0.02)


def test_voice_that_runs_across_the_cue_is_not_an_onset(tmp_path):
    # Somebody is still talking when the cue starts: nothing to snap to.
    job = _job(tmp_path, [(2.3, 4.0)], [(1.0, 3.8)])
    onsets.snap(job)
    assert job.segments[0].start == pytest.approx(2.3)


def test_speech_too_far_from_the_cue_is_not_its_speech(tmp_path):
    job = _job(tmp_path, [(3.0, 5.0)], [(1.5, 2.2)])
    onsets.snap(job)
    assert job.segments[0].start == pytest.approx(3.0)
