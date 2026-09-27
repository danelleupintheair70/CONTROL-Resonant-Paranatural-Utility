"""Many-to-many alignment between the original's lines and a reference's lines.

Two releases rarely share a clock. One is offset, one runs slightly fast, one
lost a scene. So a reference keeps its own timeline and an explicit
`TimeMap` says how it lands on the source timeline, piece by piece; a stretch
the map does not cover is a cut, not a guess.

Lines are grouped by overlap on the mapped timeline. A group can hold several
source lines and several reference lines (one dub merged two lines, another
split one). Every group carries a confidence and a state:

- ``matched``    enough overlap that the lines plausibly say the same moment;
- ``uncertain``  some overlap, not enough to rely on — never injected silently;
- ``unmatched``  a line with nothing on the other side (added, omitted, cut);
- ``excluded``   a person decided this span must not be used.

A person can link, unlink, exclude or re-map. Each change produces a new
alignment revision; nothing is edited in place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..artifacts import digest

METHOD = "overlap/1"
# Minimum shared time, as a share of the shorter line, for two lines to be
# considered the same moment at all.
MIN_OVERLAP = 0.2
# Padding either side of a mapped line when looking for partners: dubs start a
# beat early or late far more often than they move a line by a second.
PAD = 0.25
# At or above this, a group is `matched`; below it but above zero, `uncertain`.
MATCHED = 0.5
# A chain of lines this long on one side is almost always overlap bleeding
# through a busy scene rather than one merged utterance.
MAX_SIDE = 4


@dataclass
class MapSegment:
    """``source = reference * rate + offset`` for reference times in [start, end)."""

    start: float
    end: float
    offset: float = 0.0
    rate: float = 1.0
    confidence: float | None = None
    method: str = "manual"

    def contains(self, t: float) -> bool:
        return self.start <= t < self.end

    def to_source(self, t: float) -> float:
        return t * self.rate + self.offset

    def to_reference(self, t: float) -> float:
        return (t - self.offset) / self.rate

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "offset": self.offset,
                "rate": self.rate, "confidence": self.confidence, "method": self.method}

    @classmethod
    def from_dict(cls, data: dict) -> MapSegment:
        start, end = float(data["start"]), float(data["end"])
        rate = float(data.get("rate", 1.0))
        if end <= start or rate <= 0.5 or rate >= 2.0:
            raise ValueError("a time-map segment needs end > start and a plausible rate")
        confidence = data.get("confidence")
        return cls(start, end, float(data.get("offset", 0.0)), rate,
                   None if confidence is None else float(confidence),
                   str(data.get("method") or "manual"))


class TimeMap:
    """Piecewise-linear mapping from one reference's timeline to the source's."""

    def __init__(self, segments: list[MapSegment] | None = None):
        self.segments = sorted(segments or [], key=lambda s: s.start)
        for a, b in zip(self.segments, self.segments[1:], strict=False):
            if b.start < a.end:
                raise ValueError("time-map segments must not overlap")

    @classmethod
    def identity(cls, length: float = 1e7) -> TimeMap:
        return cls([MapSegment(0.0, length, 0.0, 1.0, None, "identity")])

    @classmethod
    def from_dict(cls, data: dict | None) -> TimeMap:
        rows = (data or {}).get("segments") or []
        return cls([MapSegment.from_dict(r) for r in rows]) if rows else cls.identity()

    def as_dict(self) -> dict:
        return {"segments": [s.as_dict() for s in self.segments]}

    def segment_at(self, t: float) -> MapSegment | None:
        return next((s for s in self.segments if s.contains(t)), None)

    def to_source(self, start: float, end: float) -> tuple[float, float, MapSegment] | None:
        """Map a reference span, or None when its middle falls in a cut."""
        middle = (start + end) / 2
        seg = self.segment_at(middle)
        if seg is None:
            return None
        return seg.to_source(start), seg.to_source(end), seg

    def to_reference(self, start: float, end: float) -> tuple[float, float, MapSegment] | None:
        """Map a source span back onto the reference, for playback of the same moment."""
        middle = (start + end) / 2
        for seg in self.segments:
            ref = seg.to_reference(middle)
            if seg.contains(ref):
                return seg.to_reference(start), seg.to_reference(end), seg
        return None


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def align(source: list[dict], reference: list[dict], time_map: TimeMap | None = None) -> dict:
    """Group source and reference utterances; returns an alignment body."""
    time_map = time_map or TimeMap.identity()
    mapped: dict[str, tuple[float, float, float | None]] = {}
    outside = []
    for utt in reference:
        placed = time_map.to_source(float(utt["start"]), float(utt["end"]))
        if placed is None:
            outside.append(utt["utt_id"])
            continue
        start, end, seg = placed
        mapped[utt["utt_id"]] = (start, end, seg.confidence)
    src = {u["utt_id"]: (float(u["start"]), float(u["end"])) for u in source}
    # Bipartite overlap edges, then connected components.
    edges: dict[str, set[str]] = {}
    strength: dict[tuple[str, str], float] = {}
    for sid, s_span in src.items():
        for rid, (r0, r1, _conf) in mapped.items():
            shared = _overlap((s_span[0] - PAD, s_span[1] + PAD), (r0, r1))
            shorter = min(s_span[1] - s_span[0], r1 - r0)
            if shorter <= 0 or shared < MIN_OVERLAP * shorter:
                continue
            edges.setdefault("s:" + sid, set()).add("r:" + rid)
            edges.setdefault("r:" + rid, set()).add("s:" + sid)
            strength[(sid, rid)] = _overlap(s_span, (r0, r1))
    seen: set[str] = set()
    groups = []
    order = [("s:" + u["utt_id"]) for u in source] + [("r:" + u["utt_id"]) for u in reference
                                                       if u["utt_id"] in mapped]
    for node in order:
        if node in seen:
            continue
        stack, members = [node], []
        seen.add(node)
        while stack:
            current = stack.pop()
            members.append(current)
            for nxt in edges.get(current, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        sids = [m[2:] for m in members if m.startswith("s:")]
        rids = [m[2:] for m in members if m.startswith("r:")]
        sids.sort(key=lambda i: src[i][0])
        rids.sort(key=lambda i: mapped[i][0])
        groups.append(_group(sids, rids, src, mapped, strength))
    for rid in outside:
        groups.append({"source": [], "reference": [rid], "confidence": None,
                       "state": "unmatched", "manual": False,
                       "evidence": {"reason": "outside the mapped range — possibly cut from "
                                              "this edition, or the map does not reach here"}})
    groups.sort(key=lambda g: g.get("span", {}).get("start", 1e12))
    for n, group in enumerate(groups):
        group["group_id"] = "g-" + digest([group["source"], group["reference"]])[:10]
        group.setdefault("order", n)
    return {"method": METHOD, "time_map": time_map.as_dict(), "groups": groups,
            "stats": stats(groups)}


def _group(sids, rids, src, mapped, strength) -> dict:
    if not sids or not rids:
        side = sids or rids
        spans = [src[i] for i in sids] or [mapped[i][:2] for i in rids]
        return {"source": sids, "reference": rids, "confidence": None, "state": "unmatched",
                "manual": False,
                "span": {"start": min(s[0] for s in spans), "end": max(s[1] for s in spans)},
                "evidence": {"reason": ("nothing in the reference overlaps this line"
                                        if sids else "no original line overlaps this reference "
                                        "line — added, or mistimed"),
                             "lines": len(side)}}
    s_spans = [src[i] for i in sids]
    r_spans = [mapped[i][:2] for i in rids]
    union = (min(x[0] for x in s_spans + r_spans), max(x[1] for x in s_spans + r_spans))
    shared = sum(strength.get((s, r), 0.0) for s in sids for r in rids)
    total = max(1e-6, union[1] - union[0])
    confidence = round(min(1.0, shared / total), 3)
    maps = [mapped[i][2] for i in rids if mapped[i][2] is not None]
    if maps:
        confidence = round(confidence * min(maps), 3)
    state = "matched" if confidence >= MATCHED else "uncertain"
    reasons = []
    if len(sids) > MAX_SIDE or len(rids) > MAX_SIDE:
        state, reasons = "uncertain", ["a long chain of overlapping lines — busy scene"]
    return {"source": sids, "reference": rids, "confidence": confidence, "state": state,
            "manual": False, "span": {"start": union[0], "end": union[1]},
            "evidence": {"overlap_seconds": round(shared, 3), "union_seconds": round(total, 3),
                         "shape": f"{len(sids)}:{len(rids)}", "notes": reasons}}


def stats(groups: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for g in groups:
        counts[g["state"]] = counts.get(g["state"], 0) + 1
    shapes: dict[str, int] = {}
    for g in groups:
        if g["source"] and g["reference"]:
            key = f"{min(len(g['source']), 3)}:{min(len(g['reference']), 3)}"
            shapes[key] = shapes.get(key, 0) + 1
    return {"groups": len(groups), "states": counts, "shapes": shapes}


def apply_override(body: dict, override: dict, source: list[dict],
                   reference: list[dict]) -> dict:
    """A person's correction, applied to a copy of the alignment body."""
    groups = [dict(g) for g in body["groups"]]
    action = override.get("action")
    by_id = {g["group_id"]: g for g in groups}
    if action in ("exclude", "include", "unlink"):
        target = by_id.get(str(override.get("group_id")))
        if target is None:
            raise ValueError("that alignment group no longer exists")
        if action == "exclude":
            target["previous_state"] = target.get("state")
            target["state"], target["manual"] = "excluded", True
        elif action == "include":
            target["state"] = target.pop("previous_state", None) or "uncertain"
            target["manual"] = True
        else:
            groups.remove(target)
            for sid in target["source"]:
                groups.append({"source": [sid], "reference": [], "confidence": None,
                               "state": "unmatched", "manual": True,
                               "evidence": {"reason": "unlinked by hand"}})
            for rid in target["reference"]:
                groups.append({"source": [], "reference": [rid], "confidence": None,
                               "state": "unmatched", "manual": True,
                               "evidence": {"reason": "unlinked by hand"}})
    elif action == "link":
        sids = [str(i) for i in override.get("source") or []]
        rids = [str(i) for i in override.get("reference") or []]
        known_s = {u["utt_id"] for u in source}
        known_r = {u["utt_id"] for u in reference}
        if not sids or not rids or set(sids) - known_s or set(rids) - known_r:
            raise ValueError("a manual link needs existing lines on both sides")
        taken = set(sids) | set(rids)
        kept = []
        for g in groups:
            rest_s = [s for s in g["source"] if s not in taken]
            rest_r = [r for r in g["reference"] if r not in taken]
            if (rest_s, rest_r) == (g["source"], g["reference"]):
                kept.append(g)
            elif rest_s or rest_r:
                kept.append({**g, "source": rest_s, "reference": rest_r,
                             "state": "uncertain" if rest_s and rest_r else "unmatched",
                             "manual": True,
                             "evidence": {"reason": "part of this group was relinked by hand"}})
        kept.append({"source": sids, "reference": rids, "confidence": 1.0, "state": "matched",
                     "manual": True, "evidence": {"reason": "linked by hand",
                                                  "note": str(override.get("note") or "")[:500]}})
        groups = kept
    else:
        raise ValueError(f"unknown alignment correction {action!r}")
    src_times = {u["utt_id"]: (u["start"], u["end"]) for u in source}
    ref_times = {u["utt_id"]: (u["start"], u["end"]) for u in reference}
    time_map = TimeMap.from_dict(body.get("time_map"))
    for g in groups:
        spans = [src_times[i] for i in g["source"] if i in src_times]
        for rid in g["reference"]:
            placed = time_map.to_source(*ref_times[rid]) if rid in ref_times else None
            if placed:
                spans.append(placed[:2])
        if spans:
            g["span"] = {"start": min(s[0] for s in spans), "end": max(s[1] for s in spans)}
        g["group_id"] = "g-" + digest([g["source"], g["reference"]])[:10]
    groups.sort(key=lambda g: g.get("span", {}).get("start", 1e12))
    return {**body, "groups": groups, "stats": stats(groups),
            "overrides": list(body.get("overrides") or []) + [override]}


_DIGITS = re.compile(r"\d+")
_QUESTION = re.compile(r"[?？¿]")


def differences(source_text: str, reference_text: str) -> list[str]:
    """Cheap, explainable signals that a reference may say something different.

    These are prompts to look, never conclusions: a dub legitimately changes
    wording, and a matching number proves nothing either.
    """
    notes = []
    a, b = set(_DIGITS.findall(source_text or "")), set(_DIGITS.findall(reference_text or ""))
    if a != b and (a or b):
        notes.append("numbers differ")
    if bool(_QUESTION.search(source_text or "")) != bool(_QUESTION.search(reference_text or "")):
        notes.append("one is a question, the other is not")
    if source_text and reference_text:
        ratio = len(reference_text) / max(1, len(source_text))
        if ratio > 4:
            notes.append("reference is much longer — it may add information")
    if not reference_text:
        notes.append("nothing in the reference here")
    return notes


def usable_groups(body: dict) -> list[dict]:
    """Groups a writing condition may read: matched, never uncertain or excluded."""
    return [g for g in body.get("groups", [])
            if g.get("state") == "matched" and g["source"] and g["reference"]]
