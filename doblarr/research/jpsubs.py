"""Japanese subtitles from a local clone of a subtitle mirror.

`research.kitsunekko_mirror` names a folder a person cloned once (for
example a git mirror of the kitsunekko archive: one folder per title, `.srt`
and `.ass` files inside). Everything here reads that folder: nothing about a
title leaves the machine. A title's folder is found by its names, folded the
same way cast names are, and each file becomes a `title_script` record of
kind `subtitles`: the original Japanese wording and timing of each line,
for checking speech recognition and for the source form of names and terms.
"""

from __future__ import annotations

from pathlib import Path

from .. import published_cast
from ..catalogues.base import name_key
from ..studio import records
from . import scripts

SUFFIXES = (".srt", ".ass", ".ssa", ".vtt")
MAX_FILES = 60


def _titles(db, series_id: str) -> list[str]:
    titles = [published_cast.series_title(db, series_id)]
    for record in published_cast.links(db, series_id):
        titles += [record.get("title") or "", *(record.get("titles") or {}).values()]
    info = records.get(db, "title_info", series_id) or {}
    titles += [a.get("title") or "" for a in info.get("aliases") or []]
    return [t for t in dict.fromkeys(str(t) for t in titles) if t]


def find_folder(mirror: str | Path, titles: list[str]) -> Path | None:
    """The mirror folder (up to two levels deep) whose name is one of the titles."""
    root = Path(mirror)
    if not root.is_dir():
        raise ValueError(f"the subtitle mirror {root} is not a folder on this machine")
    wanted = {name_key(t) for t in titles if t}
    loose = {k.replace(" ", "") for k in wanted}
    candidates = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    for parent in list(candidates):
        if parent.name.casefold() in {"subtitles", "anime_tv", "anime_movie", "drama_tv"}:
            candidates += [p for p in parent.iterdir() if p.is_dir()]
    for folder in candidates:
        key = name_key(folder.name)
        if key in wanted or key.replace(" ", "") in loose:
            return folder
    return None


def read_cues(path: Path) -> list[dict]:
    import pysubs2

    try:
        subs = pysubs2.load(str(path), encoding="utf-8")
    except UnicodeDecodeError:
        subs = pysubs2.load(str(path), encoding="cp932")
    out = []
    for event in subs:
        if getattr(event, "is_comment", False):
            continue
        text = " ".join(event.plaintext.split())
        if text:
            out.append({"kind": "dialogue", "speaker": None, "text": text,
                        "start_ms": int(event.start), "end_ms": int(event.end)})
    return out


def import_title(db, series_id: str, mirror: str | Path, *, titles: list[str] | None = None,
                 max_files: int = MAX_FILES) -> dict:
    """Keep the Japanese subtitles the mirror has for this title."""
    folder = find_folder(mirror, titles or _titles(db, series_id))
    if folder is None:
        return {"folder": None, "saved": []}
    saved = []
    files = sorted(p for p in folder.rglob("*") if p.suffix.casefold() in SUFFIXES)
    for path in files[:max_files]:
        try:
            cues = read_cues(path)
        except Exception:  # noqa: BLE001 - a broken file is skipped, not fatal
            continue
        if not cues:
            continue
        season, episode = scripts.episode_of(path.stem)
        saved.append(scripts.save(
            db, series_id, source="kitsunekko", url=path.relative_to(folder).as_posix(),
            lines=cues, kind="subtitles", title=path.name, season=season, episode=episode,
            language="ja")["id"])
    return {"folder": folder.name, "files": len(files), "saved": saved}
