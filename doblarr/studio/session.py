"""The studio session: where you are, how you work, and what an export would do.

A session is keyed by the episode's media, not by a job: a studio exists
before the first draft is rendered, and it outlives every rerun. It records the
view, scene, line, version and playback position so a reload lands where you
were; the working style and its checkpoints; and the direction (reference
policy, locale) the next render will use. It holds no dialogue and no takes —
those stay in the run's review snapshot and decisions sidecar.

Working styles change *when the studio asks you*, never what is stored:

- Automatic runs within budgets and saves a result with its findings visible.
- Guided pauses at the checkpoints you picked: casting, script, export.
- Manual never queues anything you did not ask for.

Switching style keeps every edit, note and selection.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..artifacts import digest
from ..voices import cast_key
from . import records

STYLES = ("automatic", "guided", "manual")
CHECKPOINTS = ("casting", "script", "export")
VIEWS = ("overview", "cast", "dialogue", "compare", "export")


def session_id(path: str) -> str:
    return "st-" + digest(cast_key(path=path))[:12]


class BudgetsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: int = Field(default=0, ge=0, le=5000)      # 0 = counted, uncapped (existing)
    candidates: int = Field(default=2, ge=0, le=4)
    retries: int = Field(default=1, ge=0, le=3)


class DirectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_locale: str = Field(default="", max_length=16)
    reference_policy: Literal["original_only", "reference_suggestions",
                              "follow_edition"] = "original_only"
    reference: str = Field(default="", max_length=64)    # adaptation reference id
    alignment: str = Field(default="", max_length=64)
    slang: bool = False
    adaptation: Literal["natural", "faithful", "localized"] = "natural"
    evaluation: list[str] = Field(default_factory=list, max_length=8)


class SessionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    base_revision: int = Field(ge=1)
    view: Literal["overview", "cast", "dialogue", "compare", "export"] | None = None
    job_id: str | None = Field(default=None, max_length=64)
    cue: str | None = Field(default=None, max_length=64)
    line: int | None = Field(default=None, ge=0)
    version: str | None = Field(default=None, max_length=128)
    position: float | None = Field(default=None, ge=0, le=36000)
    filters: dict | None = None
    compare: dict | None = None
    style: Literal["automatic", "guided", "manual"] | None = None
    checkpoints: list[Literal["casting", "script", "export"]] | None = None
    unresolved: Literal["flag", "block_export"] | None = None
    budgets: BudgetsIn | None = None
    direction: DirectionIn | None = None


def create(db, *, path: str, title: str, job_id: str = "", series_ref: str = "",
           target_locale: str = "") -> dict:
    sid = session_id(path)
    found = records.get(db, "session", sid)
    if found:
        if job_id and found.get("job_id") != job_id:
            return records.update(db, "session", sid, {"job_id": job_id})
        return found
    return records.put(db, "session", sid, {
        "path": path, "title": title, "title_ref": cast_key(path=path),
        "series_ref": series_ref, "job_id": job_id, "view": "overview",
        "line": None, "cue": None, "version": None, "position": 0.0,
        "filters": {}, "compare": {}, "style": "manual", "checkpoints": ["export"],
        "unresolved": "flag", "budgets": BudgetsIn().model_dump(),
        "direction": DirectionIn(target_locale=target_locale).model_dump(),
    }, scope=sid, create_only=True)


def patch(db, sid: str, body: SessionPatch) -> dict:
    changes = body.model_dump(exclude_none=True, exclude={"base_revision"})
    current = records.get(db, "session", sid)
    if current is None:
        raise KeyError(sid)
    return records.put(db, "session", sid, {**current, **changes}, scope=sid,
                       base_revision=body.base_revision)


def overrides(session: dict, reference_file: str = "", holdout_files=()) -> dict:
    """The per-run config a studio direction amounts to — nothing else."""
    direction = session.get("direction") or {}
    budgets = session.get("budgets") or {}
    out = {"translate.adaptation": direction.get("adaptation", "natural"),
           "translate.slang": bool(direction.get("slang")),
           "quality.request_budget": int(budgets.get("requests") or 0),
           "quality.max_retries": int(budgets.get("retries", 1)),
           "dub.candidate_limit": int(budgets.get("candidates", 2))}
    policy = direction.get("reference_policy") or "original_only"
    if policy != "original_only" and reference_file:
        out["translate.reference_policy"] = policy
        out["translate.reference_file"] = reference_file
    if holdout_files:
        out["translate.holdout_files"] = list(holdout_files)
    return out


def next_action(session: dict, state: dict) -> dict:
    """What the studio suggests next, given the style. Never an automatic action."""
    style = session.get("style", "manual")
    checkpoints = set(session.get("checkpoints") or [])
    job = state.get("job") or {}
    if not job:
        if style == "guided" and "casting" in checkpoints and not state.get("cast_decided"):
            return {"action": "audition", "view": "cast",
                    "reason": "casting is a checkpoint: choose voices before the first draft"}
        return {"action": "render", "view": "overview",
                "reason": "no draft yet" + ("; automatic runs within the budgets shown"
                                            if style == "automatic" else "")}
    if job.get("status") in ("queued", "running"):
        return {"action": "wait", "view": "overview", "reason": "a render is in progress"}
    if style == "guided" and "script" in checkpoints and not state.get("script_reviewed"):
        return {"action": "review", "view": "dialogue",
                "reason": "script review is a checkpoint before export"}
    if state.get("stale"):
        return {"action": "rerender", "view": "export",
                "reason": f"{state['stale']} line(s) have audio of older wording"}
    if style != "automatic" or "export" in checkpoints:
        return {"action": "confirm_export", "view": "export",
                "reason": "export waits for your confirmation"}
    return {"action": "done", "view": "export", "reason": "saved; findings are listed"}


def export_plan(snapshot: dict, decisions: dict, pending: dict | None = None) -> dict:
    """What an export would contain, what is stale, what is unresolved — no generation."""
    pending = pending or {}
    rows = []
    stale = 0
    unresolved = []
    for row in snapshot.get("segments") or []:
        cue = row.get("cue") or {}
        audio = cue.get("audio") or {}
        selection = audio.get("selection") or {}
        takes = audio.get("takes") or []
        chosen = next((t for t in takes if t.get("take_id") == selection.get("take_id")),
                      takes[-1] if takes else None)
        wanted = (pending.get(cue.get("cue_id")) or {}).get("text")
        spoken = row.get("tts_text") or row.get("text_translated") or ""
        is_stale = bool(chosen and chosen.get("text") and wanted
                        and wanted.strip() != (row.get("text_translated") or "").strip())
        stale += int(is_stale)
        for finding in cue.get("findings") or []:
            verdict = ((decisions.get("cues") or {}).get(cue.get("cue_id")) or {}).get(
                "dispositions", {}).get(finding.get("finding_id"))
            state = (verdict or {}).get("disposition") or finding.get("disposition")
            if state == "open" and finding.get("severity") in ("warning", "error"):
                unresolved.append({"cue": cue.get("cue_id"), "line": row.get("index"),
                                   "code": finding.get("code"),
                                   "severity": finding.get("severity")})
        rows.append({"index": row.get("index"), "cue": cue.get("cue_id"),
                     "speaker": row.get("speaker"), "text": wanted or row.get("text_translated"),
                     "spoken": spoken, "take": (chosen or {}).get("take_id"),
                     "selection": selection.get("reason"), "stale": is_stale,
                     "start": row.get("start"), "end": row.get("end")})
    return {"lines": rows, "stale": stale, "unresolved": unresolved,
            "timing_edits": len(snapshot.get("timing_edits") or {}),
            "manual_gains": len(snapshot.get("manual_gains") or {}),
            "note": ("Export uses the selected take of every line. A line whose wording "
                     "changed after its take was made is stale and is never exported as if "
                     "it said the new words.")}
