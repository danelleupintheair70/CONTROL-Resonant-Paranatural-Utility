"""Approved local face references per character, and matching tracks to them.

A reference is a face crop a person tied to a character (by assigning a track
to them), with the embedding of the embedder that produced it. Matching only
compares vectors of the same embedder: an SFace vector says nothing about a
DINOv2 vector. A match is a *proposal* with its similarity and the margin to
the next character; it never assigns a name on its own, and it is never made
from a reference that is not approved.
"""

from __future__ import annotations

from ..artifacts import digest
from ..studio import records

MAX_PER_CHARACTER = 12
MIN_MARGIN = 0.05


def references_id(series_id: str) -> str:
    return "vref-" + digest(series_id)[:16]


def load(db, series_id: str) -> dict:
    found = records.get(db, "visual", references_id(series_id)) or {}
    return {"references": list(found.get("references") or []),
            "revision": found.get("revision", 0)}


def add_from_track(db, series_id: str, track: dict, character_id: str, *,
                   revision_id: str, approved: bool = True) -> dict:
    """Keep a track's face as a reference for a character (a person's decision)."""
    if not track.get("vector"):
        return load(db, series_id)
    current = load(db, series_id)
    refs = [r for r in current["references"]
            if not (r["source"].get("track") == track["id"]
                    and r["source"].get("revision_id") == revision_id)]
    mine = [r for r in refs if r["character_id"] == character_id
            and r["embedder"] == track["embedder"]]
    if len(mine) >= MAX_PER_CHARACTER:
        oldest = mine[0]
        refs = [r for r in refs if r is not oldest]
    refs.append({"id": "vr-" + digest([series_id, revision_id, track["id"]])[:12],
                 "character_id": character_id, "embedder": track["embedder"],
                 "domain": track.get("domain", ""), "vector": track["vector"],
                 "thumbnail": track.get("thumbnail", ""), "approved": approved,
                 "source": {"revision_id": revision_id, "track": track["id"],
                            "start": track["start"], "end": track["end"]},
                 "at": records.now_marker()})
    records.put(db, "visual", references_id(series_id),
                {"series_id": series_id, "references": refs}, scope=series_id,
                base_revision=current["revision"])
    return load(db, series_id)


def match(track: dict, references: list[dict], threshold: float,
          exclude_revisions: set[str] | None = None) -> list[dict]:
    """Characters this track's face is closest to (approved references only)."""
    vector = track.get("vector")
    if not vector:
        return []
    best: dict[str, float] = {}
    for ref in references:
        if not ref.get("approved") or ref["embedder"] != track.get("embedder"):
            continue
        if ref["source"].get("revision_id") in (exclude_revisions or set()) or \
                ref["source"].get("track") == track["id"]:
            continue
        score = float(sum(a * b for a, b in zip(vector, ref["vector"], strict=True)))
        best[ref["character_id"]] = max(best.get(ref["character_id"], -1.0), score)
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    out = []
    for i, (character, score) in enumerate(ranked[:3]):
        following = ranked[i + 1][1] if i + 1 < len(ranked) else None
        margin = round(score - following, 3) if following is not None else None
        out.append({"character_id": character, "similarity": round(score, 3),
                    "margin": margin,
                    "proposed": i == 0 and score >= threshold
                    and (margin is None or margin >= MIN_MARGIN)})
    return out
