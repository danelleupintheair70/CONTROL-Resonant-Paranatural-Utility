"""Reference scripts of a title: transcripts, screenplays and subtitles found online.

A reference script is somebody else's text of the dialogue. It can name who
speaks a line, give the original wording, or show where the lines of a scene
break, so it is useful next to the analysed subtitles; it is never evidence
from the episode itself. Each one is kept as a `title_script` record with its
source and URL, apart from what episodes taught, and is only read by an
analysis when `analysis.use_reference_scripts` is on.

This module keeps the records and the parts every source shares: turning
wiki markup and screenplay layout into speaker-labelled lines, and aligning
those lines to an episode's subtitle cues by their words.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from ..artifacts import digest
from ..catalogues.base import name_key
from ..studio import records

KIND = "title_script"
MAX_LINES = 8000
# "Episode 4", "Ep. 4", "S01E04", "Harbor Lights - 04 [720p]", "04 The Night Tide"
_EPISODE = re.compile(r"(?:\bep(?:isode)?\.?\s*#?\s*|\b[sS]\d{1,2}[eE]|\s-\s|^)(\d{1,4})\b",
                      re.IGNORECASE)
_SEASON = re.compile(r"\b(?:season\s*|s)(\d{1,2})(?=\b|e\d)", re.IGNORECASE)


# -- records -----------------------------------------------------------------

def save(db, series_id: str, *, source: str, url: str, lines: list[dict], kind: str,
         title: str = "", season: int | None = None, episode: int | None = None,
         language: str = "", extra: dict | None = None) -> dict:
    """Keep one found script (replacing an earlier fetch of the same page)."""
    sid = "ts-" + digest([series_id, source, url])[:16]
    current = records.get(db, KIND, sid)
    document = {"series_id": series_id, "source": source, "url": url, "kind": kind,
                "title": title, "season": season, "episode": episode, "language": language,
                "lines": lines[:MAX_LINES], "truncated": len(lines) > MAX_LINES,
                "speakers": sorted({str(line["speaker"]) for line in lines
                                    if line.get("speaker")})[:200],
                "fetched_at": records.now_marker(), **(extra or {})}
    return records.put(db, KIND, sid, document, scope=series_id,
                       base_revision=current["revision"] if current else 0)


def listing(db, series_id: str) -> list[dict]:
    """Found scripts without their lines, by season and episode."""
    out = []
    for r in records.list_latest(db, KIND, scope=series_id):
        out.append({k: r.get(k) for k in ("id", "source", "url", "kind", "title", "season",
                                          "episode", "language", "fetched_at", "truncated")}
                   | {"lines": len(r.get("lines") or []),
                      "speakers": len(r.get("speakers") or [])})
    return sorted(out, key=lambda r: (r["season"] or 0, r["episode"] or 0, r["title"] or ""))


def for_episode(db, series_id: str, *, season: int | None, episode: int | None,
                kinds: tuple[str, ...] = ("transcript", "screenplay")) -> list[dict]:
    """Scripts that name this episode (or the film, when there is no episode)."""
    found = []
    for r in records.list_latest(db, KIND, scope=series_id):
        if r.get("kind") not in kinds:
            continue
        if episode is None or r.get("episode") == episode and (
                r.get("season") in (None, season) or season is None):
            found.append(r)
    return found


def episode_of(title: str) -> tuple[int | None, int | None]:
    """(season, episode) a page title names, when it names one."""
    text = str(title or "")
    season = _SEASON.search(text)
    match = _EPISODE.search(text.rsplit("/", 1)[0] if "/" in text else text)
    return (int(season.group(1)) if season else None,
            int(match.group(1)) if match else None)


# -- parsing -----------------------------------------------------------------

_REF = re.compile(r"<ref[^>]*?(?:/>|>.*?</ref>)", re.IGNORECASE | re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_EXTERNAL = re.compile(r"\[https?://\S+\s*([^\]]*)\]")
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_DIRECTION = re.compile(r"\[[^\]]*\]|\(\s*''[^)]*''\s*\)")
_SPEAKER = re.compile(r"^\s*(?:'''|\*\*)?([A-Z][\w .'\-&]{0,40}?)(?:'''|\*\*)?\s*:\s*(?:'''|\*\*)?"
                      r"\s*(.+)$")
_HEADING = re.compile(r"^\s*=+\s*(.*?)\s*=+\s*$")


def _spoken(text: str) -> str:
    """A spoken line without its bracketed directions (links are kept as words)."""
    text = _EXTERNAL.sub(r"\1", _LINK.sub(r"\1", text))
    return _clean(_DIRECTION.sub("", text))


def _clean(text: str) -> str:
    text = _LINK.sub(r"\1", text)
    text = _EXTERNAL.sub(r"\1", text)
    text = _TAG.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    return " ".join(text.split())


def wikitext_lines(wikitext: str) -> list[dict]:
    """Speaker-labelled lines from a wiki transcript.

    Reads the table form (`!Speaker` then `|line`), the colon form
    (`Speaker: line`, bold or not) and headings as scene breaks. Italic
    narration becomes an `action` line; bracketed directions inside a spoken
    line are dropped from its text.
    """
    text = _COMMENT.sub("", _REF.sub("", str(wikitext or "")))
    for _ in range(4):
        text = _TEMPLATE.sub("", text)
    out: list[dict] = []
    speaker: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("{|", "|}", "|-", "[[Category", "[[File", "__")):
            if line.startswith("|-"):
                speaker = None
            continue
        heading = _HEADING.match(line)
        if heading:
            out.append({"kind": "scene", "speaker": None, "text": _clean(heading.group(1))})
            continue
        if line.startswith("!"):
            speaker = _clean(line.lstrip("!").split("|")[-1]) or None
            continue
        if line.startswith("|"):
            body = line[1:]
            if body.strip().startswith("''") and body.strip().endswith("''") and not speaker:
                cleaned = _clean(body)
                if cleaned:
                    out.append({"kind": "action", "speaker": None, "text": cleaned})
                continue
            spoken = _spoken(body)
            if spoken:
                out.append({"kind": "dialogue" if speaker else "action", "speaker": speaker,
                            "text": spoken})
            continue
        match = _SPEAKER.match(line)
        if match and len(match.group(1).split()) <= 4:
            spoken = _spoken(match.group(2))
            if spoken:
                out.append({"kind": "dialogue", "speaker": _clean(match.group(1)),
                            "text": spoken})
            continue
        cleaned = _clean(line)
        if cleaned:
            out.append({"kind": "action", "speaker": None, "text": cleaned})
    return out


_CUE = re.compile(r"^[A-Z][A-Z0-9 .'\-]{1,30}(?:\s*\((?:V\.?O\.?|O\.?S\.?|CONT'D|O\.?C\.?)\))*$")
_SLUG = re.compile(r"^(?:INT|EXT|INT\./EXT|EST)\b", re.IGNORECASE)
_TRANSITION = re.compile(r"^(?:CUT TO|FADE (?:IN|OUT)|DISSOLVE TO|SMASH CUT)", re.IGNORECASE)


def screenplay_lines(text: str) -> list[dict]:
    """Speaker-labelled lines from a screenplay's plain text.

    A character cue is a short line in capitals; the lines under it, up to
    a blank line, are what they say. Scene headings (INT./EXT.) are scene
    breaks; everything else is action.
    """
    out: list[dict] = []
    speaker: str | None = None
    spoken: list[str] = []

    def flush() -> None:
        nonlocal speaker, spoken
        if speaker and spoken:
            said = " ".join(_DIRECTION.sub("", " ".join(spoken)).split())
            said = re.sub(r"^\([^)]*\)\s*", "", said)
            if said:
                out.append({"kind": "dialogue", "speaker": speaker.title(), "text": said})
        speaker, spoken = None, []

    for raw in str(text or "").splitlines():
        line = " ".join(raw.replace("*", "").replace("#", "").split())
        if not line:
            flush()
            continue
        if _SLUG.match(line):
            flush()
            out.append({"kind": "scene", "speaker": None, "text": line})
        elif _TRANSITION.match(line):
            flush()
        elif _CUE.match(line) and not speaker:
            flush()
            speaker = re.sub(r"\s*\(.*$", "", line).strip()
        elif speaker:
            spoken.append(line)
        else:
            out.append({"kind": "action", "speaker": None, "text": line})
    flush()
    return out


# -- alignment ---------------------------------------------------------------

def _words(text: str) -> str:
    return name_key(text)


def align(lines: list[dict], cues: list[dict], *, min_score: float = 0.55,
          window: int = 40) -> dict[int, dict]:
    """Script lines matched to subtitle cues by their words, in order.

    Walks both in order: each cue looks at the next `window` dialogue lines
    after the last match and takes the most similar one when it is similar
    enough. Returns {cue ordinal: {speaker, text, score, line}}; unmatched
    cues are left out, so a matcher never reads a guess.
    """
    spoken = [(i, line) for i, line in enumerate(lines) if line.get("kind") == "dialogue"]
    keys = [_words(line["text"]) for _, line in spoken]
    out: dict[int, dict] = {}
    at = 0
    for cue in cues:
        text = _words(cue.get("text") or "")
        if not text:
            continue
        best, best_score = None, 0.0
        for j in range(at, min(len(spoken), at + window)):
            if not keys[j]:
                continue
            score = SequenceMatcher(None, text, keys[j], autojunk=False).ratio()
            if text in keys[j] or keys[j] in text:
                score = max(score, min(len(text), len(keys[j])) / max(len(text), len(keys[j]))
                            + 0.3)
            if score > best_score:
                best, best_score = j, score
        if best is not None and best_score >= min_score:
            index, line = spoken[best]
            out[int(cue["ordinal"])] = {"speaker": line.get("speaker"), "text": line["text"],
                                        "score": round(min(best_score, 1.0), 3), "line": index}
            at = best
    return out


def reference_for(db, ident: dict, cues: list[dict]) -> dict[int, dict] | None:
    """Aligned reference lines for one analysed episode, from the best script found."""
    media = records.get(db, "media", ident.get("media_id") or "") or {}
    series_id = ident.get("series_id") or ""
    best: dict[int, dict] = {}
    for script in for_episode(db, series_id, season=media.get("season"),
                              episode=media.get("episode")):
        aligned = align(script.get("lines") or [], cues)
        if len(aligned) > len(best):
            best = {k: {**v, "source": script["source"]} for k, v in aligned.items()}
    return best or None


def summary(lines: list[dict[str, Any]]) -> dict:
    spoken = [line for line in lines if line.get("kind") == "dialogue"]
    return {"lines": len(lines), "dialogue": len(spoken),
            "speakers": len({line["speaker"] for line in spoken if line.get("speaker")})}
