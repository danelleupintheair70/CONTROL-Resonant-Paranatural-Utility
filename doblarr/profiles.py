"""A character's voice profile: what they sound like, how they perform, and proof.

A profile belongs to a character (doblarr.identity), not to a voice. One voice
asset can serve several characters and one character can have a voice per
language, age or edition; those links are casting choices (doblarr.studio
.casting), which already decide what the synthesizer uses. The profile holds
what stays true of the character across those choices, in twelve groups:

1. ``identity``     role and the variants it is cast in (names live on the character)
2. ``vocal``        perceived age, pitch range, timbre; character gender, vocal
                    presentation and verified performer metadata kept apart
3. ``locale``       desired locale/accent, languages, auditioned combinations
4. ``delivery``     default pace, energy, expressiveness, phrasing, register, direction
5. ``variations``   neutral, whisper, call, shout, ... each desired / supported /
                    auditioned independently
6. ``references``   labelled clips with source, transcript, quality and approval
7. ``pronunciation`` names, terms, catchphrases, register and honorifics per locale
8. ``dynamics``     measured ranges kept apart from desired ranges and bounds
9. ``templates``    favoured/discouraged template families by id, with conditions
10. ``engine``      actual provider/model/profile revision and supported controls
11. ``auditions``   verdicts tied to exact samples and settings
12. ``meta``        per-field provenance, freshness, confidence category and locks

Rules the code enforces:

- **Unknown is valid.** Nothing is required; enums carry ``unknown``.
- **Explicit updates.** A change names the fields it sets (dotted paths) and the
  revision it was made against; a stale write conflicts. Fields not named are
  left exactly as they were, so an older form can never erase newer fields.
- **Locks win.** A locked field is never changed by an inferred proposal. A
  person can still change it; the lock records that they decided.
- **Reading never generates.** Nothing here calls a speech service.
"""

from __future__ import annotations

import statistics
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .studio import records

PROFILE_VERSION = 1
VARIATIONS = ("neutral", "whisper", "call", "shout", "restrained", "excited", "sad",
              "exhausted", "nonverbal")
GROUPS = ("identity", "vocal", "locale", "delivery", "variations", "references",
          "pronunciation", "dynamics", "templates", "engine", "auditions", "meta")
Level = Literal["unknown", "low", "medium", "high"]
CONFIDENCE = ("measured", "inferred", "asserted", "imported")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Range(_Strict):
    low: float | None = None
    high: float | None = None
    units: str = ""


class Performer(_Strict):
    name: str = Field(default="", max_length=120)
    verified: bool = False            # only a person or an attributed source sets this
    source: str = Field(default="", max_length=300)


class Vocal(_Strict):
    perceived_age: Literal["unknown", "child", "teen", "young", "adult", "older"] = "unknown"
    pitch_range: Range = Field(default_factory=lambda: Range(units="Hz"))
    resonance: Level = "unknown"
    brightness: Literal["unknown", "dark", "neutral", "bright"] = "unknown"
    breathiness: Level = "unknown"
    raspiness: Level = "unknown"
    nasality: Level = "unknown"
    articulation: Literal["unknown", "slurred", "relaxed", "clear", "crisp"] = "unknown"
    character_gender: str = Field(default="unknown", max_length=40)
    vocal_presentation: Literal["unknown", "masculine", "feminine", "androgynous",
                                "varies"] = "unknown"
    performer: Performer = Field(default_factory=Performer)
    notes: str = Field(default="", max_length=1000)


class Audition(_Strict):
    language: str = Field(max_length=16)
    engine: str = Field(default="", max_length=60)
    verdict: Literal["untested", "good", "acceptable", "poor", "failed"] = "untested"


class Locale(_Strict):
    desired_locale: str = Field(default="", max_length=16)
    accent: str = Field(default="", max_length=120)
    languages: list[str] = Field(default_factory=list, max_length=20)
    auditioned: list[Audition] = Field(default_factory=list, max_length=50)


