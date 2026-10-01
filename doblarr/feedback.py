"""Verdicts on exact renders, approved examples, and the held-out set.

A verdict is about one exact thing: a job, a cue, the decision record it came
from and the rendered artifact's fingerprint. It says accept / reject /
correct, and *why* (identity, source evidence, acting, timing, level,
background or envelope), and who said it.

Only an accepted (or corrected) verdict can become an **example** for
retrieval (doblarr.retrieval), and only when a person approves it as one. An
example's id is derived from what it is about (revision, cue, template), so
importing or resuming twice never counts it twice; a correction supersedes the
earlier version of the same example; retiring an example removes it from new
retrieval without touching the decisions that already used it (those stay
reproducible from their frozen records). Rejected verdicts may be kept as
explicitly labelled negative evidence; they never vote for a template.

A **held-out** revision is excluded from examples, retrieval, speaker memory
and narrative context. Taking a revision out of the held-out set is recorded,
so an evaluation can tell which cases were ever seen.

Nothing here learns on its own: there is no online training and nothing a
model produced is approved without a person.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import features, identity, templates
from .artifacts import digest
from .studio import records

PROBLEMS = ("identity", "source_evidence", "acting", "timing", "level", "background",
            "envelope", "other")


class VerdictIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=64)
    cue: str = Field(min_length=1, max_length=64)
    revision_id: str = Field(default="", max_length=64)
    artifact: str = Field(default="", max_length=64)          # rendered fingerprint
    decision: str = Field(default="", max_length=64)          # recommendation record
    template: dict = Field(default_factory=dict)              # the pin that was rendered
    params: dict = Field(default_factory=dict)
    verdict: Literal["accept", "reject", "correct"]
    problems: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(default="", max_length=500)
    correction: dict = Field(default_factory=dict)            # {template, strength}
    reviewer: str = Field(default="you", min_length=1, max_length=80)


def verdict_id(body: VerdictIn) -> str:
    return "fb-" + digest([body.job_id, body.cue, body.artifact, body.reviewer])[:16]


def record_verdict(db, body: VerdictIn) -> dict:
    unknown = [p for p in body.problems if p not in PROBLEMS]
    if unknown:
        raise ValueError(f"unknown problem kind(s): {', '.join(unknown)}")
    if body.verdict == "correct" and not body.correction.get("template"):
        raise ValueError("a correction names the template that should have been used")
    record_id = verdict_id(body)
    current = records.get(db, "feedback", record_id)
    return records.put(db, "feedback", record_id, {**body.model_dump(),
                                                  "at": records.now_marker()},
                       scope=body.revision_id or body.job_id,
                       base_revision=current["revision"] if current else 0)


def example_id(revision_id: str, cue: str) -> str:
    return "ex-" + digest([revision_id, cue])[:16]


def approve_example(db, verdict: dict, *, source_curve: list[float], take_curve: list[float],
                    target_lang: str, series_id: str = "", scope: str = "series",
                    approved_by: str = "you") -> dict:
    """Make an accepted/corrected verdict retrievable. One example per line:
    approving again (or a correction) supersedes it; it never duplicates."""
    if verdict.get("verdict") not in ("accept", "correct"):
        raise ValueError("only an accepted or corrected verdict can become an example")
    revision_id = verdict.get("revision_id") or ""
    if revision_id in held_out(db):
        raise ValueError("this revision is held out for evaluation; promote it first")
    template = (verdict.get("correction") or {}).get("template") or \
        (verdict.get("template") or {}).get("id")
    strength = (verdict.get("correction") or {}).get("strength",
                                                      (verdict.get("params") or {}).get(
                                                          "strength"))
    order = None
    if revision_id:
        media = identity.find_media_by_content(db, revision_id.removeprefix("rev-"))
        order = identity.episode_order(db, media["id"]) if media else None
    record_id = example_id(revision_id, verdict["cue"])
    current = records.get(db, "example", record_id)
    return records.put(db, "example", record_id, {
        "revision_id": revision_id, "cue": verdict["cue"], "series_id": series_id,
        "scope": scope, "order": list(order) if order else None,
        "target_lang": target_lang, "template": template,
        "params": {"strength": strength} if strength is not None else {},
        "source_curve": list(source_curve)[:64], "take_curve": list(take_curve)[:64],
        "features_version": features.FEATURES, "catalogue": templates.CATALOGUE,
        "feedback": verdict.get("id"), "approved_by": approved_by, "retired": False,
        "holdout": False, "at": records.now_marker()},
        scope=series_id or "global", base_revision=current["revision"] if current else 0)


def examples(db, series_id: str | None = None, *, include_retired: bool = False) -> list[dict]:
    rows = records.list_latest(db, "example")
    out = []
    for row in rows:
        if row["id"].startswith("holdout-") or not row.get("template"):
            continue
        if row.get("retired") and not include_retired:
            continue
        if series_id and row.get("series_id") not in (series_id, "") and \
                row.get("scope") != "global":
            continue
        out.append(row)
    return out


def retire_example(db, record_id: str, *, base_revision: int | None,
                   retired: bool = True) -> dict:
    current = records.get(db, "example", record_id)
    if current is None:
        raise KeyError(record_id)
    return records.update(db, "example", record_id, {"retired": retired,
                                                     "retired_at": records.now_marker()},
                          base_revision=base_revision)


def hold_out(db, revision_id: str, *, held: bool = True, note: str = "") -> dict:
    """Put a revision in (or take it out of) the held-out evaluation set.

    Taking one out is kept in its history: an evaluation can always tell
    whether a case was ever available to retrieval.
    """
    record_id = "holdout-" + digest(revision_id)[:16]
    current = records.get(db, "example", record_id)
    return records.put(db, "example", record_id, {
        "revision_id": revision_id, "holdout": held, "note": note[:300],
        "was_held_out": bool(current) or held, "at": records.now_marker()},
        base_revision=current["revision"] if current else 0)


def held_out(db) -> set[str]:
    return {r["revision_id"] for r in records.list_latest(db, "example")
            if r["id"].startswith("holdout-") and r.get("holdout")}


def dependents(db, example: str) -> list[dict]:
    """Recommendation records that used an example (for "what would change")."""
    out = []
    for row in records.list_latest(db, "decision"):
        used = row.get("examples_used") or {}
        cues = [cue for cue, ids in used.items() if example in ids]
        if cues:
            out.append({"decision": row["id"], "job": row.get("job_id"), "cues": cues})
    return out


def export_guidance(db, *, template_ids: list[str], series_id: str | None = None) -> dict:
    """Approved guidance that may travel: templates, character template
    preferences and delivery direction, and approved examples' curves.
    Never media, paths, voice vectors, private verdicts or reviewers."""
    from . import profiles

    bundle_templates = templates.export(db, template_ids)["templates"] if template_ids else []
    characters = []
    if series_id:
        for character in identity.characters(db, series_id):
            profile = profiles.get(db, character["id"])
            characters.append({"name": character["name"],
                               "aliases": character.get("aliases") or [],
                               "templates": profile["templates"],
                               "direction": profile["delivery"].get("direction") or ""})
    shared = [{"template": e["template"], "params": e.get("params") or {},
               "source_curve": e.get("source_curve") or [],
               "take_curve": e.get("take_curve") or [], "target_lang": e.get("target_lang"),
               "features_version": e.get("features_version")}
              for e in examples(db, series_id) if not e.get("retired")]
    return {"format": "doblarr-guidance/1", "templates": bundle_templates,
            "characters": characters, "examples": shared}


def import_guidance(db, bundle: dict, *, series_id: str, reviewer: str = "you") -> dict:
    """Bring guidance in, mapping characters by name into `series_id`.

    Missing templates are reported (examples that need them are skipped);
    existing profile fields a person locked are not overwritten.
    """
    from . import profiles

    if bundle.get("format") != "doblarr-guidance/1":
        raise ValueError("not a Doblarr guidance bundle")
    report: dict = {"templates": {}, "characters": [], "examples": 0, "skipped": []}
    if bundle.get("templates"):
        report["templates"] = templates.import_bundle(
            db, {"format": "doblarr-templates/1", "templates": bundle["templates"]})
    for row in bundle.get("characters") or []:
        character = identity.ensure_character(db, series_id, row["name"], origin="imported")
        profile = profiles.get(db, character["id"])
        fields = {}
        if row.get("templates"):
            fields["templates"] = row["templates"]
        if row.get("direction"):
            fields["delivery.direction"] = row["direction"]
        if fields:
            profiles.update(db, character["id"], set_fields=fields,
                            base_revision=profile["revision"], source="imported",
                            confidence="imported", respect_locks=True)
        report["characters"].append(row["name"])
    for n, row in enumerate(bundle.get("examples") or []):
        if templates.get(db, row.get("template") or "") is None:
            report["skipped"].append(f"example {n}: template {row.get('template')} missing")
            continue
        record_id = "ex-imp-" + digest([series_id, row])[:16]
        if records.get(db, "example", record_id) is not None:
            continue                       # importing twice adds nothing
        records.put(db, "example", record_id, {**row, "series_id": series_id,
                                               "scope": "series", "revision_id": "",
                                               "cue": f"imported-{n}", "retired": False,
                                               "holdout": False, "approved_by": reviewer,
                                               "imported": True, "at": records.now_marker()},
                    scope=series_id)
        report["examples"] += 1
    return report
