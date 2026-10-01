"""Who speaks a line, from every kind of evidence kept apart and then fused.

Three observations are never collapsed into one:

- **audio identity**: the line's voice group and the character it is linked to
  (doblarr.identity), with how the grouping decided it (doblarr.speakers);
- **visible identity**: face tracks on screen during the line and the character
  a person assigned (or an approved reference proposes) for each;
- **mouth activity**: whether a visible face moves its mouth with the speech
  (doblarr.vision.active).

The fusion ranks candidate characters with the reason for each, records
conflicts, and abstains when nothing is strong enough. Its rules:

1. A line a person assigned by hand is decided; nothing overrides it.
2. A clear audio identity (heard and clustered, margin above `AUDIO_MARGIN`)
   decides, and visual agreement or disagreement is recorded beside it.
3. A weak audio identity (a short line that inherited or took the nearest
   group, a merged small group, a small margin) may be *proposed* for review
   from a speaking face of a named character above the calibrated threshold.
   It is never applied automatically, so an uncertain visual association
   cannot silently recast a character.
4. Faces that are visible but not speaking (reaction shots) contribute
   presence only; they never take a line.
5. With no face on screen the line is offscreen; when the visual stages did not
   run or are unsupported, the context says unknown, not offscreen.
"""

from __future__ import annotations

AUDIO_MARGIN = 0.05
SPEAKING = 0.35        # default speaking-face score threshold until calibrated
WEAK_METHODS = ("inherited", "nearest", "merged_small")
MIN_OVERLAP = 0.3      # share of the line a track must be on screen for


def overlapping(tracks: list[dict], start: float, end: float) -> list[dict]:
    length = max(0.01, end - start)
    out = []
    for track in tracks:
        shared = min(track["end"], end) - max(track["start"], start)
        if shared / length >= MIN_OVERLAP or (track["start"] <= start and track["end"] >= end):
            out.append(track)
    return out


def track_character(track: dict) -> tuple[str | None, str]:
    """The character a track shows and on what authority."""
    if track.get("assigned") == "manual":
        return track.get("character"), "manual"
    for proposal in track.get("matches") or []:
        if proposal.get("proposed"):
            return proposal["character_id"], "reference"
    return None, "none"


def fuse(line: dict, *, audio_character: str | None, why: dict | None, locked: str | None,
         tracks: list[dict], speaking: dict[str, dict], threshold: float = SPEAKING,
         visual_state: str = "done") -> dict:
    """The association record for one line."""
    candidates: dict[str, dict] = {}

    def candidate(character: str) -> dict:
        return candidates.setdefault(character, {"character_id": character, "audio": 0.0,
                                                 "speaking": 0.0, "visible": 0.0,
                                                 "reasons": []})

    why = why or {}
    method = why.get("method", "unknown")
    margin = why.get("margin")
    audio_strong = method in ("clustered", "manual") and (margin is None or margin >=
                                                          AUDIO_MARGIN)
    if audio_character:
        row = candidate(audio_character)
        row["audio"] = 1.0 if audio_strong else 0.5
        row["reasons"].append(f"voice group linked to this character ({method}"
                              + (f", margin {margin:.2f}" if margin is not None else "") + ")")
    on_screen = overlapping(tracks, float(line["start"]), float(line["end"]))
    speaking_faces = []
    for track in on_screen:
        character, authority = track_character(track)
        evidence = speaking.get(track["id"]) or {}
        score = float(evidence.get("score") or 0.0)
        is_speaking = evidence.get("state") == "measured" and score >= threshold and \
            (evidence.get("correlation") or 0.0) > 0.0
        if is_speaking:
            speaking_faces.append((track, character, score))
        if character:
            row = candidate(character)
            row["visible"] = max(row["visible"], 1.0 if authority == "manual" else 0.6)
            if is_speaking:
                row["speaking"] = max(row["speaking"], score)
                row["reasons"].append(f"face on screen moving its mouth with the speech "
                                      f"(score {score:.2f}, {authority})")
            else:
                row["reasons"].append(f"face on screen ({authority}), not visibly speaking")
    if visual_state != "done":
        screen = "unknown"
    elif not on_screen:
        screen = "offscreen"
    elif speaking_faces:
        screen = "onscreen-speaking"
    else:
        screen = "onscreen-silent"
    conflicts = []
    named_speakers = {c for _t, c, _s in speaking_faces if c}
    if audio_character and named_speakers and audio_character not in named_speakers:
        conflicts.append({"kind": "voice-vs-face", "voice": audio_character,
                          "faces": sorted(named_speakers)})
    decision: dict
    if locked is not None:
        decision = {"state": "manual", "character_id": locked,
                    "reason": "assigned by hand; evidence is shown but does not override it"}
    elif audio_character and audio_strong:
        decision = {"state": "audio", "character_id": audio_character,
                    "reason": "clear voice evidence"
                    + ("; a speaking face disagrees, review suggested" if conflicts else "")}
    elif len(named_speakers) == 1 and (not audio_character or not audio_strong):
        face = next(iter(named_speakers))
        decision = {"state": "proposal", "character_id": face,
                    "reason": "weak voice evidence and one named face speaking on screen; "
                              "a proposal for review, never applied on its own"}
    elif audio_character:
        decision = {"state": "audio-weak", "character_id": audio_character,
                    "reason": f"voice evidence only, and weak ({method})"}
    else:
        decision = {"state": "unknown", "character_id": None,
                    "reason": "no voice link and no named speaking face"}
    ranked = sorted(candidates.values(), key=lambda c: -(c["audio"] + c["speaking"]
                                                          + 0.25 * c["visible"]))
    return {"cue": line["cue"], "screen": screen, "decision": decision,
            "candidates": ranked[:4], "conflicts": conflicts,
            "visible_tracks": [t["id"] for t in on_screen],
            "speaking_tracks": [t["id"] for t, _c, _s in speaking_faces]}


def calibrate(rows: list[dict], truth: dict[str, str], target: float = 0.9) -> dict:
    """The lowest speaking-face score at which named speaking faces agree with
    the corrected speaker at least `target` of the time, if any.

    `rows` are ``{cue, character_id, score}`` for each named speaking face;
    `truth` maps cue → corrected character id. Reports the precision curve so
    the threshold is evidence, not a guess.
    """
    points = []
    for threshold in (0.2, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7):
        picked = [r for r in rows if r["score"] >= threshold and r["cue"] in truth]
        if not picked:
            continue
        correct = sum(1 for r in picked if truth[r["cue"]] == r["character_id"])
        points.append({"threshold": threshold, "answered": len(picked),
                       "precision": round(correct / len(picked), 3)})
    passing = [p for p in points if p["precision"] >= target and p["answered"] >= 5]
    return {"target": target, "curve": points,
            "threshold": passing[0]["threshold"] if passing else None,
            "calibrated": bool(passing)}