class Delivery(_Strict):
    pace: Literal["unknown", "slow", "measured", "average", "quick", "rapid"] = "unknown"
    energy: Level = "unknown"
    expressiveness: Level = "unknown"
    phrasing: str = Field(default="", max_length=300)
    pauses: Literal["unknown", "few", "some", "many"] = "unknown"
    speech_register: Literal["unknown", "casual", "neutral", "formal", "archaic",
                             "rough"] = "unknown"
    direction: str = Field(default="", max_length=500)


class Variation(_Strict):
    desired: bool | None = None
    supported: Literal["unknown", "yes", "no"] = "unknown"   # by the assigned engine
    auditioned: Literal["untested", "good", "acceptable", "poor", "failed"] = "untested"
    notes: str = Field(default="", max_length=300)


class ReferenceSource(_Strict):
    revision_id: str = Field(default="", max_length=64)
    stream: int | None = None
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    cue: str = Field(default="", max_length=64)
    edition: str = Field(default="", max_length=120)


class ReferenceQuality(_Strict):
    duration: float | None = None
    relative_db: float | None = None
    overlap: bool | None = None
    contaminated: bool | None = None
    clipped: bool | None = None
    note: str = Field(default="", max_length=300)


class Reference(_Strict):
    id: str = Field(default="", max_length=40)
    kind: Literal["neutral", "expressive"] = "neutral"
    variation: str = Field(default="neutral", max_length=20)
    role: Literal["voice", "performance"] = "voice"
    source: ReferenceSource
    transcript: str = Field(default="", max_length=600)
    provenance: str = Field(default="", max_length=300)
    quality: ReferenceQuality = Field(default_factory=ReferenceQuality)
    approved: bool = False
    retired: bool = False
    revision: int = 1

    @field_validator("variation")
    @classmethod
    def known(cls, value):
        if value not in VARIATIONS:
            raise ValueError(f"variation must be one of {', '.join(VARIATIONS)}")
        return value


class Term(_Strict):
    term: str = Field(min_length=1, max_length=120)
    spoken: str = Field(default="", max_length=200)
    locale: str = Field(default="", max_length=16)
    knowledge_entry: str = Field(default="", max_length=64)   # doblarr.knowledge entry id


class Pronunciation(_Strict):
    terms: list[Term] = Field(default_factory=list, max_length=200)
    catchphrases: list[str] = Field(default_factory=list, max_length=50)
    speech_register: str = Field(default="", max_length=200)
    honorifics: str = Field(default="", max_length=200)


class Dynamics(_Strict):
    measured: Range = Field(default_factory=lambda: Range(units="dB relative"))
    desired: Range = Field(default_factory=lambda: Range(units="dB relative"))
    max_boost_db: float | None = Field(default=None, ge=0, le=12)
    max_cut_db: float | None = Field(default=None, ge=0, le=24)
    envelope_strength: float | None = Field(default=None, ge=0, le=1.5)
    follow_source: Literal["unknown", "follow", "partly", "ignore"] = "unknown"
    exceptions: list[str] = Field(default_factory=list, max_length=50)


class TemplatePreference(_Strict):
    template: str = Field(min_length=1, max_length=80)        # shared template id
    conditions: str = Field(default="", max_length=300)
    strength: Range | None = None
    examples: list[str] = Field(default_factory=list, max_length=20)


class Templates(_Strict):
    favored: list[TemplatePreference] = Field(default_factory=list, max_length=50)
    discouraged: list[TemplatePreference] = Field(default_factory=list, max_length=50)


class Engine(_Strict):
    provider: str = Field(default="", max_length=60)
    model: str = Field(default="", max_length=120)
    profile: str = Field(default="", max_length=120)
    revision: str = Field(default="", max_length=64)
    supported_controls: list[str] = Field(default_factory=list, max_length=20)
    tested_settings: dict[str, Any] = Field(default_factory=dict)
    pitch_semitones: float = Field(default=0.0, ge=-6, le=6)
    formant_semitones: float = Field(default=0.0, ge=-6, le=6)
    unsupported: list[str] = Field(default_factory=list, max_length=50)


