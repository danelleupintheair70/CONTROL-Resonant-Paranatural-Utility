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

    @api.put("/api/voice-catalog/traits")
    def save_traits(body: Traits):
        if not any(v["key"] == body.key for v in catalog()["voices"]):
            raise HTTPException(404, "Voice not found")
        db.save_plan("voice-traits:" + body.key, "Voice traits", body.model_dump(exclude={"key"}))
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
