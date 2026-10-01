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


# --------------------------------------------------------------------------
# Series-keyed prints (canonical identities, doblarr.identity)
# --------------------------------------------------------------------------
#
# The functions above key a show by its folder name and a character by the
# name typed for it; they stay for older callers and for the migration. The
# ones below key a show by its series id and a character by its id, and keep
# vectors apart by partition: a model's vectors are only comparable with the
# same model's, and a voice heard in Japanese is a different performer from the
# same character in a Spanish dub, so the source language is part of the key.
# A legacy print whose language was never recorded sits in its own partition
# ("unknown") and is never averaged with a known-language one.

SERIES_KEY = "voice-prints:"
PRINTS_VERSION = 2
PROTOTYPE_MIN_LINES = 8     # a character heard this often may get several prototypes
PROTOTYPE_MIN_SHARE = 3     # a prototype needs at least this many lines of its own
QUALITY_CAP = 4.0           # seconds; longer lines count no more than this


def series_key(series_id: str) -> str:
    return SERIES_KEY + series_id


def partition(model: str, language: str) -> str:
    return f"{model}|{(language or '').split('-')[0].lower() or 'unknown'}"


def _weighted(lines: list[dict]):
    import numpy as np

    vectors = np.asarray([line["vector"] for line in lines], dtype=np.float64)
    weights = np.asarray([min(QUALITY_CAP, float(line["end"]) - float(line["start"]))
                          for line in lines], dtype=np.float64)
    return vectors, weights


def prototypes(lines: list[dict]) -> list[dict]:
    """One to three duration-weighted prototypes of one character's lines.

    One person shouting and the same person calm can sit far apart; averaging
    them gives a print that matches neither. With enough lines the anchors are
    split by a small deterministic spherical k-means (farthest-point start), and
    a split is kept only when each part has lines enough to stand on.
    """
    import numpy as np

    vectors, weights = _weighted(lines)
    total = {"sum": [round(float(x), 5) for x in (vectors * weights[:, None]).sum(axis=0)],
             "n": len(lines), "weight": round(float(weights.sum()), 3)}
    if len(lines) < PROTOTYPE_MIN_LINES:
        return [total]
    centres = [vectors[int(np.argmax(weights))]]
    for _ in range(2):
        distance = 1 - np.max(vectors @ np.asarray(centres).T, axis=1)
        centres.append(vectors[int(np.argmax(distance))])
    best = [total]
    for k in (2, 3):
        chosen = np.asarray(centres[:k])
        for _ in range(8):
            assigned = np.argmax(vectors @ chosen.T, axis=1)
            new = []
            for g in range(k):
                members = vectors[assigned == g]
                if not len(members):
                    new.append(chosen[g])
                    continue
                mean = (members * weights[assigned == g][:, None]).sum(axis=0)
                new.append(mean / (np.linalg.norm(mean) or 1.0))
            chosen = np.asarray(new)
        sizes = [int((assigned == g).sum()) for g in range(k)]
        if min(sizes) < PROTOTYPE_MIN_SHARE:
            break
        best = [total] + [{
            "sum": [round(float(x), 5) for x in
                    (vectors[assigned == g] * weights[assigned == g][:, None]).sum(axis=0)],
            "n": sizes[g], "weight": round(float(weights[assigned == g].sum()), 3)}
            for g in range(k)]
    return best


def remember_series(db, series_id: str, revision_id: str, sidecar: dict | None,
                    labels: dict[str, str], language: str) -> dict[str, int]:
    """Teach a series what this revision's identified voices sound like.

    `labels` maps a voice group to a character id. Re-teaching a revision
    replaces what it taught before, so naming again never counts twice.
    """
    if not sidecar or not sidecar.get("model"):
        return {}
    key = series_key(series_id)
    doc = (db.load_plan(key) or {}).get("plan") or {}
    partitions = dict(doc.get("partitions") or {})
    part = dict(partitions.get(partition(sidecar["model"], language)) or {})
    grouped: dict[str, list[dict]] = {}
    for line in _anchors(sidecar.get("lines") or []):
        character = labels.get(line.get("speaker") or "")
        if character:
            grouped.setdefault(character, []).append(line)
    taught = {character: {"protos": prototypes(lines), "n": len(lines)}
              for character, lines in grouped.items()}
    if taught:
        part[revision_id] = taught
    else:
        part.pop(revision_id, None)
    partitions[partition(sidecar["model"], language)] = part
    doc.update(version=PRINTS_VERSION, partitions=partitions)
    db.save_plan(key, series_id, doc)
    return {character: int(len(grouped[character])) for character in taught}


