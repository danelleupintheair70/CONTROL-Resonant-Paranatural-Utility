"""What kind of line each subtitle is, from the subtitle file's own styles.

A styled subtitle track (ASS) says more than its words. Fansub and studio
tracks name their styles for what a line is: "Signs" and "Title" for text
drawn on the picture, "Lyrics OP/ED" for the songs, "NEP" or "Next Episode"
for the narrated preview at the end, "Narrator", "Thoughts", "Flashback",
"Omake". Italics inside an ordinary line mark an inner voice or a voice from
off screen. Converting the track to plain text loses all of it, so the styled
copy is kept beside the script and read here.

A line's role (dialogue, voice-over, preview, narration, flashback, extra;
italics alone cannot tell a thought from a flashback or an off-screen voice,
so they are one role, "inner", shown as voice-over)
helps whoever names the voices (a preview is usually one narrator) and later
how it is dubbed. The on-screen events are the episode's text on screen,
already translated and timed. The rules match common style names; a track
without styles leaves every line "dialogue".
"""

from __future__ import annotations

import re
from pathlib import Path

READER = "subtitle-roles/1"
SPOKEN_ROLES = ("dialogue", "inner", "preview", "narration", "flashback", "extra")

# Style name -> what its events are. First match wins.
_ROLE_PATTERNS = (
    (r"lyric|karaoke|\bsong|\bop\b|\bed\b|opening|ending|insert", "song"),
    (r"\bnep\b|next.?ep|preview|yokoku", "preview"),
    (r"narr", "narration"),
    (r"thought|think|inner|monolog", "inner"),
    (r"flash.?back|memory", "flashback"),
    (r"omake|extra|bonus", "extra"),
    (r"sign|title|card|caption|screen|\bnote|\btl\b|logo|credit", "onscreen"),
)
_STYLE_ROLES = tuple((re.compile(pattern, re.I), role) for pattern, role in _ROLE_PATTERNS)
_ITALIC = re.compile(r"\{[^}]*\\i1[^}]*\}")


def style_role(style: str) -> str:
    for pattern, role in _STYLE_ROLES:
        if pattern.search(style or ""):
            return role
    return "dialogue"


def events(path: Path) -> list[dict]:
    """Every event of a styled subtitle file: time, text, style, italics, role."""
    import pysubs2

    subs = pysubs2.load(str(path))
    italic_styles = {name for name, style in subs.styles.items() if getattr(style, "italic", False)}
    out = []
    for line in subs:
        text = line.plaintext.replace("\n", " ").strip()
        if line.is_comment or not text:
            continue
        role = style_role(line.style)
        italic = bool(_ITALIC.search(line.text or "")) or line.style in italic_styles
        if role == "dialogue" and italic:
            role = "inner"
        out.append({"start": line.start / 1000.0, "end": line.end / 1000.0, "text": text,
                    "style": line.style, "italic": italic, "role": role})
    return out


def annotate(lines: list[dict], found: list[dict]) -> dict[str, dict]:
    """Per cue: the role of the spoken events it was made from.

    A line may join several events (two subtitle cues read as one line); it
    takes the role most of their time had, and is an inner voice only when
    all of them were."""
    spoken = [e for e in found if e["role"] in SPOKEN_ROLES]
    out: dict[str, dict] = {}
    for line in lines:
        start, end = float(line["start"]), float(line["end"])
        hits = [e for e in spoken if min(end, e["end"]) - max(start, e["start"]) > 0.05
                or abs(e["start"] - start) < 0.35]
        if not hits:
            continue
        time: dict[str, float] = {}
        for e in hits:
            time[e["role"]] = time.get(e["role"], 0.0) + max(0.05, e["end"] - e["start"])
        role = max(time, key=lambda r: time[r])
        if role == "inner" and not all(e["role"] == "inner" for e in hits):
            role = "dialogue"
        out[str(line.get("cue"))] = {"role": role, "style": hits[0]["style"],
                                     "italic": all(e["italic"] for e in hits)}
    return out


def on_screen(found: list[dict]) -> list[dict]:
    """The text drawn on the picture: signs and title cards, once each."""
    seen, out = set(), []
    for e in found:
        if e["role"] != "onscreen":
            continue
        key = e["text"].casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({"start": e["start"], "end": e["end"], "text": e["text"],
                    "kind": "title" if re.search(r"title|card", e["style"], re.I) else "sign"})
    return out


def styled_copy(script: Path) -> Path:
    """Where the styled subtitle track of a script's run is kept."""
    return script.with_name(script.name.replace(".script.json", ".styles.ass"))


def ensure_styled(script: Path, video: Path, lang: str) -> Path | None:
    """The styled track beside the script, extracted from the video once if a
    run kept only the plain text. None when the video has no styled track."""
    from . import subtitles
    from .ffmpeg import run_ffmpeg

    path = styled_copy(script)
    none = path.with_suffix(".none")          # looked once: the video has no styled track
    if path.is_file():
        return path
    if none.is_file() or not video.is_file():
        return None
    try:
        streams = subtitles.sub_streams(video)
    except Exception:  # noqa: BLE001 - an unreadable video simply has no styles to read
        return None
    chosen = subtitles.pick_stream(streams, lang) if lang else None
    if not chosen or chosen.get("codec") not in ("ass", "ssa"):
        none.write_text("", encoding="utf-8")
        return None
    try:
        run_ffmpeg(["-y", "-i", str(video), "-map", f"0:{chosen['index']}", str(path)])
    except Exception:  # noqa: BLE001 - styles are a bonus; the lines stand without them
        path.unlink(missing_ok=True)
        return None
    return path if path.is_file() else None
