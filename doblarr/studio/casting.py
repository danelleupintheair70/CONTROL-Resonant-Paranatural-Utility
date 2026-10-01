"""Casting decisions with scope: series, then episode, then single line.

A series-level choice is inherited by every episode that has not decided
otherwise; an episode can override a character; a line can override its
episode. Exceptions are always visible — the effective cast says where each
choice came from — and changing a series choice first lists which episodes
would follow it and which keep their own.

The pipeline keeps reading the existing per-title voice cast. Applying a
decision writes that cast (the one authority the synthesizer already uses) and
queues only the affected character's lines; it does not create a second cast
store the pipeline would have to reconcile.
"""

from __future__ import annotations

import datetime as _dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..artifacts import digest
from . import records


class ChoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character: str = Field(min_length=1, max_length=80)
    scope: Literal["series", "episode", "line"]
    scope_ref: str = Field(min_length=1, max_length=2000)   # series id, title key, cue id
    episode_ref: str = Field(default="", max_length=2000)   # for a line choice
    voice: str = Field(default="", max_length=200)
    engine: str = Field(default="", max_length=40)
    direction: str = Field(default="", max_length=500)
    reference: str = Field(default="", max_length=64)
    audition: str = Field(default="", max_length=64)
    candidate: str = Field(default="", max_length=40)
    actor: str = Field(default="", max_length=100)
    # Shaping heard in the audition travels with the voice: semitones applied
    # to every line of the character after generation.
    pitch_semitones: float = Field(default=0.0, ge=-6.0, le=6.0)
    formant_semitones: float = Field(default=0.0, ge=-6.0, le=6.0)
    clear: bool = False


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def record_id(scope: str, ref: str) -> str:
    return f"cast-{scope}-" + digest(ref)[:16]


def decide(db, body: ChoiceIn, base_revision: int | None = None) -> dict:
    """Record one choice at one scope; `clear` removes it (the parent shows through)."""
    scope = "episode" if body.scope == "line" else body.scope
    ref = body.episode_ref if body.scope == "line" else body.scope_ref
    if body.scope == "line" and not body.episode_ref:
        raise ValueError("a line choice needs the episode it belongs to")
    rid = record_id(scope, ref)
    current = records.get(db, "casting", rid) or {"scope_kind": scope, "scope_ref": ref,
                                                   "characters": {}, "lines": {}}
    entry = {k: v for k, v in body.model_dump().items()
             if k in ("voice", "engine", "direction", "reference", "audition", "candidate",
                      "actor", "pitch_semitones", "formant_semitones") and v}
    entry["decided_at"] = _now()
    characters = dict(current.get("characters") or {})
    lines = dict(current.get("lines") or {})
    if body.scope == "line":
        if body.clear:
            lines.pop(body.scope_ref, None)
        else:
            lines[body.scope_ref] = {**entry, "character": body.character}
    elif body.clear:
        characters.pop(body.character, None)
    else:
        characters[body.character] = entry
    return records.put(db, "casting", rid, {**current, "characters": characters,
                                            "lines": lines},
                       scope=ref, base_revision=base_revision)


def effective(db, *, series_ref: str, episode_ref: str, speakers: list[str],
              mapping: dict | None = None) -> dict:
    """Each speaker's voice and where it came from; line exceptions listed."""
    mapping = dict(mapping or {})
    series = records.get(db, "casting", record_id("series", series_ref)) if series_ref else None
    episode = records.get(db, "casting", record_id("episode", episode_ref))
    rows = []
    for speaker in speakers:
        name = mapping.get(speaker, speaker)
        from_episode = ((episode or {}).get("characters") or {}).get(speaker)
        from_series = ((series or {}).get("characters") or {}).get(name)
        if from_episode:
            rows.append({"speaker": speaker, "character": name, "source": "episode",
                         **from_episode,
                         "overrides_series": bool(from_series),
                         "series_choice": from_series or None})
        elif from_series:
            rows.append({"speaker": speaker, "character": name, "source": "series",
                         **from_series})
        else:
            rows.append({"speaker": speaker, "character": name, "source": "none"})
    lines = [{"cue_id": cue, **choice}
             for cue, choice in ((episode or {}).get("lines") or {}).items()]
    return {"speakers": rows, "line_exceptions": lines,
            "series_revision": (series or {}).get("revision"),
            "episode_revision": (episode or {}).get("revision")}


def affected(db, *, series_ref: str, character: str, episodes: list[str]) -> dict:
    """Before changing a series choice: who follows it, who keeps their own."""
    follow: list[dict] = []
    keep: list[dict] = []
    for episode_ref in episodes:
        episode = records.get(db, "casting", record_id("episode", episode_ref)) or {}
        own = (episode.get("characters") or {}).get(character)
        line_overrides = [c for c, v in (episode.get("lines") or {}).items()
                          if v.get("character") == character]
        row = {"episode": episode_ref, "line_exceptions": len(line_overrides)}
        (keep if own else follow).append({**row, **({"voice": own.get("voice")} if own
                                                    else {})})
    return {"series": series_ref, "character": character, "follow": follow, "keep": keep,
            "note": ("Episodes that follow the series choice would use the new voice on their "
                     "next render. Nothing is re-rendered until you queue it; episodes and "
                     "lines with their own choice keep it.")}


def to_voice_cast(existing: list[dict], chosen: dict) -> list[dict]:
    """Merge effective choices into the pipeline's existing voice-cast entries."""
    by_speaker = {e["speaker_id"]: dict(e) for e in existing}
    for row in chosen.get("speakers", []):
        if row.get("source") == "none" or not row.get("voice"):
            continue
        entry = by_speaker.setdefault(row["speaker"], {
            "speaker_id": row["speaker"], "label": row["character"], "category": "speaker",
            "voice": "", "previewed": False})
        entry["voice"] = row["voice"]
        entry["previewed"] = True
        if row.get("engine"):
            entry["engine"] = row["engine"]
        if row.get("direction"):
            entry["delivery"] = row["direction"]
        # The choice decides the shaping outright: a voice picked without any
        # must not inherit a shift an earlier choice left on the entry.
        for key in ("pitch_semitones", "formant_semitones"):
            if row.get(key):
                entry[key] = row[key]
            else:
                entry.pop(key, None)
        # A new choice gets a new revision so cached takes of the old voice are
        # not reused for it.
        entry["revision"] = digest([row.get("voice"), row.get("engine"),
                                    row.get("direction"), row.get("reference"),
                                    row.get("pitch_semitones") or 0,
                                    row.get("formant_semitones") or 0])[:12]
    return list(by_speaker.values())
