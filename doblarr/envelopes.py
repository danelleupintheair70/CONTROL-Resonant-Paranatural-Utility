"""Fit a voice envelope to the take that will be heard, and render it.

A template (doblarr.templates) is a shape on a unit span. The line that gets
it is a *generated, time-fitted take* in another language: different words,
different syllables, its own pauses and its own emphasis. So the shape is
fitted to that take, never copied from the original waveform:

- **curve** anchors are laid over the take's own active span (first to last
  speech), so 0.0 is where its speech starts and 1.0 where it ends; silence
  before, after and inside follows the template's silence rule;
- **flatten** pulls the take's own measured envelope partly toward its mean;
- **peak_linked** places short bumps on the take's own strongest peaks (or the
  starts of its phrases, after its pauses), never on the original's syllables;
- **preserve** returns no curve at all.

If the take already carries the shape asked for (its own curve correlates with
the template), the strength is reduced by that much and the share is recorded
as `preserved`: emphasis the engine already performed is not doubled.

The curve is sampled every `HOP` seconds, smoothed, bounded to
±`max_db`, and its largest step between frames is reported so a render with an
abrupt jump is visible. Rendering multiplies each sample by
``10 ** ((static_db + curve_db(t)) / 20)``: one pass, together with the static
gain of the level owner, with peak protection taken from the static part so
the shape (the thing asked for) survives.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

HOP = 0.01                 # seconds per curve frame
FIT = "envelope-fit/1"
RENDER = "envelope-render/1"
DEFAULT_MAX_DB = 6.0
MAX_STEP_DB = 1.5          # per 10 ms; above this a step is reported as abrupt


def _interp(anchors: list[dict], x: float, mode: str) -> float:
    if x <= anchors[0]["at"]:
        return anchors[0]["db"]
    if x >= anchors[-1]["at"]:
        return anchors[-1]["db"]
    for a, b in zip(anchors, anchors[1:], strict=False):
        if a["at"] <= x <= b["at"]:
            span = b["at"] - a["at"] or 1e-9
            u = (x - a["at"]) / span
            if mode == "hold":
                return a["db"]
            if mode == "smooth":
                u = (1 - math.cos(math.pi * u)) / 2
            return a["db"] + (b["db"] - a["db"]) * u
    return anchors[-1]["db"]


def template_curve(template: dict, points: int = 33,
                   strength: float = 1.0) -> list[tuple[float, float]]:
    """A template's shape on a unit span (for previews; no take involved)."""
    if template["family"] != "curve":
        return [(i / (points - 1), 0.0) for i in range(points)]
    anchors = template["anchors"]
    mode = template.get("interpolation", "smooth")
    return [(i / (points - 1), strength * _interp(anchors, i / (points - 1), mode))
            for i in range(points)]


def _smooth(values: list[float], ms: float) -> list[float]:
    width = max(1, int(round(ms / 1000 / HOP)))
    if width <= 1 or len(values) < 3:
        return values
    half = width // 2
    out = []
    prefix = [0.0]
    for v in values:
        prefix.append(prefix[-1] + v)
    for i in range(len(values)):
        a, b = max(0, i - half), min(len(values), i + half + 1)
        out.append((prefix[b] - prefix[a]) / (b - a))
    return out


