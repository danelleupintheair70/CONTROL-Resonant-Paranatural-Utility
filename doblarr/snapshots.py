"""What has been analysed for one source revision, and whether it still holds.

An analysis snapshot is keyed by the *content* that was analysed (a source
revision, doblarr.identity) and the language it was heard in, never by a file
name. It records each stage separately:

- ``done``: produced, with the fingerprint of what it was produced from;
- ``failed``: tried, with the error;
- ``stale``: produced, but something it depends on changed since;
- ``unsupported``: this machine cannot run it (a model or a library is missing);
- ``skipped``: not asked for;
- ``missing``: never run.

A snapshot can be partial. A missing visual stage does not make the audio
analysis incomplete, and a failed visual stage does not erase it. Invalidation
follows the declared dependencies only: regrouping speakers makes the speaker
baselines and anything built on them stale, but not the energy curves, which
depend on the audio and the line spans and not on who was said to speak them.
"""

from __future__ import annotations

from .artifacts import digest
from .studio import records

STAGES: dict[str, tuple[str, ...]] = {
    # stage: what it depends on
    "probe": (),
    "separate": ("probe",),
    "transcribe": ("separate",),
    "diarize": ("transcribe",),
    "measure": ("transcribe",),
    "baselines": ("measure", "diarize"),
    "analyze": ("transcribe",),
    "features": ("transcribe",),
    "speaker_memory": ("diarize",),
    "shots": ("probe",),
    "faces": ("shots",),
    "tracks": ("faces",),
    "active_speaker": ("tracks", "features"),
    "association": ("active_speaker", "diarize"),
    "scenes": ("shots", "transcribe"),
    "knowledge": ("transcribe",),
    "emotion": ("transcribe",),
    "reader": ("diarize",),
}
AUDIO_STAGES = ("probe", "separate", "transcribe", "diarize", "measure", "baselines",
                "analyze", "features", "speaker_memory")
VISUAL_STAGES = ("shots", "faces", "tracks", "active_speaker", "association", "scenes")
STATES = ("done", "failed", "stale", "unsupported", "skipped", "missing", "running")


def snapshot_id(revision_id: str, language: str) -> str:
    return "snap-" + digest([revision_id, (language or "").lower()])[:16]


def get(db, revision_id: str, language: str) -> dict | None:
    return records.get(db, "snapshot", snapshot_id(revision_id, language))


def dependents(stage: str) -> list[str]:
    """Every stage that depends on `stage`, directly or not."""
    out: list[str] = []
    frontier = [stage]
    while frontier:
        current = frontier.pop()
        for name, needs in STAGES.items():
            if current in needs and name not in out:
                out.append(name)
                frontier.append(name)
    return out


def record_stage(db, revision_id: str, language: str, stage: str, state: str, *,
                 inputs=None, outputs: dict | None = None, version: str = "",
                 metrics: dict | None = None, error: str = "", identity: dict | None = None,
                 attempts: int = 4) -> dict:
    """Write one stage's result and mark what depended on its old result stale."""
    if stage not in STAGES:
        raise ValueError(f"unknown analysis stage {stage!r}")
    if state not in STATES:
        raise ValueError(f"unknown stage state {state!r}")
    record_id = snapshot_id(revision_id, language)
    fingerprint = digest(inputs)[:16] if inputs is not None else ""
    for _ in range(attempts):
        current = records.get(db, "snapshot", record_id) or {}
        stages = {k: dict(v) for k, v in (current.get("stages") or {}).items()}
        previous = stages.get(stage) or {}
        entry = {"state": state, "inputs": fingerprint, "version": version,
                 "outputs": outputs or {}, "metrics": metrics or {}, "error": error[:500],
                 "at": records.now_marker(),
                 "after": {need: (stages.get(need) or {}).get("inputs", "")
                           for need in STAGES[stage]}}
        stages[stage] = entry
        changed = state == "done" and (previous.get("inputs") != fingerprint
                                       or previous.get("version") != version)
        if changed:
            for name in dependents(stage):
                if (stages.get(name) or {}).get("state") == "done":
                    stages[name] = {**stages[name], "state": "stale",
                                    "reason": f"{stage} changed"}
        document = {**{k: v for k, v in current.items()
                       if k not in ("id", "revision", "scope", "updated_at")},
                    "revision_id": revision_id, "language": language, "stages": stages}
        if identity:
            document["identity"] = {**(current.get("identity") or {}), **identity}
        try:
            return records.put(db, "snapshot", record_id, document, scope=revision_id,
                               base_revision=current.get("revision", 0))
        except records.StudioConflict:
            continue
    raise records.StudioConflict("the analysis snapshot kept changing; try again")


def invalidate(db, revision_id: str, language: str, stage: str, reason: str) -> dict | None:
    """Mark a stage and everything after it stale (a correction, a new cut)."""
    current = get(db, revision_id, language)
    if current is None:
        return None
    stages = {k: dict(v) for k, v in (current.get("stages") or {}).items()}
    for name in [stage, *dependents(stage)]:
        if (stages.get(name) or {}).get("state") == "done":
            stages[name] = {**stages[name], "state": "stale", "reason": reason}
    return records.update(db, "snapshot", current["id"], {"stages": stages},
                          base_revision=current["revision"])


def coverage(snapshot: dict | None, unsupported: dict[str, str] | None = None) -> list[dict]:
    """Every stage with its state, for a page that must not look complete when
    it is not. `unsupported` names stages this machine cannot run, and why."""
    stages = (snapshot or {}).get("stages") or {}
    out = []
    for name in STAGES:
        entry = stages.get(name) or {}
        state = entry.get("state") or "missing"
        reason = entry.get("reason") or entry.get("error") or ""
        why = (unsupported or {}).get(name)
        if why and state in ("missing", "skipped"):
            state, reason = "unsupported", why
        out.append({"stage": name, "state": state, "reason": reason,
                    "version": entry.get("version", ""), "at": entry.get("at", ""),
                    "group": "visual" if name in VISUAL_STAGES else
                    "knowledge" if name in ("knowledge", "reader") else
                    "emotion" if name == "emotion" else "audio",
                    "metrics": entry.get("metrics") or {}})
    return out


def rerunnable(snapshot: dict | None) -> list[str]:
    """Stages a person can rerun on their own: failed or stale ones."""
    stages = (snapshot or {}).get("stages") or {}
    return [name for name in STAGES
            if (stages.get(name) or {}).get("state") in ("failed", "stale")]
