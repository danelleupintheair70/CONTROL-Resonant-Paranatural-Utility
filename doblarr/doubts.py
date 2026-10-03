"""The few questions about an episode's voices worth a person's time.

An answer from someone who watched the line beats any model, and an answer
about a whole voice beats one about a line: naming a 40-line voice names 40
lines. So the queue asks, in order:

1. Who is this voice? Every unnamed group with a few lines, most talk first,
   shown by its clearest line, with what the dialogue and the show's voice
   memory hint.
2. Who says this line? Lines the grouping decided with the least evidence:
   joined to the nearest voice, folded in from a tiny group, decided by a
   hair, or too short to hear well. On a hand-labelled episode the ten most
   doubtful lines held four of its fourteen misgrouped ones.

A line a person already assigned is never asked again. Reads only.
"""

from __future__ import annotations

DOUBTS = "doubt-queue/1"
MIN_VOICE_LINES = 3
LINE_THRESHOLD = 2.0


def line_doubt(line: dict) -> tuple[float, list[str]]:
    """How little evidence decided a line's voice, with the reasons."""
    why = line.get("why") or {}
    method = why.get("method")
    candidates = why.get("candidates") or []
    score, reasons = 0.0, []
    if method in ("nearest", "inherited"):
        score += 2.0
        reasons.append("too short to group; joined the closest voice" if method == "nearest"
                       else "no usable voice; took the previous speaker")
    elif method == "merged_small":
        score += 1.5
        reasons.append("folded in from a tiny group")
    margin = why.get("margin")
    if margin is not None and margin < 0.15:
        score += (0.15 - margin) * 10
        reasons.append(f"barely closer to this voice than to the next ({margin:.2f})")
    top = candidates[0]["similarity"] if candidates else None
    if top is not None and top < 0.6:
        score += (0.6 - top) * 5
        reasons.append(f"not much like any voice ({top:.2f})")
    if float(line["end"]) - float(line["start"]) < 1.2:
        score += 1.0
        reasons.append("a very short line")
    return round(score, 2), reasons


def _clearest(lines: list[dict]) -> dict:
    """A line that shows a voice well: long enough, cleanly measured, spoken."""
    def rank(line):
        quality = (line.get("features") or {}).get("quality")
        seconds = float(line["end"]) - float(line["start"])
        return (quality == "ok", min(seconds, 6.0), len(line.get("text") or ""))
    return max(lines, key=rank)


def queue(lines: list[dict], names: dict[str, str], *, dialogue: dict | None = None,
          suggestions: dict | None = None, reader: dict | None = None, voices: int = 6,
          per_line: int = 6) -> list[dict]:
    """Questions, most useful first: {kind: voice|line, ...}."""
    by_voice: dict[str, list[dict]] = {}
    for line in lines:
        by_voice.setdefault(line.get("speaker") or "", []).append(line)
    asks: list[dict] = []
    unnamed = sorted((v for v in by_voice if v and v not in names
                      and len(by_voice[v]) >= MIN_VOICE_LINES),
                     key=lambda v: -sum(float(x["end"]) - float(x["start"]) for x in by_voice[v]))
    for voice in unnamed[:voices]:
        sample = _clearest(by_voice[voice])
        hints = [{"name": a["name"], "why": f"answers when {a['name']} is called ({a['count']}×)"}
                 for a in ((dialogue or {}).get(voice) or {}).get("answers", [])[:2]]
        narrated = sum(1 for x in by_voice[voice] if x.get("role") in ("preview", "narration"))
        if narrated * 5 >= len(by_voice[voice]) * 3:
            hints.append({"name": "Narrator", "why": f"{narrated} of its lines are narration or "
                                                     "the next-episode preview"})
        hints += [{"name": s["name"],
                   "why": f"sounds like {s['name']} ({round(s['similarity'] * 100)}%)"}
                  for s in ((suggestions or {}).get(voice) or [])[:2]
                  if s["name"] not in {h["name"] for h in hints}]
        asks.append({"kind": "voice", "voice": voice, "lines": len(by_voice[voice]),
                     "line": sample, "hints": hints})
    doubtful = []
    for line in lines:
        if line.get("locked") or not line.get("speaker"):
            continue
        score, reasons = line_doubt(line)
        said = (reader or {}).get(line.get("cue")) or {}
        now = names.get(line["speaker"], "")
        disputed = bool(said.get("speaker")) and said.get("confidence") in ("high", "medium")
        if disputed and now and said["speaker"].casefold() != now.casefold():
            score += 3.0
            reasons.append(f"the script reader says {said['speaker']} ({said.get('clue', '')})")
        if score >= LINE_THRESHOLD:
            doubtful.append((score, line, reasons))
    doubtful.sort(key=lambda row: -row[0])
    for score, line, reasons in doubtful[:per_line]:
        candidates = [c["label"] for c in (line.get("why") or {}).get("candidates") or []]
        options = []
        said = (reader or {}).get(line.get("cue")) or {}
        if said.get("speaker") and said.get("confidence") in ("high", "medium"):
            options.append(said["speaker"])
        for label in candidates:
            name = names.get(label)
            if name and name not in options:
                options.append(name)
        asks.append({"kind": "line", "voice": line["speaker"], "line": line, "doubt": score,
                     "reasons": reasons, "now": names.get(line["speaker"], ""),
                     "options": options[:3]})
    return asks
