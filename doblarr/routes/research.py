"""Title research over HTTP (doblarr.research).

A question is queued as a job, since it costs provider calls and takes a
minute; its run is kept and listed by series. Every route that sends anything
out of the machine is refused while `research.enabled` is off. Cast leads
and found scripts wait for a person here; nothing is applied on its own.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..research import agent
from ..studio import records
from .cast import research_allowed


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str = Field(min_length=3, max_length=120)
    question: str = Field(min_length=3, max_length=agent.MAX_QUESTION)
    target_locale: str = Field(default="", max_length=16)


class LeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=4, max_length=64)
    index: int = Field(ge=0, le=500)
    decision: Literal["accept", "dismiss"]
    reviewer: str = Field(default="you", min_length=1, max_length=80)


def build_router(config, store, bus) -> APIRouter:
    api = APIRouter()
    db = store.db

    @api.post("/api/research")
    def ask(body: AskIn):
        """Queue one question about a title. Only the question (and title) leave."""
        research_allowed(config)
        if not records.get(db, "series", body.series_id):
            raise HTTPException(404, "unknown series")
        try:
            model = agent.resolve_model(config)
            sent = agent.compose_query(db, body.series_id, body.question)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        job = store.add(title=f"Research · {body.question[:60]}", source="research",
                        source_lang="und", target_lang="und", kind="studio_research",
                        task={"series_id": body.series_id, "question": body.question,
                              "target_locale": body.target_locale})
        bus.publish("job", {"type": "queued", "job_id": job.id, "title": job.title})
        return {"job_id": job.id, "model": model, "sent": sent}

    @api.get("/api/research/runs")
    def runs(series_id: str):
        return {"series_id": series_id, "runs": [
            {k: r.get(k) for k in ("id", "question", "model", "depth", "cost", "elapsed_s",
                                   "created_at", "synthesis")}
            | {"sources": len(r.get("sources") or []),
               "terms": len(r.get("terms") or []),
               "open_leads": sum(1 for lead in r.get("leads") or []
                                 if lead.get("state") == "open")}
            for r in agent.runs(db, series_id)]}

    @api.get("/api/research/runs/{run_id}")
    def run(run_id: str):
        found = records.get(db, agent.KIND, run_id)
        if found is None:
            raise HTTPException(404, "no such research run")
        return found

    @api.post("/api/research/leads")
    def lead(body: LeadIn):
        """A person accepts a cast lead (it joins the series' research cast) or dismisses it."""
        try:
            act = agent.accept_lead if body.decision == "accept" else agent.dismiss_lead
            saved = act(db, body.run_id, body.index, reviewer=body.reviewer)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip("'\"")) from exc
        except records.StudioConflict as exc:
            raise HTTPException(409, {"error": str(exc), "current": exc.current}) from exc
        return {"leads": saved["leads"]}

    return api
