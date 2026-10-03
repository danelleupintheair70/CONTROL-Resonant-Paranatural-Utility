"""Subtitles in other languages from OpenSubtitles (optional, keyed).

With `research.opensubtitles_api_key` set, a person can fetch a title's
subtitles in another language (an English or Spanish track to compare a dub
against, or to measure a region's wording). The free tier allows about
twenty downloads a day, plenty for one title at a time. Without a key the
source is off and says so. The title (or its TMDB id) and the episode number
are what leave the machine.
"""

from __future__ import annotations

from .. import published_cast
from ..catalogues import base
from ..catalogues.base import Fetch, Unreachable
from ..studio import records
from . import scripts

API = "https://api.opensubtitles.com/api/v1"
MAX_DOWNLOADS = 5


class OpenSubtitles:
    def __init__(self, api_key: str, fetch: Fetch | None = None):
        if not api_key:
            raise Unreachable("OpenSubtitles needs research.opensubtitles_api_key")
        self.headers = {"Api-Key": api_key, "Accept": "application/json"}
        self._fetch = fetch

    def search(self, *, query: str = "", tmdb_id: int | None = None, languages: str = "en",
               season: int | None = None, episode: int | None = None) -> list[dict]:
        params: dict = {"languages": languages}
        if tmdb_id:
            params["tmdb_id" if episode is None else "parent_tmdb_id"] = tmdb_id
        else:
            params["query"] = query
        if season is not None:
            params["season_number"] = season
        if episode is not None:
            params["episode_number"] = episode
        data = base.get_json(self._fetch, f"{API}/subtitles", params=params,
                             headers=self.headers, interval=1.0)
        out = []
        for item in (data or {}).get("data") or []:
            attrs = item.get("attributes") or {}
            files = attrs.get("files") or []
            if not files:
                continue
            feature = attrs.get("feature_details") or {}
            out.append({"file_id": files[0].get("file_id"), "file_name": files[0].get("file_name"),
                        "language": attrs.get("language"), "downloads": attrs.get("download_count"),
                        "season": feature.get("season_number"),
                        "episode": feature.get("episode_number"), "title": feature.get("title"),
                        "url": attrs.get("url")})
        return sorted(out, key=lambda s: -(s["downloads"] or 0))

    def download(self, file_id: int) -> str:
        data = base.get_json(self._fetch, f"{API}/download", method="POST",
                             json_body={"file_id": int(file_id)}, headers=self.headers,
                             interval=1.0)
        link = (data or {}).get("link")
        if not link:
            raise Unreachable(str((data or {}).get("message") or "no download link"))
        return (self._fetch or base.http_get)(link, interval=1.0)


def _cues(text: str) -> list[dict]:
    import pysubs2

    subs = pysubs2.SSAFile.from_string(text)
    return [{"kind": "dialogue", "speaker": None, "text": " ".join(e.plaintext.split()),
             "start_ms": int(e.start), "end_ms": int(e.end)}
            for e in subs if e.plaintext.strip() and not getattr(e, "is_comment", False)]


def fetch_title(db, series_id: str, *, api_key: str, languages: str = "en",
                season: int | None = None, episode: int | None = None,
                fetch: Fetch | None = None) -> dict:
    """Download the most used subtitles per language for a film or one episode."""
    client = OpenSubtitles(api_key, fetch)
    tmdb = int(series_id.rsplit(":", 1)[-1]) if series_id.startswith("movie:tmdb:") else None
    info = records.get(db, "title_info", series_id) or {}
    tmdb = tmdb or (info.get("external_ids") or {}).get("tmdb_tv")
    found = client.search(query=published_cast.series_title(db, series_id),
                          tmdb_id=int(tmdb) if tmdb else None, languages=languages,
                          season=season, episode=episode)
    saved: list[str] = []
    seen: set[str] = set()
    for item in found:
        if item["language"] in seen or len(saved) >= MAX_DOWNLOADS:
            continue
        try:
            cues = _cues(client.download(item["file_id"]))
        except (Unreachable, LookupError, ValueError):
            continue
        if not cues:
            continue
        seen.add(item["language"])
        saved.append(scripts.save(
            db, series_id, source="opensubtitles", url=item.get("url") or
            f"opensubtitles:{item['file_id']}", lines=cues, kind="subtitles",
            title=item.get("file_name") or "", season=item.get("season") or season,
            episode=item.get("episode") or episode, language=item["language"] or "")["id"])
    return {"found": len(found), "saved": saved}
