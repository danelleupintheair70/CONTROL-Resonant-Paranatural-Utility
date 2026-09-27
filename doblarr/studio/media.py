"""Bounded media for the studio: windows, peaks, playable video and track sync.

Everything here reads the original media and writes small derived files into
the studio's own cache under the work directory. Nothing here writes next to
the original, and nothing is kept that was not asked for: a window is cut once,
cached by its exact request, and served with the same path guard as every
other preview.
"""

from __future__ import annotations

import array
import json
import math
import sys
import wave
from pathlib import Path

from ..artifacts import digest, stamp
from ..ffmpeg import run_ffmpeg, run_ffprobe

MAX_WINDOW = 240.0          # seconds of media one request may cut
PEAK_BUCKETS = 480
VIDEO_HEIGHT = 360


def probe(media: Path) -> dict:
    """Streams in a media file, as tagged — which is not proof of content."""
    out = run_ffprobe(["-v", "error", "-show_entries",
                       "stream=index,codec_type,codec_name,channels:stream_tags=language,title"
                       ":format=duration", "-of", "json", str(media)])
    data = json.loads(out or "{}")
    streams = []
    audio_n = 0
    for s in data.get("streams", []):
        row = {"index": s.get("index"), "type": s.get("codec_type"),
               "codec": s.get("codec_name"), "channels": s.get("channels"),
               "language": (s.get("tags") or {}).get("language", ""),
               "title": (s.get("tags") or {}).get("title", "")}
        if row["type"] == "audio":
            row["audio_index"] = audio_n
            audio_n += 1
        streams.append(row)
    duration = (data.get("format") or {}).get("duration")
    return {"media_key": digest(stamp(media))[:16], "streams": streams,
            "duration": float(duration) if duration else None,
            "note": "Track language tags and titles are what the release says, not a check "
                    "of what each track contains."}


def _cache(root: Path, request: dict, suffix: str) -> Path:
    return Path(root) / "studio" / "cache" / f"{digest(request)[:24]}{suffix}"


