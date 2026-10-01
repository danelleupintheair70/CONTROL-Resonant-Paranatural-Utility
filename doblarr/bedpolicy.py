"""One background policy for the whole timeline, instead of per-line ducking.

The legacy mix ducks the bed with a sidechain compressor keyed by the dialogue
bus (doblarr.stages.mix). A background template (doblarr.templates, family
``bed``) replaces that with one planned gain curve for the bed:

- speech activity is the union of the placed lines' *speech* intervals (from
  the rendered takes, not their padding), so overlaps and reactions count once;
- short hesitations (gaps under ``gap_recover_s``) do not let the music rise;
- the curve moves toward its target with ``attack_ms``/``release_ms``
  (one-pole in dB) and holds ``hold_ms`` after speech, so it cannot pump;
- ``transient_db``: where the bed's own level jumps above its running median
  (an impact, a sting), the duck is lifted for that moment instead of burying it;
- ``swell_db``/``swell_s``: after a scene's last line the bed may rise a little;
- ``transition_ms``: at a scene change the release is stretched instead of
  jumping;
- the total (trim + duck + swell) is bounded by `max_attenuation_db`.

Exactly one ducking system runs: with a policy active, the mix is flat and the
sidechain compressor is bypassed; the run's metrics record that. The bed is
rendered once from the original bed file (never from a processed one), in
bounded chunks.
"""

from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

HOP = 0.01
POLICY = "bed-policy/1"
CHUNK = 10.0            # seconds rendered at a time
RATE = 48000


def _union(intervals: list[tuple[float, float]], merge_gap: float) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(intervals):
        if out and a - out[-1][1] <= merge_gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def bed_levels(bed: Path, duration: float, cancel=None) -> list[float]:
    """The bed's own short-term level (dB) every HOP, decoded in chunks."""
    from . import features

    reader = features.ChunkedAudio(Path(bed), cancel)
    levels: list[float] = []
    hop = int(HOP * features.RATE)
    t = 0.0
    import numpy as np

    while t < duration:
        samples = reader.span(t, min(duration, t + features.CHUNK))
        if not len(samples):
            break
        usable = len(samples) // hop * hop
        if usable:
            frames = np.asarray(samples[:usable], dtype=np.float64).reshape(-1, hop)
            power = (frames ** 2).mean(axis=1)
            levels.extend(10 * math.log10(p) if p > 1e-10 else -100.0 for p in power)
        t += features.CHUNK
    return levels


def plan(params: dict, activity: list[tuple[float, float]], duration: float, *,
         scene_starts: list[float] | None = None, bed_level: list[float] | None = None,
         max_attenuation_db: float = 18.0) -> dict:
    """The bed's gain curve (dB per HOP) for the whole programme."""
    frames = max(1, int(math.ceil(duration / HOP)))
    trim = float(params.get("trim_db", 0.0))
    duck = float(params.get("duck_db", 0.0))
    attack = max(HOP, float(params.get("attack_ms", 100)) / 1000)
    release = max(HOP, float(params.get("release_ms", 400)) / 1000)
    hold = float(params.get("hold_ms", 0)) / 1000
    gap = float(params.get("gap_recover_s", 0.0))
    swell = float(params.get("swell_db", 0.0))
    swell_s = float(params.get("swell_s", 1.5))
    transient = params.get("transient_db")
    transition = float(params.get("transition_ms", 0)) / 1000
    speech = _union([(a, b + hold) for a, b in activity], gap)
    target = [trim] * frames
    for a, b in speech:
        for i in range(max(0, int(a / HOP)), min(frames, int(math.ceil(b / HOP)))):
            target[i] = trim + duck
    if swell > 0 and speech:
        boundaries = sorted(scene_starts or [])
        for _a, b in speech:
            following = next((s for s in boundaries if s > b), None)
            next_speech = next((x for x, _y in speech if x > b), None)
            ends_scene = following is not None and (next_speech is None
                                                    or next_speech > following)
            if not ends_scene and next_speech is not None and next_speech - b < 4.0:
                continue
            for i in range(int(b / HOP), min(frames, int((b + swell_s) / HOP))):
                if target[i] == trim:
                    u = (i * HOP - b) / swell_s
                    target[i] = trim + swell * math.sin(math.pi * u)
    protected = 0
    if transient is not None and bed_level:
        window = int(3.0 / HOP)
        ordered: list[float] = []
        for i in range(min(frames, len(bed_level))):
            if i % 50 == 0:
                lo, hi = max(0, i - window), min(len(bed_level), i + window)
                ordered = sorted(bed_level[lo:hi])
            median = ordered[len(ordered) // 2] if ordered else -100.0
            if bed_level[i] > median + float(transient) and target[i] < trim:
                for j in range(max(0, i - 10), min(frames, i + 10)):
                    if target[j] < trim:
                        target[j] = trim
                        protected += 1
    curve = []
    value = trim
    starts = set(int(s / HOP) for s in scene_starts or [])
    slow = 0
    for i, goal in enumerate(target):
        if i in starts and transition > 0:
            slow = int(transition / HOP)
        rate_s = attack if goal < value else (max(release, transition) if slow > 0
                                              else release)
        slow = max(0, slow - 1)
        value += (goal - value) * (1 - math.exp(-HOP / rate_s))
        curve.append(round(max(-max_attenuation_db, min(6.0, value)), 3))
    steps = [abs(b - a) for a, b in zip(curve, curve[1:], strict=False)]
    ducked = sum(1 for c in curve if c < trim - 1.0)
    return {"policy": POLICY, "hop": HOP, "curve": curve,
            "stats": {"min_db": min(curve), "max_db": max(curve),
                      "ducked_share": round(ducked / len(curve), 3),
                      "max_step_db": round(max(steps), 3) if steps else 0.0,
                      "speech_spans": len(speech), "transient_frames": protected}}


def render(bed: Path, dest: Path, curve: list[float], hop: float = HOP,
           cancel=None) -> dict:
    """The bed with the planned gain, rendered once, chunk by chunk."""
    import numpy as np

    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(".partial.wav")
    process = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-i", str(bed),
                                "-ac", "2", "-ar", str(RATE), "-f", "s16le", "-"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame_times = np.arange(len(curve)) * hop
    gains = np.asarray(curve, dtype=np.float64)
    written = 0
    peak = 0.0
    with wave.open(str(temp), "wb") as out:
        out.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
        assert process.stdout is not None
        while True:
            if cancel is not None and cancel.is_set():
                process.kill()
                temp.unlink(missing_ok=True)
                from .errors import JobCancelled

                raise JobCancelled("cancelled while rendering the bed")
            raw = process.stdout.read(int(CHUNK * RATE) * 4)
            if not raw:
                break
            block = np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, 2) / 32768.0
            times = (written + np.arange(block.shape[0])) / RATE
            gain = 10 ** (np.interp(times, frame_times, gains) / 20)
            shaped = block * gain[:, None]
            peak = max(peak, float(np.max(np.abs(shaped))) if shaped.size else 0.0)
            out.writeframes(np.clip(np.round(shaped * 32767), -32768, 32767)
                            .astype("<i2").tobytes())
            written += block.shape[0]
    process.wait()
    temp.replace(dest)
    return {"samples": written, "seconds": round(written / RATE, 3), "peak": round(peak, 4)}
