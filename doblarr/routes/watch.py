"""Watch a finished dub in the browser, switch languages, and leave notes.

Notes are timestamped observations about the dub ("the laugh is lost here",
"two voices overlap"), kept as annotation records scoped to the job, so what
a person hears while watching is stored with the dub and not in a chat.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import watch
from ..studio import records
from .media_delivery import allowed_path, ranged_response


class WatchNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    at: float = Field(ge=0, le=36000)
    end: float | None = Field(default=None, ge=0, le=36000)
    track: str = Field(default="", max_length=120)          # what was playing
    category: Literal["", "lost sound", "overlap", "timing", "voice", "translation",
                      "level", "other"] = ""
    severity: Literal["minor", "noticeable", "major"] = "noticeable"
    in_original: Literal["", "yes", "no", "not sure"] = ""
    note: str = Field(default="", max_length=2000)


class WatchNotePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Literal["open", "fixed", "won't fix"]
    base_revision: int | None = None


def build_router(config, store) -> APIRouter:
    api = APIRouter()
    db = store.db

    def output_of(job_id: str):
        job = store.get(job_id)
        if job is None or not job.output_file:
            raise HTTPException(404, "This job has no finished dub to watch")
        path = allowed_path(config, str(job.output_file))
        if path is None:
            raise HTTPException(403, "The dub is outside the configured folders")
        if not path.is_file():
            raise HTTPException(404, "The dub's file is no longer on disk")
        return job, path

    def scope(job_id: str) -> str:
        return f"job:{job_id}"

    def pick(audio: list[dict], job) -> tuple[dict | None, dict | None]:
        """Ours (the track the dub added, the last one) and the original to
        compare it with (the default track, else the source language's)."""
        ours = audio[-1] if audio else None
        rest = [a for a in audio if a is not ours]
        original = next((a for a in rest if a["default"]), None) or next(
            (a for a in rest if a["lang"] == (job.source_lang or "")), None) or (
            rest[0] if rest else None)
        return ours, original

    @api.get("/api/watch/{job_id}")
    def watch_info(job_id: str, retry: bool = False):
        job, path = output_of(job_id)
        found = watch.streams(path)
        ours, original = pick(found["audio"], job)
        where = watch.folder(Path(config.work_dir) / "cache", path)
        if retry:
            watch.retry(where)
        state = watch.ensure(path, where, original["stream"] if original else None,
                             ours["stream"] if ours else None)
        loud = where / "loudness.json"
        loudness = None
        if loud.is_file():
            import json

            data = json.loads(loud.read_text(encoding="utf-8"))
            loudness = {k: data.get(k) for k in ("window", "offset_db", "spans", "curves")}
        notes = sorted(records.list_latest(db, "annotation", scope(job_id)),
                       key=lambda n: n.get("at") or 0)
        review = allowed_path(config, str(job.review_file)) if job.review_file else None
        return {
            "job": {"id": job.id, "title": job.title, "status": job.status,
                    "source": job.source_lang, "target": job.target_locale or job.target_lang,
                    "version": job.version_name, "kind": job.kind,
                    "input": Path(str(job.input_file)).name if job.input_file else "",
                    # The studio opens by file, as from the jobs list.
                    "input_file": str(job.input_file) if job.input_file else "",
                    "output": path.name,
                    "has_review": bool(review and review.is_file())},
            "state": state,
            "tracks": [{**a, "ours": a is ours, "original": a is original}
                       for a in found["audio"]],
            "subtitles": found["subtitles"],
            "loudness": loudness,
            "notes": notes,
        }

    @api.get("/api/watch/{job_id}/audio/{stream}.mp4")
    def watch_audio(job_id: str, stream: int, request: Request):
        _job, path = output_of(job_id)
        where = watch.folder(Path(config.work_dir) / "cache", path)
        if not (where / "video.mp4").is_file():
            raise HTTPException(409, "The watch copy is still being made")
        track = next((a for a in watch.streams(path)["audio"] if a["stream"] == stream), None)
        if track is None:
            raise HTTPException(404, "No such audio track in this dub")
        try:
            file = watch.language(path, where, stream, track.get("codec"))
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc
        return ranged_response(file, request.headers.get("range"))

    @api.get("/api/watch/{job_id}/subtitles/{stream}.vtt")
    def watch_subtitles(job_id: str, stream: int):
        _job, path = output_of(job_id)
        if stream not in {s["stream"] for s in watch.streams(path)["subtitles"]}:
            raise HTTPException(404, "No such subtitle track in this dub")
        where = watch.folder(Path(config.work_dir) / "cache", path)
        try:
            return FileResponse(watch.subtitles(path, where, stream), media_type="text/vtt")
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc

    @api.post("/api/watch/{job_id}/notes")
    def add_note(job_id: str, body: WatchNoteIn):
        job, _path = output_of(job_id)
        nid = "note-" + records.digest_id(job_id, body.model_dump(), records.now_marker())
        saved = records.put(db, "annotation", nid, {
            **body.model_dump(), "job_id": job_id, "source": body.track,
            "domain": "target", "input": str(job.input_file or ""),
            "resolution": "open", "history": []}, scope=scope(job_id), create_only=True)
        return {"note": saved}

    @api.patch("/api/watch/{job_id}/notes/{nid}")
    def patch_note(job_id: str, nid: str, body: WatchNotePatch):
        current = records.get(db, "annotation", nid)
        if current is None or current.get("scope") != scope(job_id):
            raise HTTPException(404, "No such note on this dub")
        history = list(current.get("history") or []) + [
            {"at": records.now_marker(), "resolution": body.resolution}]
        try:
            return {"note": records.put(db, "annotation", nid, {
                **current, "resolution": body.resolution, "history": history[-50:]},
                base_revision=body.base_revision)}
        except (records.StudioConflict, records.FrozenRecord) as exc:
            raise HTTPException(409, str(exc)) from exc

    return api