class AuditionRecord(_Strict):
    id: str = Field(default="", max_length=40)
    sample: str = Field(default="", max_length=300)     # artifact reference, never a path
    settings: dict[str, Any] = Field(default_factory=dict)
    language: str = Field(default="", max_length=16)
    context: str = Field(default="", max_length=300)
    verdict: Literal["good", "acceptable", "poor", "failed"] = "acceptable"
    reviewer: str = Field(default="", max_length=100)
    at: str = ""


class Identity(_Strict):
    role: Literal["unknown", "lead", "supporting", "minor", "narrator", "crowd"] = "unknown"
    variants: list[str] = Field(default_factory=list, max_length=20)   # character variant ids
    notes: str = Field(default="", max_length=500)


SECTION_MODELS: dict[str, type[BaseModel]] = {
    "identity": Identity, "vocal": Vocal, "locale": Locale, "delivery": Delivery,
    "pronunciation": Pronunciation, "dynamics": Dynamics, "templates": Templates,
    "engine": Engine,
}


def skeleton() -> dict:
    """An empty profile: every group present, every value unknown."""
    doc: dict[str, Any] = {name: model().model_dump() for name, model in SECTION_MODELS.items()}
    doc["variations"] = {v: Variation().model_dump() for v in VARIATIONS}
    doc["references"] = []
    doc["auditions"] = []
    doc["meta"] = {"fields": {}, "version": PROFILE_VERSION}
    return doc


def _merge_defaults(stored: dict) -> dict:
    base = skeleton()
    for group in GROUPS:
        if group not in stored:
            continue
        if isinstance(base[group], dict) and isinstance(stored[group], dict):
            merged = {**base[group], **stored[group]}
            base[group] = merged
        else:
            base[group] = stored[group]
    return base


def get(db, character_id: str) -> dict:
    """The stored profile over the empty skeleton (never None; never generates)."""
    stored = records.get(db, "profile", character_id)
    profile = _merge_defaults(stored or {})
    profile["character_id"] = character_id
    profile["revision"] = stored["revision"] if stored else 0
    profile["updated_at"] = stored.get("updated_at") if stored else None
    return profile


class ProfileConflict(records.StudioConflict):
    pass


def _split(path: str) -> list[str]:
    parts = [p for p in str(path).split(".") if p]
    if not parts or parts[0] not in GROUPS or parts[0] == "meta":
        raise ValueError(f"unknown profile field {path!r}")
    return parts


def _assign(doc: dict, parts: list[str], value) -> None:
    target = doc
    for key in parts[:-1]:
        if key not in target or not isinstance(target[key], dict):
            target[key] = {}
        target = target[key]
    target[parts[-1]] = value


def validate(doc: dict) -> dict:
    """Every group checked against its schema; returns the normalised document."""
    out = dict(doc)
    for name, model in SECTION_MODELS.items():
        out[name] = model.model_validate(doc.get(name) or {}).model_dump()
    variations = doc.get("variations") or {}
    unknown = set(variations) - set(VARIATIONS)
    if unknown:
        raise ValueError(f"unknown variation(s) {', '.join(sorted(unknown))}")
    out["variations"] = {v: Variation.model_validate(variations.get(v) or {}).model_dump()
                         for v in VARIATIONS}
    out["references"] = [Reference.model_validate(r).model_dump()
                         for r in doc.get("references") or []]
    out["auditions"] = [AuditionRecord.model_validate(a).model_dump()
                        for a in doc.get("auditions") or []]
    meta = dict(doc.get("meta") or {})
    meta.setdefault("fields", {})
    meta["version"] = PROFILE_VERSION
    out["meta"] = meta
    return out


