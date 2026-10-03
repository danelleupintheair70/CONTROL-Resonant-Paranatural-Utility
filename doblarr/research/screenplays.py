"""Film screenplays and TV transcripts from public script archives.

Probes a few archives by the title's own URL pattern, fetches through
Prompture's `web_fetch` (Markdown, PDF text through its reader, refusing
private addresses, cached), and keeps what it finds as `title_script`
records. A miss is quiet: most titles are in none of them.

- IMSDb and Script Slug: film screenplays, with character cues, so lines
  carry speakers.
- Springfield! Springfield!: film and episode transcripts; dialogue only,
  without speakers, which is still the original wording.

Scripts are kept for analysis on this machine only and never redistributed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urlsplit

from .. import published_cast
from ..catalogues.base import Unreachable, wait_turn
from ..studio import records
from . import scripts

MIN_CHARS = 3000
MIN_SCREENPLAY_LINES = 20
MAX_EPISODES = 40

FetchText = Callable[[str], str]


def _web_fetch(url: str) -> str:
    from prompture.tools.web import web_fetch

    wait_turn(urlsplit(url).netloc, 2.0)
    try:
        return web_fetch(url, max_chars=0).content
    except Exception as exc:  # noqa: BLE001 - any failure to fetch is a miss
        raise Unreachable(f"{urlsplit(url).netloc}: {exc}") from exc


def slug(title: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.casefold())).strip("-")


def imsdb_url(title: str) -> str:
    words = re.sub(r"[^A-Za-z0-9 ]+", " ", title).split()
    return "https://imsdb.com/scripts/" + "-".join(w[:1].upper() + w[1:] for w in words) + ".html"


def scriptslug_url(title: str, year: int | None) -> str | None:
    return f"https://www.scriptslug.com/script/{slug(title)}-{year}" if year else None


def springfield_movie_url(title: str) -> str:
    return f"https://www.springfieldspringfield.co.uk/movie_script.php?movie={slug(title)}"


def springfield_episode_url(title: str, season: int, episode: int) -> str:
    return ("https://www.springfieldspringfield.co.uk/view_episode_scripts.php?"
            f"tv-show={slug(title)}&episode=s{season:02d}e{episode:02d}")


def transcript_lines(text: str) -> list[dict]:
    """Dialogue-only text as lines without speakers."""
    out = []
    for chunk in re.split(r"\n+|(?<=[.!?…])\s+(?=[-A-Z¿¡\"'])", str(text or "")):
        line = " ".join(chunk.replace("*", "").split()).lstrip("- ")
        if line and not line.startswith(("#", "[", "!")) and len(line) < 400:
            out.append({"kind": "dialogue", "speaker": None, "text": line})
    return out


def _is_screenplay(text: str) -> list[dict] | None:
    if len(text) < MIN_CHARS:
        return None
    lines = scripts.screenplay_lines(text)
    return lines if scripts.summary(lines)["dialogue"] >= MIN_SCREENPLAY_LINES else None


def _film(db, series_id: str, title: str, year: int | None, fetch: FetchText) -> list[str]:
    saved = []
    for source, url in (("imsdb", imsdb_url(title)), ("scriptslug", scriptslug_url(title, year))):
        if not url:
            continue
        try:
            lines = _is_screenplay(fetch(url))
        except (Unreachable, LookupError):
            continue
        if lines:
            saved.append(scripts.save(db, series_id, source=source, url=url, lines=lines,
                                      kind="screenplay", title=title, language="en")["id"])
    url = springfield_movie_url(title)
    try:
        text = fetch(url)
    except (Unreachable, LookupError):
        text = ""
    if len(text) >= MIN_CHARS:
        saved.append(scripts.save(db, series_id, source="springfield", url=url,
                                  lines=transcript_lines(text), kind="transcript", title=title,
                                  language="en")["id"])
    return saved


def _episodes(db, series_id: str) -> list[tuple[int, int]]:
    found = set()
    for media in records.list_latest(db, "media", scope=series_id):
        if media.get("season") is not None and media.get("episode") is not None:
            found.add((int(media["season"]), int(media["episode"])))
    return sorted(found)[:MAX_EPISODES]


def _show(db, series_id: str, title: str, fetch: FetchText) -> list[str]:
    saved = []
    for season, episode in _episodes(db, series_id):
        url = springfield_episode_url(title, season, episode)
        try:
            text = fetch(url)
        except (Unreachable, LookupError):
            continue
        if len(text) < MIN_CHARS:
            continue
        saved.append(scripts.save(db, series_id, source="springfield", url=url,
                                  lines=transcript_lines(text), kind="transcript",
                                  title=f"{title} S{season:02d}E{episode:02d}", season=season,
                                  episode=episode, language="en")["id"])
    return saved


def probe(db, series_id: str, *, title: str = "", fetch: FetchText | None = None) -> dict:
    """Look for this title's scripts; keep what is there, skip what is not."""
    fetch = fetch or _web_fetch
    title = title or published_cast.series_title(db, series_id)
    if not title:
        raise ValueError("no title known for this series")
    linked = published_cast.get(db, series_id) or {}
    if series_id.startswith("movie:"):
        saved = _film(db, series_id, title, linked.get("year"), fetch)
    else:
        saved = _show(db, series_id, title, fetch)
    return {"title": title, "saved": saved}
