"""AniList (anime), read through Prompture's keyless AniList reader.

Every voice language AniList tracks is read, not only Japanese, so a
character's Spanish or English dub actor comes along with the original.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .base import hit

_PAGE = re.compile(r"^https?://(?:www\.)?anilist\.co/(anime|manga)/\d+", re.IGNORECASE)


def _prompture_search(query: str, **kwargs: Any) -> list[dict]:
    try:
        from prompture.tools.web import search_anilist
    except ImportError as exc:  # pragma: no cover - depends on the installed Prompture
        raise RuntimeError("the published cast needs prompture>=1.13.6 (the AniList reader); "
                           "reinstall Doblarr's requirements") from exc
    return search_anilist(query, **kwargs)


def _prompture_read(url: str, **kwargs: Any) -> Any:
    from prompture.tools.web import read_url

    return read_url(url, **kwargs)


class AniList:
    name = "anilist"
    label = "AniList"
    host = "anilist.co"

    def __init__(self, search_fn: Callable[..., list[dict]] | None = None,
                 read_fn: Callable[..., Any] | None = None):
        self._search = search_fn or _prompture_search
        self._read = read_fn or _prompture_read

    def can_handle(self, url: str) -> bool:
        return bool(_PAGE.match(str(url or "")))

    def search(self, query: str, *, max_results: int = 8) -> list[dict]:
        return [hit(source=self.name, cid=h.get("id"), title=h.get("title") or "",
                    url=h.get("url") or "", titles=h.get("titles") or {}, year=h.get("year"),
                    fmt=h.get("format"), episodes=h.get("episodes"))
                for h in self._search(query, max_results=max_results)]

    def read(self, url: str, *, max_characters: int = 100, fresh: bool = False) -> dict:
        result = self._read(url, max_characters=max_characters, use_cache=not fresh,
                            voice_language=None)
        meta = getattr(result, "meta", None) or {}
        if getattr(result, "reader", "") != self.name or not isinstance(meta.get("characters"),
                                                                        list):
            raise ValueError(f"{url} is not an AniList title page")
        return {"source_id": meta.get("id"), "url": meta.get("page_url") or url,
                "title": getattr(result, "title", "") or "", "titles": meta.get("titles") or {},
                "format": meta.get("format"), "year": meta.get("year"),
                "episodes": meta.get("episodes"), "characters": meta["characters"],
                "complete": not meta.get("more_characters"), "staff": []}
