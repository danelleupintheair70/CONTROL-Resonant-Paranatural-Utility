"""An episode broken down line by line, without dubbing it.

An analysis run stops where a dub would start writing: the dialogue is
separated, every line is cut (from subtitles or recognition), grouped by voice
(doblarr.speakers) and measured against its speaker's average level. This
step adds what a person needs to judge a line and a voice bank needs to pick
it:

- the line's pitch (median Hz) and how far it moves (semitones), from the
  separated dialogue, the same measures the clone reference picker ranks by;
- the original-language words. When the lines came from subtitles in another
  language (an English fansub of a Japanese show), recognition on the original dialogue
  gives the Japanese, word by word, and each word joins the line it falls in.

Everything lands in `<stem>.analysis.json` beside the script; the script keeps
the lines, speakers and levels. Nothing here is translated or generated.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from pathlib import Path

log = logging.getLogger("doblarr.analysis")

DETECTOR = "line-analysis/1"
RATE = 16000


def _stats(track: list[float]) -> tuple[float | None, float | None]:
    if len(track) < 5:
        return None, None
    centre = statistics.median(track)
    spread = (statistics.pstdev([12 * math.log2(f / centre) for f in track])
              if len(track) >= 10 else None)
    return round(centre, 1), (round(spread, 2) if spread is not None else None)


def voice_measures(samples, spans: list[tuple[float, float]]) -> list[dict]:
    """Pitch and pitch movement of each span of 16 kHz mono samples."""
    from .stages.synthesize import pitch_track_samples

    found = []
    for start, end in spans:
        chunk = samples[int(start * RATE):int(end * RATE)]
        pitch, movement = _stats(pitch_track_samples(chunk, RATE)) if len(chunk) else (None, None)
        found.append({"pitch_hz": pitch, "movement_st": movement})
    return found


def words_by_line(words: list[dict], spans: list[tuple[float, float]],
                  slack: float = 0.25) -> list[str]:
    """Join recognised words to the line whose window holds their midpoint."""
    texts: list[list[str]] = [[] for _ in spans]
    for word in words:
        if word.get("start") is None or word.get("end") is None:
            continue
        mid = (float(word["start"]) + float(word["end"])) / 2
        best, best_gap = None, slack
        for i, (start, end) in enumerate(spans):
            gap = 0.0 if start <= mid <= end else min(abs(mid - start), abs(mid - end))
            if gap <= best_gap:
                best, best_gap = i, gap
                if gap == 0.0:
                    break
        if best is not None:
            texts[best].append(str(word.get("word", "")).strip())
    joiner = ""   # Japanese and Chinese words carry no spaces between them
    return [joiner.join(t) if all(not any(c.isascii() and c.isalpha() for c in w) for w in t)
            else " ".join(t) for t in texts]


def run(job, work_dir: Path, *, whisper_model: str = "large-v3", device=None,
        recognise: bool = True) -> Path:
    """Measure every line and, if needed, recover its original words."""
    from .speakers import _audio
    from .stages.common import work_stem

    audio = job.vocals if job.vocals and Path(job.vocals).is_file() else job.source_audio
    spans = [(seg.start, seg.end) for seg in job.segments]
    samples = _audio(Path(audio))
    measures = voice_measures(samples, spans)
    original: list[str] | None = None
    source_lang = (job.source_lang or "").split("-")[0]
    script_lang = (job.script_lang or "").split("-")[0]
    if recognise and source_lang and script_lang and source_lang != script_lang:
        from .stages.transcribe import _faster_whisper_segments

        heard = _faster_whisper_segments(job, Path(audio), whisper_model, device)
        words = [w for seg in heard for w in (seg.words or [])]
        original = words_by_line(words, spans)
        log.info("analysis: %d original-language word(s) placed on %d line(s)",
                 len(words), sum(bool(t) for t in original))
    lines = []
    for i, seg in enumerate(job.segments):
        lines.append({"cue": seg.cue_id, "index": seg.index, **measures[i],
                      "original_text": original[i] if original is not None else None})
    path = Path(work_dir) / f"{work_stem(job)}.analysis.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "detector": DETECTOR, "source_lang": job.source_lang, "script_lang": job.script_lang,
        "original_text": original is not None, "lines": lines}, ensure_ascii=False),
        encoding="utf-8")
    return path
