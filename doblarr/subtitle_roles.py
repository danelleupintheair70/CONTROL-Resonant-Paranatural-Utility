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
        none.parent.mkdir(parents=True, exist_ok=True)
        none.write_text("", encoding="utf-8")
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_ffmpeg(["-y", "-i", str(video), "-map", f"0:{chosen['index']}", str(path)])
    except Exception:  # noqa: BLE001 - styles are a bonus; the lines stand without them
        path.unlink(missing_ok=True)
        return None
    return path if path.is_file() else None


# ---- what a role means for the dub ----

PREVIEW_DIRECTION = ("narrating the next-episode preview to the audience: lively, announcing, "
                     "clear")
NARRATION_DIRECTION = "as a narrator speaking to the audience: clear, measured, unhurried"


def direct(segments, roles: dict[str, dict]) -> dict[str, int]:
    """Give lines the delivery their role asks for, where nobody said otherwise.

    A voice-over line (italics: a thought, a flashback, an off-screen voice)
    is asked for as an inner thought, close and unprojected; a preview or a
    narration line as told to the audience. A line a person or a cast choice
    already directed keeps its direction. Returns how many lines changed, per
    role. Loudness and room are left to their owners (levels, treatments).
    """
    changed: dict[str, int] = {}
    for seg in segments:
        role = (roles.get(str(seg.cue_id)) or {}).get("role")
        intent = seg.intent
        if role not in ("inner", "preview", "narration") or seg.delivery \
                or intent.origin not in ("unknown", "", "subtitles"):
            continue
        if role == "inner" and intent.mode in ("unknown", "normal"):
            intent.mode = "thought"
        elif role == "preview":
            intent.direction = PREVIEW_DIRECTION
        elif role == "narration":
            intent.direction = NARRATION_DIRECTION
        else:
            continue
        intent.origin = "subtitles"
        changed[role] = changed.get(role, 0) + 1
    return changed


def _clusters(found: list[dict], role: str, gap: float) -> list[list[float]]:
    spans: list[list[float]] = []
    for e in sorted((e for e in found if e["role"] == role), key=lambda e: e["start"]):
        if spans and e["start"] - spans[-1][1] <= gap:
            spans[-1][1] = max(spans[-1][1], e["end"])
        else:
            spans.append([e["start"], e["end"]])
    return spans


def song_spans(found: list[dict], gap: float = 4.0, pad: float = 0.5) -> list[list[float]]:
    """Where the songs are sung: lyric events joined across short gaps."""
    return [[round(max(0.0, a - pad), 2), round(b + pad, 2)]
            for a, b in _clusters(found, "song", gap)]


def structure(found: list[dict], duration: float) -> list[dict]:
    """The episode's parts: cold open, opening, episode, ending, preview, extra.

    Songs near the start and end are the opening and ending; the preview and
    the extra are the spans of their styled lines. What lies between the
    opening and whatever comes after is the episode itself."""
    duration = max(duration, max((e["end"] for e in found), default=0.0))
    parts: list[dict] = []
    songs = _clusters(found, "song", 12.0)
    opening = next((s for s in songs if s[0] < duration * 0.35 and s[1] - s[0] > 30), None)
    ending = next((s for s in reversed(songs) if s[0] > duration * 0.6 and s[1] - s[0] > 30
                   and s is not opening), None)
    preview = _clusters(found, "preview", 15.0)
    extra = _clusters(found, "extra", 15.0)
    if opening:
        if opening[0] > 15:
            parts.append({"kind": "cold-open", "start": 0.0, "end": opening[0]})
        parts.append({"kind": "opening", "start": opening[0], "end": opening[1]})
    body_start = opening[1] if opening else 0.0
    later = [s[0] for s in (ending, *(preview[:1]), *(extra[:1])) if s]
    body_end = min(later) if later else duration
    parts.append({"kind": "episode", "start": body_start, "end": body_end})
    if ending:
        parts.append({"kind": "ending", "start": ending[0], "end": ending[1]})
    for a, b in preview:
        parts.append({"kind": "preview", "start": a, "end": b})
    for a, b in extra:
        parts.append({"kind": "extra", "start": a, "end": b})
    for s in songs:
        if s is not opening and s is not ending and s[1] - s[0] > 10:
            parts.append({"kind": "song", "start": s[0], "end": s[1]})
    return [{**p, "start": round(p["start"], 2), "end": round(p["end"], 2)}
            for p in sorted(parts, key=lambda p: p["start"])]
