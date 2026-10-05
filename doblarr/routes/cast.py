"""The published cast of a series over HTTP (doblarr.published_cast).

Under /api/published-cast (/api/cast is the voice cast), with the same
actions as `doblarr cast`. Searching sends a title to a public catalogue, so
it only runs when `research.enabled` is on and a person asks; reading what
was already linked never leaves the machine. Linking and
importing are a person's choices; nothing here runs on its own.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .. import catalogues, published_cast
from ..studio import records


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str = Field(min_length=3, max_length=120)
    url: str = Field(min_length=8, max_length=500)
    season: int | None = Field(default=None, ge=0, le=999)
    source: str | None = Field(default=None, max_length=40)
    why: str = Field(default="", max_length=400)


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str = Field(min_length=3, max_length=120)
    season: int | None = Field(default=None, ge=0, le=999)
    roles: list[str] = Field(default_factory=lambda: ["MAIN"], max_length=3)
    names: list[str] | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=40)


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str = Field(min_length=3, max_length=120)
    season: int | None = Field(default=None, ge=0, le=999)
    source: str | None = Field(default=None, max_length=40)


def research_allowed(config) -> None:
    if not (config.get("research") or {}).get("enabled"):
        raise HTTPException(403, "title research is off; turn it on under Settings → Research")


def build_router(config, db) -> APIRouter:
    api = APIRouter()
    catalogues.configure_from(config)

    def failed(exc: Exception) -> HTTPException:
        if isinstance(exc, catalogues.Unreachable):
            return HTTPException(503, str(exc))
        if isinstance(exc, KeyError):
            return HTTPException(404, str(exc).strip("'\""))
        return HTTPException(422, str(exc))

    @api.get("/api/published-cast/catalogues")
    def list_catalogues():
        return {"catalogues": [{"name": p.name, "label": p.label, "host": p.host}
                               for p in catalogues.PROVIDERS.values()],
                "enabled": bool((config.get("research") or {}).get("enabled"))}

    @api.get("/api/published-cast/series")
    def series():
        out = []
        for found in records.list_latest(db, "series"):
            if found.get("linked_to"):
                continue
            out.append({"id": found["id"], "title": published_cast.series_title(db, found["id"]),
                        "sources": published_cast.sources(db, found["id"])})
        return {"series": out}

    @api.get("/api/published-cast")
    def show(series_id: str, season: int | None = None, episode: int | None = None):
        """The merged cast and each source's record. Nothing is fetched."""
        merged = published_cast.merged_cast(db, series_id, season=season)
        primary = published_cast.get(db, series_id, season=season)
        return {**merged, "title": published_cast.series_title(db, series_id),
                "candidates": [c["name"] for c in
                               published_cast.candidates(primary, episode=episode)]
                if primary and episode is not None else None,
                "links": [{"id": r["id"], "source": published_cast.source_of(r),
                           "season": r.get("season"), "title": r.get("title"),
                           "url": r.get("url"), "complete": r.get("complete"),
                           "fetched_at": r.get("fetched_at"), "why": r.get("why") or "",
                           "characters": len(r.get("characters") or [])}
                          for r in published_cast.links(db, series_id)]}

    @api.get("/api/published-cast/search")
    def search(series_id: str, query: str = "", source: str = "anilist"):
        """Catalogue entries for a title. Sends the title out; stores nothing."""
        research_allowed(config)
        query = query or published_cast.series_title(db, series_id)
        if not query:
            raise HTTPException(422, "no title known for this series; type one")
        names = list(catalogues.PROVIDERS) if source == "all" else [source]
        try:
            hosts = [catalogues.provider(n).host for n in names]
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        kind = "movie" if series_id.startswith("movie:") else "show"
        found = published_cast.search_all(query, kind=kind, sources=names,
                                          max_results=8 if len(names) == 1 else 5)
        return {"query": query, "sent_to": hosts, **found}

    @api.get("/api/published-cast/suggest")
    def suggest(series_id: str, source: str, season: int | None = None):
        """Entries of another catalogue matching the linked title, with why."""
        research_allowed(config)
        try:
            return {"source": source, "hits": published_cast.suggest_links(
                db, series_id, source, season=season)}
        except (KeyError, ValueError, LookupError, catalogues.Unreachable) as exc:
            raise failed(exc) from exc

    @api.post("/api/published-cast/link")
    def link(body: LinkIn):
        research_allowed(config)
        try:
            saved = published_cast.link(db, body.series_id, body.url, season=body.season,
                                        source=body.source, why=body.why)
        except (KeyError, ValueError, LookupError, RuntimeError) as exc:
            raise failed(exc) from exc
        return {"id": saved["id"], "source": saved["source"], "title": saved["title"],
                "characters": len(saved["characters"]), "complete": saved["complete"]}

    @api.post("/api/published-cast/refresh")
    def refresh(body: RefreshIn):
        research_allowed(config)
        try:
            saved = published_cast.refresh(db, body.series_id, season=body.season,
                                           source=body.source)
        except (KeyError, ValueError, LookupError, RuntimeError) as exc:
            raise failed(exc) from exc
        return {"id": saved["id"], "characters": len(saved["characters"])}

    @api.post("/api/published-cast/import")
    def import_cast(body: ImportIn):
        """Create or annotate series characters from the linked cast (never renames)."""
        try:
            return published_cast.import_characters(db, body.series_id, season=body.season,
                                                    roles=body.roles, names=body.names,
                                                    source=body.source)
        except KeyError as exc:
            raise failed(exc) from exc

    return api
