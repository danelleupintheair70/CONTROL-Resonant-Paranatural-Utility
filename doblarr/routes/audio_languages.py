"""Audio track languages across the library (doblarr/audio_languages.py)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import original_language
from ..audio_languages import AudioLanguages
from ..clients.plex import PlexClient, PlexError
from ..config import Config
from ..jobs import Worker
from ..library_service import LibraryService
from ..services import Services


class TrackChange(BaseModel):
    id: str
    language: str = ""
    title: str = ""


class ApplyIn(BaseModel):
    scanned_at: str
    changes: list[TrackChange] = Field(default_factory=list)


def build_router(config: Config, library: LibraryService, services: Services,
                 worker: Worker) -> APIRouter:
    api = APIRouter()

    def originals(item: dict, movie: bool) -> str | None:
        ids = PlexClient.external_ids(item)
        key = original_language.cache_key("movie" if movie else "show",
                                          ids.get("tvdb"), ids.get("tmdb"))
        return original_language.remembered(worker.store.db, key).get("lang") or None

    tracks = AudioLanguages(
        client_of=lambda: services.plex, cache_of=library.plex_cache, originals=originals,
        dry_run_of=lambda: (config.get("dub") or {}).get("dry_run"),
        refresh=lambda key: services.plex.refresh_item(key))

    @api.get("/api/audio-languages")
    def audio_languages(refresh: bool = False):
        try:
            return tracks.scan(force=refresh)
        except PlexError as exc:
            raise HTTPException(502, f"Plex: {exc}") from exc

    @api.post("/api/audio-languages/apply")
    def apply(body: ApplyIn):
        try:
            return tracks.start(body.scanned_at, [c.model_dump() for c in body.changes])
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.get("/api/audio-languages/apply")
    def apply_state():
        return tracks.job

    return api
