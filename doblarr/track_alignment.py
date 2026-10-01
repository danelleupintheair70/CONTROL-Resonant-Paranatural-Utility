"""Is another audio track of this video the same cut, on the same clock?

A dub can help tell voices apart (doblarr.speakers), but only if its lines sit
where the original's do. A stream's language tag cannot say that: an edition
with a scene removed, a commentary track, audio description or a dub timed to
another release all carry an ordinary language tag.

So before a track is used as evidence it is aligned against the original:

- Both are reduced to an energy envelope (50 ms frames, in dB). A dub track is
  usually a full mix that shares the original's music and effects, so its
  envelope follows the original *mix* closely when the cut is the same; the
  original mix is the reference when it is available, the separated dialogue
  otherwise.
- The whole-track offset is the lag with the highest normalised correlation.
- The track is then cut into windows and each window is aligned on its own.
  A consistent offset across windows (small spread, linear drift) is a
  **verified** alignment, recorded as ``source = track * rate + offset``. Windows
  that disagree mean a different edit: the track is **rejected**. Too little
  correlation is **uncertain**, which is never used silently.

Titles that announce commentary or audio description are excluded before any
of this, and a track a studio reference marks as evaluation-only is excluded
whatever its alignment.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

METHOD = "envelope-xcorr/1"
FRAME = 0.05            # seconds per envelope frame
WINDOWS = 6             # independent windows checked for a consistent offset
# Seconds of disagreement between windows still called one cut. Envelope
# alignment of two different dialogue mixes jitters by a frame or two (a dub
# measured on a real episode: -0.10..+0.15 s with no trend), and speaker
# embeddings read 0.8 s and longer windows, so that is harmless; a removed or
# moved scene shows up instead as windows that stop correlating at all.
MAX_SPREAD = 0.3
MIN_WINDOW_CORR = 0.3
EXCLUDED_TITLES = re.compile(
    r"comment|commentary|comentario|kommentar|description|descriptive|audio ?desc|"
    r"\bad\b|narrat|isolated score|music only|karaoke", re.IGNORECASE)


def envelope(path: Path, cancel=None) -> list[float]:
    """Frame energies in dB of a whole file, decoded in bounded chunks."""
    from . import features

    reader = features.ChunkedAudio(Path(path), cancel)
    out: list[float] = []
    t = 0.0
    hop = int(FRAME * features.RATE)
    import numpy as np

    while True:
        samples = reader.span(t, t + features.CHUNK)
        if not len(samples):
            break
        usable = len(samples) // hop * hop
        if usable:
            frames = np.asarray(samples[:usable], dtype=np.float64).reshape(-1, hop)
            power = (frames ** 2).mean(axis=1)
            out.extend(float(10 * math.log10(p)) if p > 1e-10 else -100.0 for p in power)
        if len(samples) < int(features.CHUNK * features.RATE) - hop:
            break
        t += features.CHUNK
    return out


def _normalise(values):
    import numpy as np

    array = np.asarray(values, dtype=np.float64)
    array = np.clip(array, -80.0, 0.0)
    array = array - array.mean()
    norm = float(np.linalg.norm(array))
    return array / norm if norm else array


def best_lag(reference, track, max_lag: int) -> tuple[int, float]:
    """The lag (in frames) at which `track` best matches `reference`, and the
    normalised correlation there. Positive lag: the track runs late."""
    import numpy as np

    a, b = _normalise(reference), _normalise(track)
    best, best_corr = 0, -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x, y = a[:len(a) - lag] if lag else a, b[lag:]
        else:
            x, y = a[-lag:], b[:len(b) + lag]
        n = min(len(x), len(y))
        if n < 20:
            continue
        xs, ys = x[:n], y[:n]
        denom = float(np.linalg.norm(xs) * np.linalg.norm(ys))
        corr = float(xs @ ys) / denom if denom else 0.0
        if corr > best_corr:
            best, best_corr = lag, corr
    return best, best_corr


def align(reference: list[float], track: list[float], *, max_offset: float = 2.0,
          min_correlation: float = 0.45) -> dict:
    """Verify one track against the reference envelope."""
    max_lag = max(1, int(max_offset / FRAME))
    if min(len(reference), len(track)) < 200:
        return {"state": "uncertain", "method": METHOD,
                "reason": "too little audio to align"}
    lag, corr = best_lag(reference, track, max_lag)
    if corr < min_correlation:
        return {"state": "uncertain", "method": METHOD, "correlation": round(corr, 3),
                "reason": f"envelopes correlate only {corr:.2f} within ±{max_offset:g}s"}
    windows = []
    size = min(len(reference), len(track)) // WINDOWS
    local = max(4, int(0.5 / FRAME))
    for w in range(WINDOWS):
        start = w * size
        ref = reference[start:start + size]
        shifted = track[max(0, start + lag):max(0, start + lag) + size]
        if len(ref) < 50 or len(shifted) < 50:
            continue
        sub_lag, sub_corr = best_lag(ref, shifted, local)
        windows.append({"start": round(start * FRAME, 2), "lag": round((lag + sub_lag) * FRAME, 3),
                        "correlation": round(sub_corr, 3)})
    usable = [w for w in windows if w["correlation"] >= MIN_WINDOW_CORR]
    # One window may disagree (a different opening or credits); more means
    # part of the programme is not the same edit.
    if len(usable) < max(2, len(windows) - 1):
        return {"state": "rejected", "method": METHOD, "correlation": round(corr, 3),
                "windows": windows,
                "reason": "most of the track does not line up: likely another edit"}
    lags = [w["lag"] for w in usable]
    times = [w["start"] for w in usable]
    spread = max(lags) - min(lags)
    if len(usable) >= 2 and max(times) > min(times):
        slope = (lags[-1] - lags[0]) / (times[-1] - times[0])
    else:
        slope = 0.0
    residual = max(abs(lag_ - (lags[0] + slope * (t - times[0]))) for lag_, t in zip(lags, times,
                                                                                  strict=True))
    if spread > MAX_SPREAD and residual > MAX_SPREAD:
        return {"state": "rejected", "method": METHOD, "correlation": round(corr, 3),
                "windows": windows, "spread": round(spread, 3),
                "reason": f"windows disagree by {spread:.2f}s: a scene was moved or cut"}
    # track = source + lag(source), lag(t) = lag0 + slope (t - t0); inverted to
    # source = track * rate + offset, the studio TimeMap convention.
    # A drift smaller than the jitter over the whole programme is not a rate.
    drifting = abs(slope) * (times[-1] - times[0]) > MAX_SPREAD
    rate = 1.0 / (1.0 + slope) if drifting else 1.0
    offset = (-(lags[0] - slope * times[0]) * rate if drifting
              else -sum(lags) / len(lags))
    return {"state": "verified", "method": METHOD, "correlation": round(corr, 3),
            "offset": round(offset, 3), "rate": round(rate, 6), "spread": round(spread, 3),
            "windows": windows}


def check_tracks(reference: Path, tracks: list[dict], *,
                 evaluation_streams: set[int] | frozenset[int] = frozenset(),
                 max_offset: float = 2.0, min_correlation: float = 0.45,
                 verify: bool = True, cancel=None) -> list[dict]:
    """One evidence record per candidate track: used or not, and why.

    `tracks` are ``{stream, path, lang, title}``. Returns the same tracks with
    ``state`` (verified | uncertain | rejected | excluded | unchecked) and, for
    a verified track, the offset and rate that map it onto the source.
    """
    out = []
    ref_env = None
    for track in tracks:
        row = {k: track.get(k) for k in ("stream", "lang", "title")}
        if int(track["stream"]) in evaluation_streams:
            out.append({**row, "state": "excluded",
                        "reason": "an evaluation-only reference: never used as evidence"})
            continue
        if EXCLUDED_TITLES.search(str(track.get("title") or "")):
            out.append({**row, "state": "excluded",
                        "reason": "its title says commentary or description, not a dub"})
            continue
        if not verify:
            out.append({**row, "state": "unchecked", "offset": 0.0, "rate": 1.0,
                        "reason": "alignment checking is off; used as-is"})
            continue
        try:
            if ref_env is None:
                ref_env = envelope(reference, cancel)
            result = align(ref_env, envelope(Path(track["path"]), cancel),
                           max_offset=max_offset, min_correlation=min_correlation)
        except OSError as exc:
            result = {"state": "uncertain", "reason": f"could not read the track: {exc}"}
        out.append({**row, **result})
    return out


def usable(evidence: list[dict]) -> set[int]:
    """Streams a grouping may use: verified, or explicitly unchecked."""
    return {int(e["stream"]) for e in evidence if e.get("state") in ("verified", "unchecked")}