def _entry_protos(entry: dict) -> list[dict]:
    # A legacy (migrated) entry is a single {sum, n}.
    return entry.get("protos") or [{"sum": entry["sum"], "n": entry.get("n", 1)}]


def prints_series(db, series_id: str, model: str, language: str,
                  exclude: set[str] | None = None) -> dict[str, dict]:
    """Every identified character of a series for one model and language.

    `exclude` drops revisions (the one being named, held-out evaluation
    episodes) so a voice is never matched against what it taught itself.
    """
    import numpy as np

    doc = (db.load_plan(series_key(series_id)) or {}).get("plan") or {}
    part = (doc.get("partitions") or {}).get(partition(model, language)) or {}
    totals: dict[str, dict] = {}
    for revision, taught in part.items():
        if exclude and revision in exclude:
            continue
        for character, entry in taught.items():
            protos = _entry_protos(entry)
            total = totals.setdefault(character, {"sum": None, "n": 0, "episodes": 0,
                                                  "protos": []})
            mean = np.asarray(protos[0]["sum"], dtype=np.float64)
            total["sum"] = mean if total["sum"] is None else total["sum"] + mean
            total["n"] += int(entry.get("n", protos[0].get("n", 1)))
            total["episodes"] += 1
            for proto in protos[1:]:
                vector = np.asarray(proto["sum"], dtype=np.float64)
                norm = float(np.linalg.norm(vector))
                if norm:
                    total["protos"].append(vector / norm)
    out = {}
    for character, total in totals.items():
        norm = float(np.linalg.norm(total["sum"]))
        if norm:
            out[character] = {"vector": total["sum"] / norm, "protos": total["protos"],
                              "lines": total["n"], "episodes": total["episodes"]}
    return out


def similarity(vector, known: dict, use_prototypes: bool = True) -> float:
    """Cosine of a group mean to a character: its print, or its closest prototype."""
    import numpy as np

    scores = [float(vector @ known["vector"])]
    if use_prototypes:
        scores += [float(vector @ p) for p in known.get("protos") or []]
    return max(scores) if scores else float(np.nan)


def suggest_series(db, series_id: str, revision_id: str, sidecar: dict | None,
                   named: set[str], language: str, top: int = 3,
                   exclude: set[str] | None = None,
                   use_prototypes: bool = False) -> dict[str, list[dict]]:
    """For each unidentified group, the series' characters it sounds closest to,
    with the margin to the next one (a small margin is a weak suggestion).

    Prototypes are stored but not used by default: on the hand-labelled anime
    episode, leave-one-out recognition fell from 0.966 to 0.938 top-1 with
    them, so the single duration-weighted print stays the default until a
    larger evaluation says otherwise."""
    import numpy as np

    if not sidecar or not sidecar.get("model"):
        return {}
    known = prints_series(db, series_id, sidecar["model"], language,
                          exclude={revision_id, *(exclude or set())})
    if not known:
        return {}
    groups: dict[str, list] = {}
    for line in _anchors(sidecar.get("lines") or []):
        label = line.get("speaker") or ""
        if label and label not in named:
            groups.setdefault(label, []).append(np.asarray(line["vector"], dtype=np.float64))
    out: dict[str, list[dict]] = {}
    for label, vectors in groups.items():
        mean = np.mean(vectors, axis=0)
        norm = float(np.linalg.norm(mean))
        if not norm:
            continue
        mean = mean / norm
        ranked = sorted(((similarity(mean, p, use_prototypes), character, p)
                         for character, p in known.items()), key=lambda r: -r[0])
        picks = []
        for i, (score, character, p) in enumerate(ranked[:top]):
            if score < FLOOR:
                continue
            following = ranked[i + 1][0] if i + 1 < len(ranked) else None
            picks.append({"character_id": character, "similarity": round(score, 3),
                          "margin": round(score - following, 3) if following is not None
                          else None, "lines": p["lines"], "episodes": p["episodes"],
                          "group_lines": len(vectors)})
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