def update(db, character_id: str, *, set_fields: dict[str, Any] | None = None,
           lock: list[str] | None = None, unlock: list[str] | None = None,
           base_revision: int | None, source: str = "manual",
           confidence: str = "asserted", respect_locks: bool = False) -> dict:
    """Set named fields, lock or unlock them. Nothing else changes.

    `respect_locks` is for automatic writers (inferred proposals): a locked
    field is skipped and reported instead of being overwritten.
    """
    if confidence not in CONFIDENCE:
        raise ValueError(f"confidence must be one of {', '.join(CONFIDENCE)}")
    stored = records.get(db, "profile", character_id)
    current = stored["revision"] if stored else 0
    if base_revision is not None and int(base_revision) != current:
        raise ProfileConflict(
            f"the profile changed since revision {base_revision} (now {current}); "
            "reload it and apply your change again", get(db, character_id))
    doc = _merge_defaults(stored or {})
    fields = dict((doc.get("meta") or {}).get("fields") or {})
    skipped: list[str] = []
    for path, value in (set_fields or {}).items():
        parts = _split(path)
        key = ".".join(parts)
        if respect_locks and any((fields.get(k) or {}).get("locked") for k in
                                 _prefixes(key)):
            skipped.append(key)
            continue
        _assign(doc, parts, value)
        fields[key] = {**(fields.get(key) or {}), "source": source, "confidence": confidence,
                       "at": records.now_marker()}
    for path in lock or []:
        key = ".".join(_split(path))
        fields[key] = {**(fields.get(key) or {}), "locked": True, "at": records.now_marker()}
    for path in unlock or []:
        key = ".".join(_split(path))
        if key in fields:
            fields[key] = {**fields[key], "locked": False}
    doc["meta"] = {**(doc.get("meta") or {}), "fields": fields}
    try:
        checked = validate(doc)
    except ValidationError as exc:
        raise ValueError(_first_error(exc)) from exc
    body = {k: checked[k] for k in GROUPS}
    saved = records.put(db, "profile", character_id, body, base_revision=current)
    result = get(db, character_id)
    result["skipped_locked"] = skipped
    result["revision"] = saved["revision"]
    return result


def _prefixes(key: str) -> list[str]:
    parts = key.split(".")
    return [".".join(parts[:n]) for n in range(1, len(parts) + 1)]


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    return f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"


def locked(profile: dict, path: str) -> bool:
    fields = (profile.get("meta") or {}).get("fields") or {}
    return any((fields.get(k) or {}).get("locked") for k in _prefixes(path))


# --------------------------------------------------------------------------
# References and auditions
# --------------------------------------------------------------------------

def add_reference(db, character_id: str, reference: dict, *, base_revision: int | None) -> dict:
    ref = Reference.model_validate({**reference, "id": reference.get("id")
                                    or "ref-" + uuid.uuid4().hex[:10]}).model_dump()
    profile = get(db, character_id)
    refs = [r for r in profile["references"] if r["id"] != ref["id"]] + [ref]
    return update(db, character_id, set_fields={"references": refs},
                  base_revision=base_revision)


def review_reference(db, character_id: str, reference_id: str, *, approved: bool | None = None,
                     retired: bool | None = None, base_revision: int | None) -> dict:
    profile = get(db, character_id)
    refs = []
    found = False
    for ref in profile["references"]:
        if ref["id"] == reference_id:
            found = True
            ref = {**ref, "revision": int(ref.get("revision", 1)) + 1}
            if approved is not None:
                ref["approved"] = bool(approved)
            if retired is not None:
                ref["retired"] = bool(retired)
        refs.append(ref)
    if not found:
        raise KeyError(reference_id)
    return update(db, character_id, set_fields={"references": refs},
                  base_revision=base_revision)


