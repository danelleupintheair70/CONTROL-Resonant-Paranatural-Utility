"""Narrative knowledge of a series: extract, review, activate (doblarr.knowledge.narrative).

Extraction is queued (it costs provider calls) and lands as a draft. Review
writes overlays on exact proposals. Activation is its own explicit action and
creates an immutable revision; jobs already queued keep the revision they froze.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .. import identity
from ..knowledge import narrative
from ..knowledge import title_drafts as drafts
from ..studio import records


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=64, max_length=64)
    candidate_id: str = Field(min_length=64, max_length=64)
    decision: Literal["accept", "edit", "reject", "defer"]
    correction: str | None = Field(default=None, max_length=400)
    note: str = Field(default="", max_length=500)
    reviewer: str = Field(default="you", min_length=1, max_length=80)
    expected_revision: int = Field(ge=0)


class ActivateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str = Field(min_length=3, max_length=120)
    base_revision: int = Field(ge=0)
    boundaries: dict[str, list[int]] = Field(default_factory=dict)
    retire: list[str] = Field(default_factory=list, max_length=500)
    reviewer: str = Field(default="you", min_length=1, max_length=80)


class ExtractIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)
    model: str = Field(default="", max_length=120)
    target_lang: str = Field(default="es", max_length=16)


class ExternalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str = Field(min_length=3, max_length=120)
    media_id: str = Field(min_length=3, max_length=120)
    text: str = Field(min_length=1, max_length=2000)
    source: str = Field(min_length=1, max_length=120)
    fetched_at: str = Field(min_length=4, max_length=40)
    sources: list[str] = Field(default_factory=list, max_length=20)


def build_router(config, store) -> APIRouter:
    api = APIRouter()
    db = store.db

    @api.get("/api/narrative")
    def overview(series_id: str):
        current = narrative.active(db, series_id)
        claims = (current or {}).get("claims") or {}
        externals = [r for r in records.list_latest(db, "claim", scope=series_id)
                     if r.get("origin") == "external"]
        return {"series_id": series_id, "coverage": narrative.coverage(db, series_id),
                "revision": current["revision"] if current else 0,
                "claims": [{"id": k, **v} for k, v in claims.items()],
                "conflicted": sorted(k for k, v in claims.items() if v.get("conflicted")),
                "retired": [{"id": k, **v} for k, v in ((current or {}).get("retired")
                                                         or {}).items()],
                "external": externals,
                "characters": {c["id"]: c["name"] for c in
                               identity.characters(db, series_id, include_retired=True)}}

    @api.get("/api/narrative/draft/{draft_id}")
    def draft(draft_id: str):
        try:
            revision, found = drafts.load_draft(db, draft_id)
        except KeyError as exc:
            raise HTTPException(404, "no such draft") from exc
        cues = {found.cue_id(c.ordinal): {"ordinal": c.ordinal, "start_ms": c.start_ms,
                                          "end_ms": c.end_ms, "text": c.text,
                                          "cue_id": c.original_label}
                for c in found.cues}
        rows = drafts.review_view(db, draft_id)
        revisions = {r.candidate_id: rev for rev, r in drafts.review_history(db, draft_id)}
        for row in rows:
            row["evidence"] = [cues.get(e) for e in row["proposal"].get("evidence") or []
                               if e in cues]
            row["review_revision"] = revisions.get(row["candidate_id"], 0)
        return {"draft_id": draft_id, "revision": revision, "state": found.state,
                "media_id": found.source.title_ref, "series_id": found.source.series_ref,
                "model": f"{found.analysis.provider}/{found.analysis.model}",
                "candidates": rows}

    @api.post("/api/narrative/review")
    def review(body: ReviewIn):
        try:
            revision = narrative.review(db, body.draft_id, body.candidate_id, body.decision,
                                        body.reviewer, note=body.note,
                                        correction=body.correction if body.decision == "edit"
                                        else None,
                                        expected_revision=body.expected_revision)
        except KeyError as exc:
            raise HTTPException(404, "no such candidate") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"review_revision": revision}

    @api.post("/api/narrative/activate")
    def activate(body: ActivateIn):
        try:
            saved = narrative.activate(db, body.series_id, reviewer=body.reviewer,
                                       base_revision=body.base_revision,
                                       boundaries=body.boundaries, retire=body.retire)
        except records.StudioConflict as exc:
            raise HTTPException(409, {"error": str(exc), "current": exc.current}) from exc
        return {"revision": saved["revision"], "claims": len(saved["claims"]),
                "note": "Jobs already queued keep the revision they froze; new jobs read "
                        "this one."}

    @api.get("/api/narrative/context")
    def context(path: str):
        """What a new job on this file would read now (nothing is generated)."""
        if not Path(path).is_file():
            raise HTTPException(404, "the file is not reachable from here")
        found = identity.resolve(db, Path(path), cache_dir=Path(config.work_dir) / "cache")
        frozen = narrative.pin(db, found["series_id"])
        from ..speaker_memory import held_out_revisions

        claims = narrative.select(db, frozen, media_id=found["media_id"],
                                  held_out=held_out_revisions(db))
        return {"identity": found, "pin": frozen, "claims": claims,
                "context": narrative.context(claims, db)}

    @api.post("/api/narrative/extract")
    def extract(body: ExtractIn):
        """Queue an extraction for one analysed episode (provider calls)."""
        if not Path(body.path).is_file():
            raise HTTPException(404, "the episode's file is not reachable from here")
        model = body.model or str((config.get("analysis") or {}).get("knowledge_model") or "")
        if not model:
            raise HTTPException(422, "choose a model for knowledge extraction "
                                "(analysis.knowledge_model)")
        from ..languages import base_language
        from ..speaking import locate_script

        # Reuse the analysed run (same input path and language), so only the
        # knowledge stage does work.
        script, _how = locate_script(config.work_dir, body.path)
        recorded: dict = {}
        if script is not None:
            import json as _json

            recorded = _json.loads(script.read_text(encoding="utf-8")).get("identity") or {}
        source = str(recorded.get("input") or "")
        input_file = source if source and Path(source).is_file() else body.path
        # The earlier run's target too: another target reads other subtitles
        # and would cut and group the lines again.
        folder = script.parent.name if script is not None else ""
        target = str(recorded.get("target_lang") or base_language(body.target_lang) or "es")
        job = store.add(title=f"Knowledge · {Path(body.path).name}", source="analysis",
                        source_lang=str(recorded.get("source_lang") or "auto"),
                        target_lang=target,
                        target_locale=folder if folder.split("-")[0] == target and "-" in folder
                        else "",
                        input_file=input_file, kind="analyze", overrides={
                            "analysis.stages": ["knowledge"], "analysis.knowledge": True,
                            "analysis.knowledge_model": model})
        return {"job_id": job.id, "model": model}

    @api.post("/api/narrative/external")
    def external(body: ExternalIn):
        return narrative.add_external(db, body.series_id, body.media_id, body.text,
                                      source=body.source, fetched_at=body.fetched_at,
                                      sources=body.sources)

    return api
