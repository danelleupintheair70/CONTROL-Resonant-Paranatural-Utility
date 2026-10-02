"""Start each subtitle cue where its speech actually starts.

Fansub timing is written for reading, not for lip sync: a cue commonly appears
a few hundred milliseconds after the actor has started talking. A dub placed at
the cue start then arrives late, and the character's mouth is already moving
before the dubbed line begins. The separated dialogue stem says where the voice
really begins, so each cue's start is moved to the speech onset nearest it.

Rules the code keeps:

- **Only a real onset counts.** A sharp rise out of the moment before it;
  voice that runs steadily across the window is somebody still talking, and a
  cue is never pulled into the middle of the previous line.
- **Bounded.** An onset further than `early`/`late` seconds from the cue is
  not this cue's speech, and the cue stays where it was.
- **Idempotent.** The subtitle's own start is kept in the cue's source span,
  and every run recomputes from it, so a resume never shifts a line twice.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path

log = logging.getLogger("doblarr.onsets")

DETECTOR = "speech-onset/1"
FRAME = 0.01
FLOOR_DB = 30.0          # below the loud end of the stem: silence
QUIET_BEFORE = 0.15      # the stretch an onset must rise out of
RISE_DB = 12.0           # how far above that stretch a voice starting jumps
RISE_FLOOR_DB = 10.0     # and how far above the silence floor it must be
REFRACTORY = 0.1         # one onset per syllable burst, not one per frame
EARLY, LATE = 0.6, 0.4   # how far a cue may move toward its speech


def _levels(path: Path):
    import numpy as np

    with wave.open(str(path), "rb") as audio:
        rate, channels = audio.getframerate(), audio.getnchannels()
        if audio.getsampwidth() != 2:
            return None, None
        raw = np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16)
    samples = raw.astype(np.float32).reshape(-1, channels).mean(axis=1)
    step = max(1, int(rate * FRAME))
    frames = len(samples) // step
    if frames == 0:
        return None, None
    power = (samples[:frames * step].reshape(frames, step) ** 2).mean(axis=1)
    level = 10 * np.log10(np.maximum(power, 1.0) / (32768.0 * 32768.0))
    return level, max(float(np.percentile(level, 99)) - FLOOR_DB, -60.0)


def onsets(level, floor) -> list[float]:
    """Times where voice rises sharply out of what came before it.

    A separated dialogue stem is rarely silent: music and effects bleed through
    it, so "voice after silence" almost never happens in a scene with a score.
    A voice starting is a jump instead: a frame RISE_DB above the average of
    the QUIET_BEFORE window before it, and loud enough to be speech at all.
    """
    import numpy as np

    before = int(round(QUIET_BEFORE / FRAME))
    if len(level) <= before:
        return []
    power = 10 ** (level / 10)
    running = np.convolve(power, np.ones(before) / before, mode="full")[:len(level)]
    prior = 10 * np.log10(np.maximum(np.concatenate(([power[0]], running[:-1])), 1e-12))
    rising = (level > floor + RISE_FLOOR_DB) & (level - prior >= RISE_DB)
    rising[:before] = False
    found: list[float] = []
    for index in np.flatnonzero(rising):
        at = round(float(index) * FRAME, 3)
        if not found or at - found[-1] > REFRACTORY:
            found.append(at)
    return found


def snap(job, early: float = EARLY, late: float = LATE) -> dict:
    """Move subtitle cue starts to the nearest speech onset. Returns a summary."""
    stem = job.vocals
    if stem is None or not Path(stem).is_file() or stem == job.source_audio:
        return {"moved": 0, "note": "no separated dialogue stem"}
    try:
        level, floor = _levels(Path(stem))
    except ImportError:
        return {"moved": 0, "note": "numpy is unavailable"}
    if level is None:
        return {"moved": 0, "note": "unreadable dialogue stem"}
    starts = onsets(level, floor)
    moved, shifts = 0, []
    previous_start = None
    for seg in sorted(job.segments, key=lambda s: s.start):
        spans = seg.source.spans
        if not spans or seg.source.method != "subtitle":
            previous_start = seg.start
            continue
        original = spans[0].start
        near = [t for t in starts if original - early <= t <= original + late
                and t < seg.end - 0.2
                and (previous_start is None or t > previous_start + 0.3)]
        target = min(near, key=lambda t: abs(t - original)) if near else original
        if abs(target - seg.start) > 1e-6:
            seg.start = target
        if abs(target - original) > 1e-6:
            moved += 1
            shifts.append(round(target - original, 3))
        previous_start = seg.start
    shifts.sort()
    summary = {"moved": moved, "detector": DETECTOR,
               "median_shift": shifts[len(shifts) // 2] if shifts else 0.0}
    job.metrics["onsets"] = summary
    log.info("onsets: %d cue(s) moved to their speech onset (median %+.2f s)",
             moved, summary["median_shift"])
    return summary
