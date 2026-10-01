"""Discover saved and engine-provided voices without generating or importing on read."""

import threading
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..cache import TTLCache
from ..clients.speech import SpeechError


class Choice(BaseModel):
    key: str = Field(min_length=1, max_length=300)


class Traits(Choice):
    age: Literal["unknown", "child", "young", "adult", "older"] = "unknown"
    gender: Literal["unknown", "male", "female", "neutral"] = "unknown"
    # Who this voice is. A clone made from a scene is named after the scene
    # and a hash; a person gives it the name it is known by, and the show and
    # character it belongs to, so the catalogue reads as a cast, not a list of ids.
    display_name: str = Field(default="", max_length=80)
    character: str = Field(default="", max_length=80)
    show: str = Field(default="", max_length=200)          # a library title key
    show_name: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=500)
    # The character's colour in the app (orb, dots, charts). App-only: it is
    # never sent to the speech service. "" lets the app pick one.
    color: str = Field(default="", pattern=r"^(#[0-9a-fA-F]{6})?$")


class Preview(Choice):
    language: str = Field(pattern=r"^[a-z]{2}$")
    text: str = Field(min_length=1, max_length=300)
    direction: str = Field(default="", max_length=500)


def build_router(config, services, db):
    api = APIRouter()
    cache = TTLCache(ttl=120)
    lock = threading.Lock()
    previews = TTLCache(ttl=3600, max_size=200)

    def catalog(refresh=False):
        cached = cache.get("voices") if not refresh else None
        if cached is not None:
            return cached
        vb = services.speech
        voices, warnings = [], []
        try:
            for p in vb.voice_profiles():
                voices.append(
                    {
                        "key": f"profile:{p['id']}",
                        "profile_id": p["id"],
                        "name": p["name"],
                        "language": p.get("language", ""),
                        "engine": p.get("preset_engine")
                        or p.get("default_engine")
                        or config["voicebox"].get("default_engine", "chatterbox"),
                        "kind": p.get("voice_type", "cloned"),
                        "description": p.get("description") or "",
                        "gender": "unknown",
                        "age": "unknown",
                    }
                )
        except SpeechError as e:
            warnings.append(str(e))
        for engine in vb.preset_engines:
            try:
                for p in vb.preset_voices(engine):
                    voices.append(
                        {
                            "key": f"preset:{engine}:{p['voice_id']}",
                            "preset_id": p["voice_id"],
                            "name": p["name"],
                            "engine": engine,
                            "kind": "preset",
                            "description": "",
                            "language": p.get("language", ""),
                            "gender": p.get("gender", "unknown"),
                            "age": "unknown",
                        }
                    )
            except SpeechError as e:
                warnings.append(f"{engine}: {e}")
        result = {"voices": voices, "warnings": warnings}
        cache.set("voices", result)
        return result

    def select(key):
        voice = next((v for v in catalog()["voices"] if v["key"] == key), None)
        if not voice:
            raise HTTPException(404, "Voice not found; refresh the catalog")
        with lock:
            pid = voice.get("profile_id")
            if not pid:
                pid = services.speech.register_preset(
                    {
                        "voice_id": voice["preset_id"],
                        "name": voice["name"],
                        "language": voice["language"],
                    },
                    voice["engine"],
                )
        return {
            "profile_id": pid,
            "engine": voice["engine"],
            "name": voice["name"],
            "language": voice["language"],
            "kind": voice["kind"],
        }

    @api.get("/api/voice-catalog")
    def get_catalog(refresh: bool = False):
        data = catalog(refresh)
        voices = []
        for voice in data["voices"]:
            traits = (db.load_plan("voice-traits:" + voice["key"]) or {}).get("plan", {})
            voices.append({**voice, **traits})
        return {**data, "voices": voices}

    @api.get("/api/voice-catalog/voice")
    def voice_detail(key: str):
        """One voice with its identity and everywhere it is cast."""
        voice = next((v for v in catalog()["voices"] if v["key"] == key), None)
        if voice is None:
            raise HTTPException(404, "Voice not found; refresh the catalog")
        traits = (db.load_plan("voice-traits:" + key) or {}).get("plan", {})
        profile = voice.get("profile_id")
        used = []
        for saved in db.list_casts() if profile else []:
            for entry in saved["cast"]:
                if entry.get("voice") != profile:
                    continue
                used.append({
                    "title_key": saved["title_key"], "title": saved["title"],
                    "speaker": entry.get("speaker_id"), "label": entry.get("label"),
                    "pitch_semitones": entry.get("pitch_semitones") or 0,
                    "formant_semitones": entry.get("formant_semitones") or 0,
                    "updated_at": saved["updated_at"],
                })
        return {"voice": {**voice, **traits}, "used_in": used}

    @api.put("/api/voice-catalog/traits")
    def save_traits(body: Traits):
        if not any(v["key"] == body.key for v in catalog()["voices"]):
            raise HTTPException(404, "Voice not found")
        # Only the fields this request set change. An older form that does not
        # know a field must not erase it, so the saved traits are merged, never
        # replaced. (The rich character profile lives apart, doblarr.profiles.)
        existing = (db.load_plan("voice-traits:" + body.key) or {}).get("plan", {})
        db.save_plan("voice-traits:" + body.key, "Voice traits",
                     {**existing, **body.model_dump(exclude={"key"}, exclude_unset=True)})
        return {"ok": True}

    @api.post("/api/voice-catalog/select")
    def select_voice(body: Choice):
        return select(body.key)

    @api.post("/api/voice-catalog/preview")
    def preview(body: Preview):
        chosen = next((v for v in catalog()["voices"] if v["key"] == body.key), None)
        if chosen and chosen["engine"] == "kokoro" and chosen["language"] != body.language:
            raise HTTPException(422, "Choose a preset in the requested language")
        if body.direction and chosen and not services.speech.supports_direction(chosen["engine"]):
            raise HTTPException(422, "This voice's engine does not accept a delivery direction")
        voice = select(body.key)
        gid = services.speech.generate(
            voice["profile_id"],
            body.text,
            body.language,
            engine=voice["engine"],
            instruct=body.direction or None,
        )
        previews.set(gid, True)
        return {"id": gid}

    @api.get("/api/voice-catalog/preview/{generation_id}")
    def preview_status(generation_id: str):
        if not previews.get(generation_id):
            raise HTTPException(404, "Preview expired")
        return services.speech.generation_status(generation_id)

    @api.get("/api/voice-catalog/preview/{generation_id}/audio")
    def preview_audio(generation_id: str):
        if not previews.get(generation_id):
            raise HTTPException(404, "Preview expired")
        return Response(content=services.speech.fetch_audio(generation_id),
                        media_type="audio/wav")

    return api
