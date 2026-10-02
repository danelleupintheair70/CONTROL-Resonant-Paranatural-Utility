"""Scenes: shots grouped by dialogue continuity, not by every camera cut.

A cut is a property of the picture. A conversation filmed shot/reverse-shot is
one scene with many cuts, and nothing about a cut should reset a background
level or start a new character. A cut becomes a scene boundary only when the
dialogue around it breaks: no line spans it and the gap in speech across it is
long. Long stretches without dialogue are boundaries too. Boundaries close to
the threshold are marked uncertain. A person can add or remove boundaries; their
corrections are kept per source revision and re-applied.
"""

from __future__ import annotations

from ..artifacts import digest
from ..studio import records

GAP = 4.0             # seconds of no speech across a cut that ends a scene
SILENCE = 10.0        # a stretch this long without dialogue is a boundary on its own
UNCERTAIN = 1.5       # within this of GAP, a boundary is uncertain


def corrections_id(revision_id: str) -> str:
    return "vscn-" + digest(revision_id)[:16]


def corrections(db, revision_id: str) -> dict:
    found = records.get(db, "visual", corrections_id(revision_id)) or {}
    return {"add": list(found.get("add") or []), "remove": list(found.get("remove") or []),
            "revision": found.get("revision", 0)}


def correct(db, revision_id: str, *, add: list[float] | None = None,
            remove: list[float] | None = None, base_revision: int | None) -> dict:
    current = corrections(db, revision_id)
    doc = {"revision_id": revision_id,
           "add": sorted(set(current["add"]) | {round(float(t), 2) for t in add or []}),
           "remove": sorted(set(current["remove"]) | {round(float(t), 2) for t in remove or []})}
    return records.put(db, "visual", corrections_id(revision_id), doc, scope=revision_id,
                       base_revision=current["revision"] if base_revision is None
                       else base_revision)


def group(shots: list[dict], lines: list[dict], duration: float,
          manual: dict | None = None) -> list[dict]:
    """Scenes over the timeline. `lines` are ``{cue, start, end}``."""
    manual = manual or {"add": [], "remove": []}
    spans = sorted((float(line["start"]), float(line["end"])) for line in lines)
    boundaries: dict[float, dict] = {}
    for shot in shots[1:]:
        cut = float(shot["start"])
        if any(a < cut < b for a, b in spans):
            continue                              # a line runs across the cut
        before = max((b for a, b in spans if b <= cut), default=None)
        after = min((a for a, b in spans if a >= cut), default=None)
        gap = ((after if after is not None else duration)
               - (before if before is not None else 0.0))
        if gap >= GAP:
            boundaries[round(cut, 2)] = {"reason": f"{gap:.1f}s without dialogue across a cut",
                                         "uncertain": gap < GAP + UNCERTAIN}
    for (_a1, b1), (a2, _b2) in zip(spans, spans[1:], strict=False):
        if a2 - b1 >= SILENCE and not any(b1 < t < a2 for t in boundaries):
            middle = round((b1 + a2) / 2, 2)
            boundaries[middle] = {"reason": f"{a2 - b1:.1f}s of silence", "uncertain": False}
    # Several cuts inside one stretch without dialogue are one change of scene:
    # keep the last cut before the next line (where the new scene is set up).
    collapsed: dict[float, dict] = {}
    ordered = sorted(boundaries)
    for i, t in enumerate(ordered):
        following = ordered[i + 1] if i + 1 < len(ordered) else None
        if following is not None and not any(t <= a < following for a, _b in spans):
            continue
        collapsed[t] = boundaries[t]
    boundaries = collapsed
    for t in manual.get("remove") or []:
        for key in [k for k in boundaries if abs(k - float(t)) < 0.5]:
            boundaries.pop(key)
    for t in manual.get("add") or []:
        boundaries[round(float(t), 2)] = {"reason": "set by hand", "uncertain": False,
                                          "manual": True}
    edges = [0.0, *sorted(boundaries), duration or (spans[-1][1] if spans else 0.0)]
    scenes = []
    for i, (start, end) in enumerate(zip(edges, edges[1:], strict=False)):
        if end <= start:
            continue
        inside = [s for s in shots if start <= float(s["start"]) < end]
        info = boundaries.get(start, {})
        scenes.append({"id": f"scene-{i:03d}", "start": round(start, 2), "end": round(end, 2),
                       "shots": [s["id"] for s in inside],
                       "lines": [line["cue"] for line in lines
                                 if start <= float(line["start"]) < end],
                       "boundary": info.get("reason", "start"),
                       "uncertain": bool(info.get("uncertain")),
                       "manual": bool(info.get("manual"))})
    return scenes


def line_context(line: dict, shots: list[dict], scenes: list[dict]) -> dict:
    """Where a line sits: its scene, how many shots it spans, whether a cut falls inside."""
    start, end = float(line["start"]), float(line["end"])
    inside = [s for s in shots if float(s["end"]) > start and float(s["start"]) < end]
    scene = next((s for s in scenes if s["start"] <= start < s["end"]), None)
    return {"scene": scene["id"] if scene else None, "shots": len(inside),
            "cut_inside": any(start < float(s["start"]) < end for s in shots)}
