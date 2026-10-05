"""MyAnimeList through Jikan: characters with their voices in every language.

Jikan (api.jikan.moe) is a keyless mirror of MyAnimeList. Each character lists
its voice actors with a language (Japanese, English, Spanish, ...). The
public instance allows about sixty requests a minute and is not always
reachable; when it is not, the provider is skipped like any other.
"""

from __future__ import annotations

import re

from . import base
from .base import Fetch

API = "https://api.jikan.moe/v4"
_ID = re.compile(r"myanimelist\.net/anime/(\d+)", re.IGNORECASE)
_ROLES = {"main": "MAIN", "supporting": "SUPPORTING"}


def given_first(name: str) -> str:
    """MyAnimeList writes "Family, Given"; the cast stores "Given Family"."""
    family, sep, given = str(name or "").partition(",")
    return f"{given.strip()} {family.strip()}".strip() if sep else str(name or "").strip()


class Jikan:
    name = "jikan"
    label = "MyAnimeList (Jikan)"
    host = "api.jikan.moe"

    def __init__(self, fetch: Fetch | None = None):
        self._fetch = fetch

    def _json(self, path: str, params: dict | None = None):
        return base.get_json(self._fetch, f"{API}{path}", params=params, interval=1.1)

    def can_handle(self, url: str) -> bool:
        return bool(_ID.search(str(url or "")))

    def search(self, query: str, *, max_results: int = 8) -> list[dict]:
        query = " ".join(str(query or "").split())
        data = base.cached(f"jikan:search:{query.casefold()}:{max_results}", lambda: self._json(
            "/anime", {"q": query, "limit": max(1, min(max_results, 25))}))
        out = []
        for item in (data or {}).get("data") or []:
            titles = {t.get("type", "").lower(): t.get("title") for t in item.get("titles") or []
                      if t.get("title")}
            out.append(base.hit(source=self.name, cid=item.get("mal_id"),
                                title=item.get("title") or "", url=item.get("url") or "",
                                titles=titles, year=item.get("year"),
                                fmt=str(item.get("type") or "").upper() or None,
                                episodes=item.get("episodes")))
        return out

    def read(self, url: str, *, max_characters: int = 100, fresh: bool = False) -> dict:
        found = _ID.search(str(url or ""))
        if not found:
            raise ValueError(f"{url} is not a MyAnimeList anime page")
        mal = int(found.group(1))
        info = base.cached(f"jikan:anime:{mal}", lambda: self._json(f"/anime/{mal}"),
                           fresh=fresh).get("data") or {}
        people = base.cached(f"jikan:characters:{mal}",
                             lambda: self._json(f"/anime/{mal}/characters"),
                             fresh=fresh).get("data") or []
        staff = base.cached(f"jikan:staff:{mal}", lambda: self._json(f"/anime/{mal}/staff"),
                            fresh=fresh).get("data") or []
        characters = []
        for entry in people:
            node = entry.get("character") or {}
            if not node.get("name"):
                continue
            voices = [base.voice(given_first((v.get("person") or {}).get("name") or ""),
                                 v.get("language") or "")
                      for v in entry.get("voice_actors") or [] if v.get("person")]
            characters.append(base.character(
                cid=node.get("mal_id"), name=given_first(node["name"]),
                alternative=[node["name"]] if "," in node["name"] else [],
                role=_ROLES.get(str(entry.get("role") or "").lower(), "BACKGROUND"),
                voice_actors=voices, url=node.get("url")))
        order = {"MAIN": 0, "SUPPORTING": 1, "BACKGROUND": 2}
        characters.sort(key=lambda c: order.get(c["role"], 3))
        return {"source_id": mal, "url": info.get("url") or url,
                "title": info.get("title") or "",
                "titles": {t.get("type", "").lower(): t.get("title")
                           for t in info.get("titles") or [] if t.get("title")},
                "format": str(info.get("type") or "").upper() or None, "year": info.get("year"),
                "episodes": info.get("episodes"),
                "characters": characters[:max_characters],
                "complete": len(characters) <= max_characters,
                "staff": [{"task": ", ".join(s.get("positions") or []),
                           "name": given_first((s.get("person") or {}).get("name") or "")}
                          for s in staff if s.get("person")]}