def coverage(profile: dict) -> dict:
    """Which variations have approved references: one lively clip is not a range."""
    approved = [r for r in profile.get("references") or [] if r.get("approved")
                and not r.get("retired")]
    by_variation: dict[str, int] = {}
    for ref in approved:
        by_variation[ref["variation"]] = by_variation.get(ref["variation"], 0) + 1
    return {"approved": len(approved), "by_variation": by_variation,
            "neutral": by_variation.get("neutral", 0) > 0,
            "expressive": sum(n for v, n in by_variation.items() if v != "neutral") > 0}


def record_audition(db, character_id: str, audition: dict, *,
                    base_revision: int | None) -> dict:
    """Keep a verdict tied to the exact sample and settings it was about."""
    entry = AuditionRecord.model_validate({**audition, "id": audition.get("id")
                                           or "aud-" + uuid.uuid4().hex[:10],
                                           "at": audition.get("at") or records.now_marker()})
    profile = get(db, character_id)
    return update(db, character_id,
                  set_fields={"auditions": [*profile["auditions"], entry.model_dump()]},
                  base_revision=base_revision)


# --------------------------------------------------------------------------
# Engine capabilities: what the assigned engine can really do
# --------------------------------------------------------------------------

def engine_capabilities(speech, engine: str) -> dict:
    """Capabilities reported by the speech adapter, never inferred from tags.

    Reading capabilities is a metadata question; it never asks for audio.
    """
    controls = []
    unsupported = []
    try:
        direction = bool(speech.supports_direction(engine))
    except Exception:  # noqa: BLE001 - an adapter without the query: unknown
        direction = None
    try:
        cloning = speech.supports_cloning(engine)
    except Exception:  # noqa: BLE001
        cloning = None
    if direction:
        controls.append("direction")
    elif direction is False:
        unsupported.append("delivery direction")
    if cloning:
        controls.append("cloning")
    # Pitch and formant shaping run in Doblarr after generation (studio casting),
    # so they are available whatever the engine.
    controls += ["pitch_semitones", "formant_semitones"]
    return {"engine": engine, "direction": direction, "cloning": cloning,
            "supported_controls": controls, "unsupported": unsupported}


def variation_support(capabilities: dict) -> dict[str, str]:
    """Which variations an engine can be *asked* for. Without a direction
    control only the reference's own delivery is available; that is
    reported as unsupported rather than promised."""
    direction = capabilities.get("direction")
    out = {}
    for variation in VARIATIONS:
        if variation == "neutral":
            out[variation] = "yes"
        elif direction is None:
            out[variation] = "unknown"
        else:
            out[variation] = "yes" if direction else "no"
    return out


# --------------------------------------------------------------------------
# Inferred proposals from analyses (reviewed in bulk, never applied silently)
# --------------------------------------------------------------------------

def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))], 1)


