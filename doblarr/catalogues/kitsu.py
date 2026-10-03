"""Kitsu: characters with their voices by locale (keyless JSON:API).

Kitsu's dub credits are sparser than ANN's, but it lists a character's
voices per locale (`ja_jp`, `en`, `es`, ...) and its main and supporting
roles. One request per second; answers are cached.
"""

from __future__ import annotations

import re

from . import base
from .base import Fetch

API = "https://kitsu.io/api/edge"
PAGE = "https://kitsu.io/anime/{id}"
_ID = re.compile(r"kitsu\.(?:io|app)/anime/(\d+)", re.IGNORECASE)
_FORMATS = {"TV": "TV", "movie": "MOVIE", "OVA": "OVA", "ONA": "ONA", "special": "SPECIAL"}
_ROLES = {"main": "MAIN", "supporting": "SUPPORTING"}
PAGE_SIZE = 20
MAX_PAGES = 10


def language_of(locale: str) -> str:
    code = str(locale or "").split("_")[0].upper()
    return base.LANGUAGES.get(code, code)


class Kitsu:
    name = "kitsu"
    label = "Kitsu"
    host = "kitsu.io"

    def __init__(self, fetch: Fetch | None = None):
        self._fetch = fetch

    def _json(self, path: str, params: dict | None = None):
        return base.get_json(self._fetch, f"{API}{path}", params=params,
                             headers={"Accept": "application/vnd.api+json"}, interval=1.0)

    def can_handle(self, url: str) -> bool:
        return bool(_ID.search(str(url or "")))

    def _hit(self, item: dict) -> dict:
        attrs = item.get("attributes") or {}
        return base.hit(source=self.name, cid=base.int_or_none(item.get("id")),
                        title=attrs.get("canonicalTitle") or "", url=PAGE.format(id=item.get("id")),
                        titles={k: v for k, v in (attrs.get("titles") or {}).items() if v},
                        year=base.year_of(attrs.get("startDate")),
                        fmt=_FORMATS.get(str(attrs.get("subtype") or ""), attrs.get("subtype")),
                        episodes=attrs.get("episodeCount"))

    def search(self, query: str, *, max_results: int = 8) -> list[dict]:
        query = " ".join(str(query or "").split())
        data = base.cached(f"kitsu:search:{query.casefold()}:{max_results}", lambda: self._json(
            "/anime", {"filter[text]": query, "page[limit]": max(1, min(max_results, 20))}))
        return [self._hit(item) for item in (data or {}).get("data") or []][:max_results]

    def read(self, url: str, *, max_characters: int = 100, fresh: bool = False) -> dict:
        found = _ID.search(str(url or ""))
        if not found:
            raise ValueError(f"{url} is not a Kitsu anime page")
        kid = int(found.group(1))
        info = base.cached(f"kitsu:anime:{kid}", lambda: self._json(f"/anime/{kid}"),
                           fresh=fresh).get("data") or {}
        characters: list[dict] = []
        complete = True
        for page in range(MAX_PAGES):
            params = {"include": "character,voices.person", "page[limit]": PAGE_SIZE,
                      "page[offset]": page * PAGE_SIZE}

            def produce(params: dict = params) -> dict:
                return self._json(f"/anime/{kid}/characters", params)

            data = base.cached(f"kitsu:characters:{kid}:{page}", produce, fresh=fresh)
            included = {(i["type"], i["id"]): i for i in data.get("included") or []}
            for entry in data.get("data") or []:
                rel = entry.get("relationships") or {}
                ref = (rel.get("character") or {}).get("data") or {}
                node = included.get(("characters", ref.get("id")))
                if not node:
                    continue
                attrs = node.get("attributes") or {}
                names = attrs.get("names") or {}
                voices = []
                for v in (rel.get("voices") or {}).get("data") or []:
                    voiced = included.get(("characterVoices", v.get("id"))) or {}
                    person_ref = ((voiced.get("relationships") or {}).get("person") or {}).get(
                        "data") or {}
                    person = included.get(("people", person_ref.get("id"))) or {}
                    name = (person.get("attributes") or {}).get("name")
                    if name:
                        voices.append(base.voice(name, language_of(
                            (voiced.get("attributes") or {}).get("locale") or "")))
                characters.append(base.character(
                    cid=base.int_or_none(node.get("id")),
                    name=attrs.get("canonicalName") or attrs.get("name") or "",
                    native=" ".join(str(names.get("ja_jp") or "").split()),
                    role=_ROLES.get(str((entry.get("attributes") or {}).get("role") or ""), ""),
                    description=attrs.get("description") or "", voice_actors=voices,
                    url=f"https://kitsu.io/characters/{node.get('id')}"))
            if not (data.get("links") or {}).get("next"):
                break
            if len(characters) >= max_characters:
                complete = False
                break
        else:
            complete = False
        summary = self._hit(info) if info else base.hit(source=self.name, cid=kid, title="",
                                                        url=PAGE.format(id=kid))
        return {"source_id": kid, "url": summary["url"], "title": summary["title"],
                "titles": summary["titles"], "format": summary["format"],
                "year": summary["year"], "episodes": summary["episodes"],
                "characters": characters[:max_characters],
                "complete": complete and len(characters) <= max_characters, "staff": []}