def _pearson(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 1e-9 or vb <= 1e-9:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / math.sqrt(va * vb)


def fit(template: dict, params: dict, take: dict, duration: float, *,
        global_strength: float = 1.0, max_db: float = DEFAULT_MAX_DB,
        credit_existing: bool = True) -> dict:
    """The fitted envelope for one take.

    `take` is the take's features (doblarr.features.measure on the fitted
    audio). Returns ``{curve, frames, hop, requested, applied, preserved,
    range_db, max_step_db, outcome, reason, fit}``; ``curve`` is dB per frame.
    """
    family = template["family"]
    frames = max(1, int(math.ceil(duration / HOP)))
    requested = float(params.get("strength", 1.0)) * float(global_strength)
    result = {"fit": FIT, "hop": HOP, "frames": frames, "requested": round(requested, 3),
              "applied": 0.0, "preserved": 0.0, "curve": [0.0] * frames,
              "outcome": "preserved", "reason": "", "range_db": 0.0, "max_step_db": 0.0}
    if family == "preserve":
        result["reason"] = "preserve: the take is rendered as generated"
        return result
    if take.get("quality") in ("missing",) or not take.get("intervals"):
        result.update(outcome="unavailable", reason="the take has no measurable speech")
        return result
    intervals = [(float(a), float(b)) for a, b in take["intervals"]]
    start, end = intervals[0][0], intervals[-1][1]
    span = max(1e-3, end - start)
    curve = [0.0] * frames
    preserved = 0.0
    if family == "curve":
        anchors = template["anchors"]
        mode = template.get("interpolation", "smooth")
        silence = template.get("silence", "hold")
        for i in range(frames):
            t = i * HOP
            x = (t - start) / span
            if x < 0 or x > 1:
                if silence == "follow":
                    curve[i] = 0.0
                    continue
                if silence == "release":
                    # The edge value fades to no change over 250 ms of silence.
                    edge = _interp(anchors, 0.0 if x < 0 else 1.0, mode)
                    distance = (start - t) if x < 0 else (t - end)
                    curve[i] = edge * max(0.0, 1.0 - distance / 0.25)
                    continue
            curve[i] = _interp(anchors, min(1.0, max(0.0, x)), mode)
        if credit_existing and take.get("curve"):
            shape = [_interp(anchors, k / 31, mode) for k in range(32)]
            corr = _pearson(shape, list(take["curve"]))
            template_range = max(shape) - min(shape)
            take_range = float(take.get("range_db") or 0.0)
            if corr > 0 and template_range > 0:
                preserved = round(min(1.0, corr * min(1.0, take_range / template_range)), 3)
    elif family == "flatten":
        amount = float(params.get("amount", 0.4))
        mean = float(take.get("mean_db") or 0.0)
        measured = take.get("frames") or []        # 20 ms frames of the take
        for i in range(frames):
            t = i * HOP
            if not any(a <= t < b for a, b in intervals):
                continue
            j = min(len(measured) - 1, int(t / 0.02)) if measured else -1
            if j >= 0:
                curve[i] = -amount * (float(measured[j]) - mean)
    elif family == "peak_linked":
        bump = float(params.get("bump_db", 2.0))
        width = float(params.get("width_ms", 180)) / 1000
        limit = int(params.get("max_peaks", 4))
        if int(params.get("anchor", 0)) == 1:
            centres = [a + width / 2 for a, _b in intervals][:limit]
        else:
            centres = [float(p["t"]) for p in (take.get("peaks") or [])][:limit]
        for c in centres:
            for i in range(max(0, int((c - width) / HOP)), min(frames, int((c + width) / HOP) + 1)):
                u = (i * HOP - c) / width
                if abs(u) <= 1:
                    curve[i] = max(curve[i], bump * (1 + math.cos(math.pi * u)) / 2)
    else:
        result.update(outcome="unsupported",
                      reason=f"the {family} family is not a voice envelope")
        return result
    applied = requested * (1.0 - preserved)
    curve = [c * applied for c in curve]
    curve = _smooth(curve, float(template.get("smoothing_ms", 40)))
    clamps = 0
    bounded = []
    for c in curve:
        b = max(-max_db, min(max_db, c))
        clamps += b != c
        bounded.append(round(b, 3))
    steps = [abs(b - a) for a, b in zip(bounded, bounded[1:], strict=False)]
    result.update(curve=bounded, applied=round(applied, 3), preserved=preserved,
                  outcome="applied" if any(abs(c) > 0.05 for c in bounded) else "preserved",
                  range_db=round(max(bounded) - min(bounded), 3) if bounded else 0.0,
                  max_step_db=round(max(steps), 3) if steps else 0.0,
                  clamped_frames=clamps,
                  reason=(f"{preserved:.0%} of the shape was already in the take"
                          if preserved > 0.05 else ""))
    if result["outcome"] == "preserved" and not result["reason"]:
        result["reason"] = "the fitted curve rounds to no change"
    return result


# --------------------------------------------------------------------------
# Rendering (16-bit PCM WAV in, same layout and rate out)
# --------------------------------------------------------------------------

def read_wav(path: Path):
    import numpy as np

    with wave.open(str(path), "rb") as audio:
        if audio.getsampwidth() != 2:
            raise wave.Error("envelope rendering requires 16-bit PCM")
        channels, rate = audio.getnchannels(), audio.getframerate()
        raw = audio.readframes(audio.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    return samples.reshape(-1, max(1, channels)), rate


def write_wav(path: Path, samples, rate: int) -> None:
    import numpy as np

    channels = samples.shape[1] if samples.ndim == 2 else 1
    data = np.clip(np.round(samples * 32767.0), -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".partial.wav")
    with wave.open(str(temp), "wb") as out:
        out.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        out.writeframes(data.tobytes())
    temp.replace(path)


def gain_per_sample(curve: list[float], hop: float, count: int, rate: int, static_db: float):
    """Linear gain for every sample: static gain plus the curve, interpolated."""
    import numpy as np

    if not curve:
        return np.full(count, 10 ** (static_db / 20))
    times = np.arange(count) / rate
    frame_times = np.arange(len(curve)) * hop
    db = np.interp(times, frame_times, np.asarray(curve, dtype=np.float64))
    return 10 ** ((static_db + db) / 20)


def render(source: Path, dest: Path, static_db: float, curve: list[float], *,
           hop: float = HOP, peak_ceiling: float = 0.89) -> dict:
    """Apply static gain + envelope in one pass. If the result would cross the
    ceiling, the reduction comes out of the static part and the shape stays."""
    import numpy as np

    samples, rate = read_wav(source)
    gain = gain_per_sample(curve, hop, samples.shape[0], rate, static_db)
    peak = float(np.max(np.abs(samples * gain[:, None]))) if samples.size else 0.0
    held = 0.0
    if peak > peak_ceiling > 0:
        held = 20 * math.log10(peak / peak_ceiling)
        gain = gain * 10 ** (-held / 20)
        peak = peak_ceiling
    out = samples * gain[:, None]
    write_wav(dest, out, rate)
    return {"render": RENDER, "peak": round(peak, 4), "held_db": round(held, 3),
            "static_db": round(static_db - held, 3), "samples": int(samples.shape[0]),
            "rate": rate, "channels": int(samples.shape[1])}
