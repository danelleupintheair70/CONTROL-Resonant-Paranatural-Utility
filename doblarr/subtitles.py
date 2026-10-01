"""Read subtitle tracks embedded in a video (ffprobe/ffmpeg).

Doblarr uses embedded subs as the timed script when no external .srt is given:
the target-language track (e.g. English) is already the translation, and its
timestamps drive where each dubbed line lands.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .discovery import ISO3_TO_ISO2
from .ffmpeg import FFmpegError, run_ffmpeg, run_ffprobe

log = logging.getLogger("doblarr.subtitles")


def sub_streams(video: Path) -> list[dict]:
    """List embedded text subtitle streams as {index, lang, codec}."""
    out = run_ffprobe(["-v", "error", "-select_streams", "s",
                       "-show_entries", "stream=index,codec_name:stream_tags=language",
                       "-of", "json", str(video)])
    data = json.loads(out or "{}")
    streams = []
    for s in data.get("streams", []):
        streams.append({
            "index": s["index"],
            "codec": s.get("codec_name", ""),
            "lang": (s.get("tags") or {}).get("language", "und"),
        })
    return streams


# Text subtitle codecs we can convert to SRT (image subs like PGS can't be).
_TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt"}


def pick_stream(streams: list[dict], prefer_lang: str) -> dict | None:
    text = [s for s in streams if s["codec"] in _TEXT_CODECS]
    if not text:
        return None
    p = prefer_lang.strip().lower()
    p = ISO3_TO_ISO2.get(p, p)
    for s in text:
        tag = s["lang"].lower()
        if ISO3_TO_ISO2.get(tag, tag) == p:
            return s
    return None


# Styled (ASS/SSA) subtitles carry more than dialogue: fansubs typeset the
# opening and ending songs twice (romaji and translation), the episode title
# and on-screen signs, each in a style named for what it is. None of it is a
# line anybody speaks, and read as dialogue it becomes the episode's two
# "loudest voices". Events in such a style are dropped before conversion.
NOT_DIALOGUE = re.compile(r"lyric|karaoke|kfx|song|romaji|\bop\b|\bed\b|sign|title|typeset",
                          re.IGNORECASE)


def extract_srt(video: Path, stream_index: int, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    styled = dest.with_suffix(".styled.ass")
    try:
        run_ffmpeg(["-y", "-i", str(video), "-map", f"0:{stream_index}", str(styled)])
        kept = dialogue_only(styled.read_text(encoding="utf-8-sig", errors="replace"))
        styled.write_text(kept, encoding="utf-8")
        run_ffmpeg(["-y", "-i", str(styled), str(dest)])
    except (FFmpegError, OSError):
        # A stream ffmpeg cannot write as ASS is plain text already.
        run_ffmpeg(["-y", "-i", str(video), "-map", f"0:{stream_index}", str(dest)])
    finally:
        styled.unlink(missing_ok=True)
    return dest


def dialogue_only(ass: str) -> str:
    """The same ASS document without events in a song, sign or title style."""
    out: list[str] = []
    fields: list[str] | None = None
    section = ""
    for line in ass.splitlines():
        if line.startswith("["):
            section = line.strip().lower()
        elif section == "[events]" and line.startswith("Format:"):
            fields = [f.strip().lower() for f in line[len("Format:"):].split(",")]
        if line.startswith("Dialogue:") and fields and "style" in fields:
            parts = line[len("Dialogue:"):].split(",", len(fields) - 1)
            style = parts[fields.index("style")].strip() if len(parts) == len(fields) else ""
            if NOT_DIALOGUE.search(style):
                continue
        out.append(line)
    return "\n".join(out) + "\n"
