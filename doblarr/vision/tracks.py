"""Visible tracks: the same visible entity across consecutive sampled frames.

Faces are linked inside one shot only (a cut ends every track) and only between
detections of the same detector. Two faces in neighbouring frames are the same
track when their boxes overlap enough or, failing that, when their embeddings
(same embedder) are close. A track says "this face stayed on screen from t0 to
t1"; it does not say who it is (doblarr.vision.references) or that it spoke
(doblarr.vision.active).

Corrections a person makes (assign a character, mark unknown, split at a time,
merge two tracks) are stored per source revision and re-applied after every
reanalysis. A correction names its track by id and by an anchor (shot, time
span, box centre), so a track whose id changed after a model update is found
again by overlap instead of being silently dropped.
"""

from __future__ import annotations

from ..artifacts import digest
from ..studio import records

IOU_LINK = 0.3
EMBED_LINK = 0.6
MAX_GAP = 1.6          # seconds between sampled frames a track may skip


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def _cos(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


def shot_of(shots: list[dict], t: float) -> str:
    for shot in shots:
        if shot["start"] <= t < shot["end"]:
            return shot["id"]
    return shots[-1]["id"] if shots else "shot-0000"


def build(detections: list[dict], shots: list[dict], revision_id: str) -> list[dict]:
    """Tracks from per-frame detections ``{t, box, score, detector, domain, vector,
    embedder, crop}``, linked greedily frame to frame."""
    by_time: dict[float, list[dict]] = {}
    for det in detections:
        by_time.setdefault(det["t"], []).append(det)
    open_tracks: list[dict] = []
    finished: list[dict] = []
    for t in sorted(by_time):
        shot = shot_of(shots, t)
        still = []
        for track in open_tracks:
            if track["shot"] != shot or t - track["end"] > MAX_GAP:
                finished.append(track)
            else:
                still.append(track)
        open_tracks = still
        pairs = []
        for i, det in enumerate(by_time[t]):
            for j, track in enumerate(open_tracks):
                if track["detector"] != det["detector"]:
                    continue
                last = track["detections"][-1]
                overlap = iou(last["box"], det["box"])
                similar = _cos(last.get("vector"), det.get("vector")) \
                    if last.get("embedder") == det.get("embedder") else 0.0
                if overlap >= IOU_LINK or similar >= EMBED_LINK:
                    pairs.append((overlap + similar, i, j))
        used_det, used_track = set(), set()
        for _score, i, j in sorted(pairs, reverse=True):
            if i in used_det or j in used_track:
                continue
            used_det.add(i)
            used_track.add(j)
            track = open_tracks[j]
            track["detections"].append(by_time[t][i])
            track["end"] = t
        for i, det in enumerate(by_time[t]):
            if i in used_det:
                continue
            open_tracks.append({"shot": shot, "detector": det["detector"],
                                "domain": det["domain"], "start": t, "end": t,
                                "detections": [det]})
    finished.extend(open_tracks)
    out = []
    for track in sorted(finished, key=lambda tr: (tr["start"], tr["detector"])):
        dets = track["detections"]
        vectors = [d["vector"] for d in dets if d.get("vector")]
        mean = None
        if vectors:
            sums = [sum(col) for col in zip(*vectors, strict=True)]
            norm = sum(v * v for v in sums) ** 0.5 or 1.0
            mean = [round(v / norm, 4) for v in sums]
        best = max(dets, key=lambda d: (d.get("score") or 0.0, d["box"][2] * d["box"][3]))
        first = dets[0]["box"]
        track_id = "trk-" + digest([revision_id, track["shot"], track["start"],
                                    track["detector"], first])[:12]
        out.append({"id": track_id, "shot": track["shot"], "detector": track["detector"],
                    "domain": track["domain"], "start": track["start"],
                    "end": round(track["end"] + 0.001, 3),
                    "frames": len(dets), "embedder": dets[0].get("embedder", ""),
                    "vector": mean, "thumbnail": best.get("crop", ""),
                    "boxes": [[d["t"], *d["box"]] for d in dets],
                    "score": max((d.get("score") or 0.0) for d in dets) or None})
    return out


# --------------------------------------------------------------------------
# Corrections
# --------------------------------------------------------------------------

def corrections_id(revision_id: str) -> str:
    return "vcor-" + digest(revision_id)[:16]


def corrections(db, revision_id: str) -> dict:
    found = records.get(db, "visual", corrections_id(revision_id)) or {}
    return {"assign": dict(found.get("assign") or {}), "splits": dict(found.get("splits") or {}),
            "merges": list(found.get("merges") or []), "revision": found.get("revision", 0)}


def anchor(track: dict) -> dict:
    box = track["boxes"][len(track["boxes"]) // 2]
    return {"shot": track["shot"], "start": track["start"], "end": track["end"],
            "centre": [box[1] + box[3] / 2, box[2] + box[4] / 2]}


def correct(db, revision_id: str, *, base_revision: int | None, assign: dict | None = None,
            split: dict | None = None, merge: list | None = None,
            tracks: list[dict] | None = None) -> dict:
    """Record a person's decision about tracks (assignments are character ids,
    ``None`` meaning "unknown, and stay unknown")."""
    current = records.get(db, "visual", corrections_id(revision_id)) or {}
    doc: dict = {"revision_id": revision_id, "assign": dict(current.get("assign") or {}),
           "splits": dict(current.get("splits") or {}),
           "merges": list(current.get("merges") or []),
           "anchors": dict(current.get("anchors") or {})}
    by_id = {t["id"]: t for t in tracks or []}
    for track_id, character in (assign or {}).items():
        doc["assign"][track_id] = character
        if track_id in by_id:
            doc["anchors"][track_id] = anchor(by_id[track_id])
    for track_id, at in (split or {}).items():
        doc["splits"][track_id] = float(at)
        if track_id in by_id:
            doc["anchors"][track_id] = anchor(by_id[track_id])
    for pair in merge or []:
        doc["merges"].append([str(pair[0]), str(pair[1])])
        for track_id in pair:
            if track_id in by_id:
                doc["anchors"][track_id] = anchor(by_id[track_id])
    return records.put(db, "visual", corrections_id(revision_id), doc, scope=revision_id,
                       base_revision=base_revision if base_revision is not None
                       else current.get("revision", 0))


def _remap(track_id: str, saved: dict, tracks: list[dict]) -> str | None:
    if any(t["id"] == track_id for t in tracks):
        return track_id
    anchor_ = (saved.get("anchors") or {}).get(track_id)
    if not anchor_:
        return None
    best, best_overlap = None, 0.0
    for track in tracks:
        if track["shot"] != anchor_["shot"]:
            continue
        overlap = min(track["end"], anchor_["end"]) - max(track["start"], anchor_["start"])
        if overlap > best_overlap:
            best, best_overlap = track["id"], overlap
    return best


def apply(db, revision_id: str, tracks: list[dict]) -> list[dict]:
    """Tracks with a person's splits, merges and assignments applied."""
    saved = records.get(db, "visual", corrections_id(revision_id)) or {}
    out = [dict(t) for t in tracks]
    for track_id, at in (saved.get("splits") or {}).items():
        target = _remap(track_id, saved, out)
        if target is None:
            continue
        track = next(t for t in out if t["id"] == target)
        before = [b for b in track["boxes"] if b[0] < at]
        after = [b for b in track["boxes"] if b[0] >= at]
        if not before or not after:
            continue
        out.remove(track)
        out.append({**track, "boxes": before, "end": before[-1][0] + 0.001,
                    "frames": len(before)})
        out.append({**track, "id": track["id"] + "-b", "boxes": after, "start": after[0][0],
                    "frames": len(after), "split_from": track["id"]})
    for a, b in saved.get("merges") or []:
        ta, tb = _remap(a, saved, out), _remap(b, saved, out)
        if not ta or not tb or ta == tb:
            continue
        first = next(t for t in out if t["id"] == ta)
        second = next(t for t in out if t["id"] == tb)
        out.remove(second)
        first.update(start=min(first["start"], second["start"]),
                     end=max(first["end"], second["end"]),
                     boxes=sorted(first["boxes"] + second["boxes"]),
                     frames=first["frames"] + second["frames"],
                     merged=[*first.get("merged", []), second["id"]])
    for track_id, character in (saved.get("assign") or {}).items():
        target = _remap(track_id, saved, out)
        if target is None:
            continue
        track = next(t for t in out if t["id"] == target)
        track["character"] = character
        track["assigned"] = "manual"
    return sorted(out, key=lambda t: (t["start"], t["id"]))