def proposals_from_lines(lines: list[dict]) -> list[dict]:
    """Field proposals from a character's analysed lines.

    `lines` are rows with ``pitch_hz``, ``relative_db``, ``band``, ``start``,
    ``end``, ``cue``, ``text`` and ``revision_id`` (see routes/characters).
    Each proposal names its evidence (how many lines, which measure) so a
    person can approve it knowing what it rests on.
    """
    out: list[dict] = []
    pitches = [float(r["pitch_hz"]) for r in lines if isinstance(r.get("pitch_hz"),
                                                                   int | float)]
    if len(pitches) >= 5:
        out.append({"id": "vocal.pitch_range", "field": "vocal.pitch_range",
                    "value": {"low": _quantile(pitches, 0.1), "high": _quantile(pitches, 0.9),
                              "units": "Hz"},
                    "evidence": f"10th-90th percentile of median pitch over {len(pitches)} lines",
                    "confidence": "measured"})
    levels = [float(r["relative_db"]) for r in lines
              if isinstance(r.get("relative_db"), int | float)]
    if len(levels) >= 5:
        out.append({"id": "dynamics.measured", "field": "dynamics.measured",
                    "value": {"low": _quantile(levels, 0.1), "high": _quantile(levels, 0.9),
                              "units": "dB relative"},
                    "evidence": f"10th-90th percentile of level against the speaker baseline "
                                f"over {len(levels)} measured lines",
                    "confidence": "measured"})
    bands: dict[str, int] = {}
    for row in lines:
        bands[row.get("band") or "unmeasured"] = bands.get(row.get("band") or "unmeasured",
                                                           0) + 1
    measured = sum(n for b, n in bands.items() if b != "unmeasured")
    if measured >= 8:
        share = bands.get("intense", 0) / measured
        energy = "high" if share >= 0.3 else "low" if share <= 0.05 else "medium"
        out.append({"id": "delivery.energy", "field": "delivery.energy", "value": energy,
                    "evidence": f"{bands.get('intense', 0)} of {measured} measured lines are "
                                "intense against the speaker's own baseline",
                    "confidence": "inferred"})
        if bands.get("intense", 0) >= 2:
            out.append({"id": "variations.shout.desired", "field": "variations.shout.desired",
                        "value": True, "evidence": f"{bands['intense']} intense lines heard",
                        "confidence": "inferred"})
        if bands.get("quiet", 0) >= 2:
            out.append({"id": "variations.restrained.desired",
                        "field": "variations.restrained.desired", "value": True,
                        "evidence": f"{bands['quiet']} quiet lines heard",
                        "confidence": "inferred"})
    # Reference candidates: the longest clean lines per band (a calm one is a
    # neutral reference, an intense one an expressive reference).
    for band, kind, variation in (("calm", "neutral", "neutral"),
                                  ("intense", "expressive", "excited"),
                                  ("quiet", "expressive", "restrained")):
        pool = [r for r in lines if r.get("band") == band and not r.get("uncertain")
                and float(r["end"]) - float(r["start"]) >= 1.5]
        for row in sorted(pool, key=lambda r: -(float(r["end"]) - float(r["start"])))[:2]:
            seconds = float(row["end"]) - float(row["start"])
            out.append({"id": f"reference:{row['revision_id']}:{row['cue']}",
                        "field": "references", "kind": "reference",
                        "value": {"kind": kind, "variation": variation, "role": "voice",
                                  "source": {"revision_id": row["revision_id"],
                                             "start": float(row["start"]),
                                             "end": float(row["end"]), "cue": row["cue"]},
                                  "transcript": str(row.get("original_text")
                                                    or row.get("text") or "")[:600],
                                  "provenance": "analysis: separated dialogue",
                                  "quality": {"duration": round(float(row["end"])
                                                                - float(row["start"]), 2),
                                              "relative_db": row.get("relative_db"),
                                              "overlap": None, "contaminated": None}},
                        "evidence": f"a clean {band} line of {seconds:.1f}s",
                        "confidence": "measured"})
    return out


def apply_proposals(db, character_id: str, proposals: list[dict], ids: list[str], *,
                    base_revision: int | None) -> dict:
    """Approve several proposals at once. Locked fields are skipped and reported."""
    chosen = [p for p in proposals if p["id"] in set(ids)]
    fields: dict[str, Any] = {}
    profile = get(db, character_id)
    refs = list(profile["references"])
    known = {(r["source"].get("revision_id"), r["source"].get("cue")) for r in refs}
    for proposal in chosen:
        if proposal.get("kind") == "reference":
            value = proposal["value"]
            key = (value["source"].get("revision_id"), value["source"].get("cue"))
            if key in known:
                continue
            refs.append(Reference.model_validate({**value, "id": "ref-" + uuid.uuid4().hex[:10],
                                                  "approved": True}).model_dump())
            known.add(key)
        else:
            fields[proposal["field"]] = proposal["value"]
    if refs != profile["references"]:
        fields["references"] = refs
    return update(db, character_id, set_fields=fields, base_revision=base_revision,
                  source="inferred-approved", confidence="measured", respect_locks=True)


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None
