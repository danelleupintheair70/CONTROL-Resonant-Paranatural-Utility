"""Does a visible face move its mouth with the speech? (active-speaker evidence)

For each line and each face track on screen during it, the frames of the line
are read at a higher rate (`vision.asd_fps`), the lower part of the face box
(where the mouth is) is compared frame to frame, and that motion is correlated
with the line's own speech energy (doblarr.features frames). Two numbers come
back: the correlation, and how much the mouth region moves compared with the
rest of the face (a reaction shot of a still face moves little).

This is evidence that a face *may* be speaking. It is not a name, and a
speaking face is not proof of who speaks: dubbing, off-screen speech, a mouth
hidden by a mask or a cut mid-line all break it. In animation, mouth flaps are
not synchronised to the original audio at the syllable level; whether this
signal helps there is measured, not assumed (see the evaluation in the ledger).
"""

from __future__ import annotations

import math

METHOD = "mouth-motion-xcorr/1"
ROI_W, ROI_H = 48, 24
MIN_FRAMES = 6


def _box_at(track: dict, t: float, scale: float) -> tuple[int, int, int, int] | None:
    """The face box at time t (nearest sampled detection), in the asd frame's pixels."""
    boxes = track.get("boxes") or []
    if not boxes:
        return None
    nearest = min(boxes, key=lambda b: abs(b[0] - t))
    if abs(nearest[0] - t) > 1.2:
        return None
    _t, x, y, w, h = nearest
    return (int(x * scale), int(y * scale), int(w * scale), int(h * scale))


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < MIN_FRAMES or n != len(b):
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 1e-12 or vb <= 1e-12:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / math.sqrt(va * vb)


def energy_at(feature: dict, line_start: float, times: list[float]) -> list[float]:
    """The line's 20 ms energy frames (dB) resampled at `times` (absolute seconds)."""
    frames = feature.get("frames") or []
    out = []
    for t in times:
        i = int(round((t - line_start) / 0.02))
        out.append(float(frames[min(max(i, 0), len(frames) - 1)]) if frames else -80.0)
    return out


def score(frames: list, track: dict, feature: dict, line_start: float,
          scale: float) -> dict:
    """Mouth motion of one track over one line's frames, against its energy."""
    import cv2
    import numpy as np

    times, mouth, face = [], [], []
    previous_mouth = previous_face = None
    for t, frame in frames:
        box = _box_at(track, t, scale)
        if box is None:
            previous_mouth = previous_face = None
            continue
        x, y, w, h = box
        region = frame[max(0, y):y + h, max(0, x):x + w]
        if region.size == 0:
            continue
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        lower = gray[int(gray.shape[0] * 0.6):, :]
        upper = gray[:int(gray.shape[0] * 0.5), :]
        if lower.size == 0 or upper.size == 0:
            continue
        lower = cv2.resize(lower, (ROI_W, ROI_H)).astype(np.float32)
        upper = cv2.resize(upper, (ROI_W, ROI_H)).astype(np.float32)
        if previous_mouth is not None:
            times.append(t)
            mouth.append(float(np.mean(np.abs(lower - previous_mouth))))
            face.append(float(np.mean(np.abs(upper - previous_face))))
        previous_mouth, previous_face = lower, upper
    if len(times) < MIN_FRAMES:
        return {"method": METHOD, "state": "insufficient", "frames": len(times)}
    energy = energy_at(feature, line_start, times)
    corr = _pearson(mouth, energy)
    ratio = (sum(mouth) / len(mouth)) / max(1e-3, sum(face) / len(face))
    motion = sum(mouth) / len(mouth)
    # A combined score in [0, 1] for ranking only; the raw numbers are kept.
    combined = max(0.0, corr or 0.0) * 0.6 + min(1.0, max(0.0, ratio - 1.0)) * 0.4
    return {"method": METHOD, "state": "measured", "frames": len(times),
            "correlation": None if corr is None else round(corr, 3),
            "mouth_ratio": round(ratio, 3), "motion": round(motion, 3),
            "score": round(combined, 3)}
