"""Bangumi (bgm.tv): Chinese-language catalogue with native-script names.

Keyless; Bangumi asks for an identifying User-Agent. Characters carry their
role (main, supporting, guest) and the actors credited, usually the original
cast; Bangumi does not say which language an actor voiced, so none is stated.
"""

from __future__ import annotations

import re

from . import base
from .base import Fetch

API = "https://api.bgm.tv/v0"
PAGE = "https://bgm.tv/subject/{id}"
_ID = re.compile(r"(?:bgm|bangumi)\.tv/subject/(\d+)", re.IGNORECASE)
_ROLES = {"主角": "MAIN", "配角": "SUPPORTING", "客串": "BACKGROUND"}
_FORMATS = {"TV": "TV", "剧场版": "MOVIE", "OVA": "OVA", "WEB": "ONA"}
ANIME = 2


class Bangumi:
    name = "bangumi"
    label = "Bangumi"
    host = "bgm.tv"

    def __init__(self, fetch: Fetch | None = None):
        self._fetch = fetch

    def can_handle(self, url: str) -> bool:
        return bool(_ID.search(str(url or "")))

    def search(self, query: str, *, max_results: int = 8) -> list[dict]:
        query = " ".join(str(query or "").split())
        data = base.cached(
            f"bangumi:search:{query.casefold()}:{max_results}",
            lambda: base.get_json(self._fetch, f"{API}/search/subjects", method="POST",
                                  params={"limit": max(1, min(max_results, 20))},
                                  json_body={"keyword": query, "filter": {"type": [ANIME]}},
                                  interval=1.0))
        return [self._hit(s) for s in (data or {}).get("data") or []][:max_results]

    def _hit(self, subject: dict) -> dict:
        titles = {"native": subject.get("name") or ""}
        if subject.get("name_cn"):
            titles["chinese"] = subject["name_cn"]
        return base.hit(source=self.name, cid=subject.get("id"),
                        title=subject.get("name_cn") or subject.get("name") or "",
                        url=PAGE.format(id=subject.get("id")), titles=titles,
                        year=base.year_of(subject.get("date")),
                        fmt=_FORMATS.get(str(subject.get("platform") or ""),
                                         subject.get("platform")),
                        episodes=subject.get("eps") or subject.get("total_episodes"))

    def read(self, url: str, *, max_characters: int = 100, fresh: bool = False) -> dict:
        found = _ID.search(str(url or ""))
        if not found:
            raise ValueError(f"{url} is not a Bangumi subject page")
        sid = int(found.group(1))
        subject = base.cached(f"bangumi:subject:{sid}", lambda: base.get_json(
            self._fetch, f"{API}/subjects/{sid}", interval=1.0), fresh=fresh) or {}
        people = base.cached(f"bangumi:characters:{sid}", lambda: base.get_json(
            self._fetch, f"{API}/subjects/{sid}/characters", interval=1.0), fresh=fresh) or []
        characters = [base.character(
            cid=p.get("id"), name=p.get("name") or "", native=p.get("name") or "",
            role=_ROLES.get(p.get("relation") or "", ""),
            voice_actors=[base.voice(a.get("name") or "", "", a.get("name") or "")
                          for a in p.get("actors") or [] if a.get("name")],
            url=f"https://bgm.tv/character/{p.get('id')}")
            for p in people if p.get("name")]
        summary = self._hit(subject) if subject else base.hit(source=self.name, cid=sid,
                                                              title="", url=PAGE.format(id=sid))
        return {"source_id": sid, "url": summary["url"], "title": summary["title"],
                "titles": summary["titles"], "format": summary["format"],
                "year": summary["year"], "episodes": summary["episodes"],
                "characters": characters[:max_characters],
                "complete": len(characters) <= max_characters, "staff": []}
