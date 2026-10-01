"""Voice tags: a character's voice, remembered across a show once named.

Grouping finds voices but cannot know who they are, and it splits one person
into several groups when they shout and when they whisper. Naming a group
tags its lines: the mean of their voice vectors becomes that character's
print for the show. Every unnamed group, in the same episode or the next one,
is then compared with the prints and offered the nearest names. A person
confirms; nothing is renamed on its own.

Prints are kept per voice model (vectors from two models are not comparable)
and per episode, so naming an episode again replaces what it taught instead
of counting it twice. They live in the plan store under the show's folder.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import speakers

KEY = "voice-tags:"
FLOOR = 0.3          # below this a "match" is noise for every model measured
SEASON_FOLDER = re.compile(r"^(season|series|temporada|saison|staffel|specials?)\b|^s?\d+$",
                           re.IGNORECASE)


def show_key(path: str) -> str:
    """The show an episode belongs to: its folder above any season folder."""
    folder = Path(str(path).replace("\\", "/")).parent
    if SEASON_FOLDER.match(folder.name) and folder.parent.name:
        folder = folder.parent
    return KEY + folder.name.casefold()


def episode_key(path: str) -> str:
    return Path(str(path).replace("\\", "/")).name.casefold()


def read_sidecar(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _anchors(lines: list[dict]):
    """Lines long enough to say something about a voice."""
    return [line for line in lines if line.get("vector")
            and float(line["end"]) - float(line["start"]) >= speakers.MIN_EMBED]


def name_sums(lines: list[dict], names: dict[str, str]) -> dict[str, dict]:
    """Per character: the sum of its lines' vectors and how many there were."""
    import numpy as np

    sums: dict[str, dict] = {}
    for line in _anchors(lines):
        name = names.get(line.get("speaker") or "")
        if not name:
            continue
        entry = sums.setdefault(name, {"sum": None, "n": 0})
        vector = np.asarray(line["vector"], dtype=np.float64)
        entry["sum"] = vector if entry["sum"] is None else entry["sum"] + vector
        entry["n"] += 1
    return {name: {"sum": [round(float(x), 5) for x in entry["sum"]], "n": entry["n"]}
            for name, entry in sums.items()}


def _load(db, path: str) -> dict:
    return ((db.load_plan(show_key(path)) or {}).get("plan") or {})


def remember(db, path: str, sidecar: dict | None, names: dict[str, str]) -> dict[str, int]:
    """Teach the show what this episode's named voices sound like."""
    if not sidecar or not sidecar.get("model"):
        return {}
    doc = _load(db, path)
    by_episode = doc.setdefault("models", {}).setdefault(sidecar["model"], {})
    sums = name_sums(sidecar.get("lines") or [], names)
    if sums:
        by_episode[episode_key(path)] = sums
    else:
        by_episode.pop(episode_key(path), None)
    folder = show_key(path)[len(KEY):]
    db.save_plan(show_key(path), folder, doc)
    return {name: entry["n"] for name, entry in sums.items()}


def prints(db, path: str, model: str, sidecar: dict | None = None,
           names: dict[str, str] | None = None) -> dict[str, dict]:
    """Every tagged character of the show for one model, with this episode's
    current names in place of what it taught before."""
    import numpy as np

    totals: dict[str, dict] = {}
    by_episode = dict((_load(db, path).get("models") or {}).get(model) or {})
    if sidecar is not None and names is not None:
        by_episode[episode_key(path)] = name_sums(sidecar.get("lines") or [], names)
    for sums in by_episode.values():
        for name, entry in sums.items():
            total = totals.setdefault(name, {"sum": None, "n": 0, "episodes": 0})
            vector = np.asarray(entry["sum"], dtype=np.float64)
            total["sum"] = vector if total["sum"] is None else total["sum"] + vector
            total["n"] += entry["n"]
            total["episodes"] += 1
    out = {}
    for name, total in totals.items():
        norm = float(np.linalg.norm(total["sum"]))
        if norm:
            out[name] = {"vector": total["sum"] / norm, "lines": total["n"],
                         "episodes": total["episodes"]}
    return out


def cast(db, path: str, names: dict[str, str] | None = None) -> list[dict]:
    """Every character named anywhere in the show, most heard first, so a
    name is picked from the cast instead of typed again (and mistyped)."""
    # name -> episode -> lines; an episode grouped with two models counts once.
    heard: dict[str, dict[str, int]] = {}
    for by_episode in (_load(db, path).get("models") or {}).values():
        for episode, sums in by_episode.items():
            for name, entry in sums.items():
                per = heard.setdefault(name, {})
                per[episode] = max(per.get(episode, 0), int(entry["n"]))
    for name in (names or {}).values():
        heard.setdefault(name, {})
    rows = [{"name": name, "lines": sum(per.values()), "episodes": len(per)}
            for name, per in heard.items()]
    return sorted(rows, key=lambda r: (-r["lines"], r["name"].casefold()))


def suggest(db, path: str, sidecar: dict | None, names: dict[str, str],
            top: int = 3) -> dict[str, list[dict]]:
    """For each unnamed group, the tagged characters it sounds closest to."""
    import numpy as np

    if not sidecar or not sidecar.get("model"):
        return {}
    known = prints(db, path, sidecar["model"], sidecar, names)
    if not known:
        return {}
    groups: dict[str, list] = {}
    for line in _anchors(sidecar.get("lines") or []):
        label = line.get("speaker") or ""
        if label and not names.get(label):
            groups.setdefault(label, []).append(np.asarray(line["vector"], dtype=np.float64))
    out: dict[str, list[dict]] = {}
    for label, vectors in groups.items():
        mean = np.mean(vectors, axis=0)
        norm = float(np.linalg.norm(mean))
        if not norm:
            continue
        ranked = sorted(((float(mean @ p["vector"]) / norm, name, p)
                         for name, p in known.items()), key=lambda r: -r[0])
        picks = [{"name": name, "similarity": round(score, 3), "lines": p["lines"],
                  "episodes": p["episodes"]}
                 for score, name, p in ranked[:top] if score >= FLOOR]
        if picks:
            out[label] = picks
    return out


def carry_names(old: list[str], new: list[str], seconds: list[float],
                names: dict[str, str], share: float = 0.5) -> dict[str, str]:
    """Names for a fresh grouping of the same lines: a new group takes the name
    that most of its speaking time had, when that is at least `share` of it."""
    heard: dict[str, dict[str, float]] = {}
    for before, after, duration in zip(old, new, seconds, strict=True):
        name = names.get(before or "", "")
        bucket = heard.setdefault(after, {})
        bucket[name] = bucket.get(name, 0.0) + duration
    carried = {}
    for label, by_name in heard.items():
        total = sum(by_name.values())
        name, time = max(by_name.items(), key=lambda kv: kv[1])
        if name and total and time / total >= share:
            carried[label] = name
    return carried