def cut_audio(media: Path, start: float, end: float, root: Path, *, stream: int | None = None,
              rate: int = 24000, cancel=None) -> Path:
    """A mono WAV window of one audio stream, cached by its exact request."""
    start = max(0.0, float(start))
    end = float(end)
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("a window needs a finite end after its start")
    if end - start > MAX_WINDOW:
        raise ValueError(f"a studio window is at most {MAX_WINDOW:.0f}s")
    request = {"media": stamp(Path(media)), "start": round(start, 3), "end": round(end, 3),
               "stream": stream, "rate": rate, "kind": "audio/1"}
    dest = _cache(root, request, ".wav")
    if dest.is_file() and dest.stat().st_size > 44:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(".partial.wav")
    args = ["-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
            "-i", str(media)]
    if stream is not None:
        args += ["-map", f"0:a:{int(stream)}"]
    args += ["-vn", "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(temp)]
    run_ffmpeg(args, cancel=cancel)
    temp.replace(dest)
    return dest


def cut_video(media: Path, start: float, end: float, root: Path, cancel=None) -> Path:
    """A small, silent, browser-playable H.264 proxy of one window.

    The studio's single audio player owns playback; this picture follows it.
    Original releases are often HEVC in Matroska, which most browsers cannot
    play, so a proxy is the honest way to show the scene rather than a video
    element that silently fails.
    """
    start = max(0.0, float(start))
    end = float(end)
    if end <= start or end - start > MAX_WINDOW:
        raise ValueError(f"a video window must be under {MAX_WINDOW:.0f}s")
    request = {"media": stamp(Path(media)), "start": round(start, 3), "end": round(end, 3),
               "height": VIDEO_HEIGHT, "kind": "video/1"}
    dest = _cache(root, request, ".mp4")
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(".partial.mp4")
    run_ffmpeg(["-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
                "-i", str(media), "-map", "0:v:0", "-an",
                "-vf", f"scale=-2:{VIDEO_HEIGHT}", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(temp)], cancel=cancel)
    temp.replace(dest)
    return dest


def peaks(path: Path, buckets: int = PEAK_BUCKETS) -> list[float]:
    """Normalized peak envelope of a 16-bit WAV, for drawing a waveform."""
    with wave.open(str(path), "rb") as audio:
        if audio.getsampwidth() != 2:
            return []
        frames = audio.getnframes()
        channels = audio.getnchannels()
        raw = array.array("h", audio.readframes(frames))
    if sys.byteorder != "little":
        raw.byteswap()
    if channels > 1:
        raw = array.array("h", raw[::channels])
    if not raw:
        return []
    size = max(1, len(raw) // buckets)
    values = [max(abs(v) for v in raw[i:i + size]) for i in range(0, len(raw), size)]
    top = max(values) or 1
    return [round(v / top, 3) for v in values[:buckets]]


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / float(audio.getframerate() or 1)


def envelope(media: Path, root: Path, stream: int | None = None, rate: int = 8000,
             hop: int = 80, cancel=None):
    """A 100 Hz loudness envelope of a whole track (numpy array), cached."""
    import numpy as np

    request = {"media": stamp(Path(media)), "stream": stream, "rate": rate, "hop": hop,
               "kind": "envelope/1"}
    cache = _cache(root, request, ".npy")
    if cache.is_file():
        return np.load(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temp = cache.with_suffix(".raw")
    args = ["-y", "-v", "error", "-i", str(media)]
    if stream is not None:
        args += ["-map", f"0:a:{int(stream)}"]
    args += ["-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", str(temp)]
    run_ffmpeg(args, cancel=cancel)
    samples = np.fromfile(temp, dtype=np.int16).astype(np.float32)
    temp.unlink(missing_ok=True)
    n = len(samples) // hop
    env = np.abs(samples[:n * hop]).reshape(n, hop).mean(axis=1)
    np.save(cache, env)
    return env


def _xcorr_offset(a, b, max_lag: int):
    """Lag (in envelope frames) that best aligns b onto a, and its peak strength."""
    import numpy as np

    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    size = 1 << int(math.ceil(math.log2(len(a) + len(b))))
    corr = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    lags = np.concatenate([np.arange(0, max_lag + 1), np.arange(-max_lag, 0)])
    values = np.concatenate([corr[:max_lag + 1], corr[size - max_lag:]])
    best = int(np.argmax(values))
    return int(lags[best]), float(values[best] / len(b))


def estimate_time_map(source_env, reference_env, window: float = 30.0, step: float = 60.0,
                      max_shift: float = 20.0, min_peak: float = 0.35) -> dict:
    """Piecewise offsets of a reference track against the source, by windowed correlation.

    Reference windows are correlated against the source around their own time;
    runs of consistent offsets become map segments. A window whose peak is weak
    is left unmapped rather than guessed, and a jump between runs is reported,
    because that is what a cut or an inserted scene looks like.
    """
    fps = 100.0
    win, stride, shift = int(window * fps), int(step * fps), int(max_shift * fps)
    points = []
    for start in range(0, max(1, len(reference_env) - win), stride):
        chunk = reference_env[start:start + win]
        lo = max(0, start - shift)
        hi = min(len(source_env), start + win + shift)
        if hi - lo < win:
            continue
        lag, peak = _xcorr_offset(source_env[lo:hi], chunk, hi - lo - 1)
        offset = (lo + lag - start) / fps
        points.append({"at": start / fps, "offset": round(offset, 2), "peak": round(peak, 3)})
    runs: list[dict] = []
    for point in points:
        if point["peak"] < min_peak or abs(point["offset"]) > max_shift:
            continue
        if runs and abs(runs[-1]["offsets"][-1] - point["offset"]) <= 0.25:
            runs[-1]["end"] = point["at"] + step
            runs[-1]["offsets"].append(point["offset"])
            runs[-1]["peaks"].append(point["peak"])
        else:
            runs.append({"start": point["at"], "end": point["at"] + step,
                         "offsets": [point["offset"]], "peaks": [point["peak"]]})
    segments = []
    for n, run in enumerate(runs):
        seg_start = float(run["start"]) if n else 0.0
        seg_end = (float(runs[n + 1]["start"]) if n + 1 < len(runs)
                   else len(reference_env) / fps + 1)
        offsets = sorted(run["offsets"])
        segments.append({"start": round(seg_start, 2),
                         "end": round(max(seg_end, seg_start + 1), 2),
                         "offset": offsets[len(offsets) // 2], "rate": 1.0,
                         "confidence": round(min(1.0, sum(run["peaks"]) / len(run["peaks"])), 3),
                         "method": "xcorr"})
    jumps = [{"at": runs[n + 1]["start"],
              "from": runs[n]["offsets"][-1], "to": runs[n + 1]["offsets"][0]}
             for n in range(len(runs) - 1)]
    return {"segments": segments, "points": points, "jumps": jumps,
            "unmapped_windows": sum(1 for p in points if p["peak"] < min_peak)}
