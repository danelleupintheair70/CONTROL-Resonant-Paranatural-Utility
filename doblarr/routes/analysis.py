"""An analysed episode: every line, who says it, how, and in which words.

The analysis itself is a queued run (`kind="analyze"`, see doblarr.analysis);
these routes read what it left beside the script, let a person hear any line
and name the voices it found. Names are kept per episode file: a voice group
(SPEAKER_03) is only an identity within the episode it was found in. Naming
also tags the voice for the whole show (doblarr.voice_tags), so unnamed
groups here and in later episodes are offered the nearest names, and an
episode can be grouped again with other voice models (doblarr.voice_models).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import speakers, speaking, voice_models, voice_tags

MAX_CLIP = 30.0
CLIP_CACHE = 400          # watched clips kept on disk, newest first
VIDEO_HEIGHT = 540        # clips are for recognising who talks, not for archiving


class NamesIn(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    names: dict[str, str] = Field(default_factory=dict)


class LineIn(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    cue: str = Field(min_length=1, max_length=200)
    # A character from the cast or a new one; blank: a new voice nobody named yet.
    character: str = Field(default="", max_length=80)


class RegroupIn(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    models: list[str] = Field(default_factory=list, max_length=4)
    threshold: float | None = Field(default=None, gt=0, lt=2)
    tracks: list[int] | None = Field(default=None, max_length=8)   # None: the setting


def names_key(path: str) -> str:
    """Names follow the episode file wherever a run read it from."""
    return "speaker-names:" + Path(str(path).replace("\\", "/")).name.casefold()


def load_plan(db, path: str) -> dict:
    return ((db.load_plan(names_key(path)) or {}).get("plan") or {})


def load_names(db, path: str) -> dict[str, str]:
    return load_plan(db, path).get("names") or {}


def save_names(db, path: str, names: dict[str, str], lines: dict[str, str] | None = None):
    """Names per voice group, and the lines a person moved by hand (by cue, so
    they can be moved again after the lines are regrouped)."""
    kept = (load_plan(db, path).get("lines") or {}) if lines is None else lines
    db.save_plan(names_key(path), Path(path).name, {"names": names, "lines": kept})


def label_for(names: dict[str, str], labels: set[str], character: str) -> tuple[str, bool]:
    """The voice group a character's lines go to: theirs, or a new one."""
    if character:
        for label, name in sorted(names.items()):
            if name.casefold() == character.casefold():
                return label, False
    taken = {int(x[8:]) for x in labels | set(names) if x[8:].isdigit()}
    return f"SPEAKER_{max(taken, default=-1) + 1:02d}", True


def sidecar(script: Path, suffix: str) -> Path | None:
    """`<stem>.<suffix>` next to the script or in the media folder above it."""
    stem = script.name.removesuffix(".script.json")
    for folder in (script.parent, *script.parents[:3]):
        found = folder / f"{stem}.{suffix}"
        if found.is_file():
            return found
    return None


def build_router(config, store) -> APIRouter:
    api = APIRouter()
    db = store.db

    def locate(path: str) -> Path:
        script = speaking.find_script(config.work_dir, path)
        if script is None:
            raise HTTPException(404, "This episode has not been analysed yet")
        return script

    def running(path: str) -> dict | None:
        return next((j for j in store.list() if j.get("kind") == "analyze"
                     and j.get("status") in ("queued", "running")
                     and Path(str(j.get("input_file") or "")).name.casefold()
                     == Path(path.replace("\\", "/")).name.casefold()), None)

    @api.get("/api/voice-models")
    def list_voice_models():
        return {"models": voice_models.describe(config),
                "folder": str(voice_models.folder(config))}

    @api.get("/api/analysis")
    def get_analysis(path: str):
        active = running(path)
        script = speaking.find_script(config.work_dir, path)
        if script is None:
            return {"analysed": False, "job": active and {k: active.get(k) for k in (
                "id", "status", "stage", "progress")}}
        data = json.loads(script.read_text(encoding="utf-8"))
        extra_path = sidecar(script, "analysis.json")
        extra = json.loads(extra_path.read_text(encoding="utf-8")) if extra_path else {}
        by_cue = {row["cue"]: row for row in extra.get("lines") or []}
        names = load_names(db, path)
        moved_lines = load_plan(db, path).get("lines") or {}
        lines = []
        for seg in data.get("segments") or []:
            cue = (seg.get("cue") or {})
            row = by_cue.get(cue.get("cue_id"), {})
            level = (cue.get("measurement") or {}).get("relative_db")
            lines.append({
                "index": seg.get("index"), "start": seg.get("start"), "end": seg.get("end"),
                "cue": cue.get("cue_id"),
                "moved": str(cue.get("cue_id")) in moved_lines,
                "speaker": seg.get("speaker"),
                "character": names.get(seg.get("speaker") or "", ""),
                "text": seg.get("text_src") or "", "original_text": row.get("original_text"),
                "relative_db": level, "band": speaking.band(level),
                "pitch_hz": row.get("pitch_hz"), "movement_st": row.get("movement_st"),
                "uncertain": "speaker_uncertain" in (seg.get("issues") or []),
            })
        summary = speaking.talk_share([{"id": 0, "label": "", "segments": [
            {**s, "speaker": names.get(s.get("speaker") or "", "") or s.get("speaker")}
            for s in data.get("segments") or []]}])
        grouped = voice_tags.read_sidecar(sidecar(script, "speakers.json"))
        return {"analysed": True, "lines": lines, "names": names,
                "model": (grouped or {}).get("model"),
                "grouped_tracks": (grouped or {}).get("tracks") or [],
                "cast": voice_tags.cast(db, path, names),
                "suggestions": voice_tags.suggest(db, path, grouped, names),
                "speakers": summary["speakers"], "total_seconds": summary["total_seconds"],
                "languages": {"text": data.get("script_lang"),
                              "original": extra.get("source_lang"),
                              "original_text": bool(extra.get("original_text"))},
                "measured": bool(extra), "job": active and {k: active.get(k) for k in (
                    "id", "status", "stage", "progress")}}

    @api.put("/api/analysis/names")
    def put_names(body: NamesIn):
        clean = {k: v.strip()[:80] for k, v in body.names.items()
                 if k.startswith("SPEAKER_") and v.strip()}
        save_names(db, body.path, clean)
        script = speaking.find_script(config.work_dir, body.path)
        tagged = voice_tags.remember(
            db, body.path, voice_tags.read_sidecar(script and sidecar(script, "speakers.json")),
            clean)
        return {"names": clean, "tagged": tagged}

    @api.put("/api/analysis/line")
    def move_line(body: LineIn):
        """One line, said by someone the grouping got wrong: a side character
        it filed under a main character, or a voice it never found."""
        if running(body.path):
            raise HTTPException(409, "This episode is being analysed; wait for it to finish")
        script = locate(body.path)
        data = json.loads(script.read_text(encoding="utf-8"))
        cues = {str((seg.get("cue") or {}).get("cue_id")) for seg in data.get("segments") or []}
        if body.cue not in cues:
            raise HTTPException(404, "no such line in this episode")
        names = load_names(db, body.path)
        # "mina" is Mina: the cast's spelling, never a second character.
        known = {n.casefold(): n for n in [*names.values(),
                                            *(c["name"] for c in voice_tags.cast(db, body.path))]}
        character = " ".join(body.character.split())
        character = known.get(character.casefold(), character)
        labels = {str(seg.get("speaker")) for seg in data.get("segments") or []}
        label, new = label_for(names, labels, character)
        if new and character:
            names[label] = character
        speakers.move_lines(script, sidecar(script, "speakers.json"), {body.cue: label})
        lines = dict(load_plan(db, body.path).get("lines") or {})
        if character:
            lines[body.cue] = character
        else:
            lines.pop(body.cue, None)
        save_names(db, body.path, names, lines)
        voice_tags.remember(db, body.path,
                            voice_tags.read_sidecar(sidecar(script, "speakers.json")), names)
        return {"speaker": label, "character": character, "new_voice": new}

    @api.post("/api/analysis/regroup")
    def regroup(body: RegroupIn):
        """Sort the lines into voices again with other models, in seconds:
        the separated dialogue is already on disk. Names follow their lines."""
        if running(body.path):
            raise HTTPException(409, "This episode is being analysed; wait for it to finish")
        script = locate(body.path)
        vocals = sidecar(script, "vocals.wav")
        if vocals is None:
            raise HTTPException(404, "the separated dialogue is no longer on disk; analyse again")
        grouped = sidecar(script, "speakers.json") or (
            vocals.parent / f"{script.name.removesuffix('.script.json')}.speakers.json")
        try:
            models = voice_models.resolve(body.models or voice_models.chosen(config), config)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        identity = json.loads(script.read_text(encoding="utf-8")).get("identity") or {}
        wanted = body.tracks if body.tracks is not None else (
            config.get("speakers") or {}).get("tracks", "all")
        try:
            tracks = speakers.other_tracks(
                Path(str(identity.get("input") or "")), str(identity.get("source_lang") or ""),
                vocals.parent, script.name.removesuffix(".script.json"),
                [str(t) for t in wanted] if isinstance(wanted, list) else wanted)
        except OSError:
            tracks = []          # the video moved: the separated dialogue is enough
        try:
            before, after, seconds = speakers.regroup(
                script, vocals, grouped, models, voice_models.folder(config),
                body.threshold if body.threshold is not None
                else (config.get("speakers") or {}).get("threshold"), tracks=tracks)
        except (OSError, RuntimeError, ImportError) as exc:
            raise HTTPException(502, f"could not group with {voice_models.combined_id(models)}: "
                                f"{exc}") from exc
        names = voice_tags.carry_names(before, after, seconds, load_names(db, body.path))
        # Lines a person moved stay with the character they were given to.
        moves = {}
        for cue, character in (load_plan(db, body.path).get("lines") or {}).items():
            label, new = label_for(names, set(after) | set(moves.values()), character)
            if new and character:
                names[label] = character
            moves[cue] = label
        speakers.move_lines(script, grouped, moves)
        save_names(db, body.path, names)
        voice_tags.remember(db, body.path, voice_tags.read_sidecar(grouped), names)
        return {"model": voice_models.combined_id(models), "voices": len(set(after)),
                "names": names, "tracks": [stream for stream, _ in tracks]}

    def source_video(script: Path) -> Path:
        """The video the analysis ran on, from the script; never a client path."""
        data = json.loads(script.read_text(encoding="utf-8"))
        source = Path(str((data.get("identity") or {}).get("input") or ""))
        if not source.name or not source.is_file():
            raise HTTPException(404, "the episode's video is not reachable from here")
        return source

    audio_streams = speakers.audio_tracks

    @api.get("/api/analysis/tracks")
    def tracks(path: str):
        """The episode's audio tracks, to watch a line in any of them."""
        script = locate(path)
        source = source_video(script)
        streams = audio_streams(source)
        original = (json.loads(script.read_text(encoding="utf-8")).get("identity") or {}).get(
            "source_lang")
        default = next((s["stream"] for s in streams if s["lang"] == original),
                       streams[0]["stream"] if streams else None)
        return {"tracks": streams, "default": default}

    cutting = threading.Lock()

    @api.get("/api/analysis/video")
    def video(path: str, start: float, end: float, audio: int | None = None):
        """One stretch of the episode as a small MP4 any browser plays: the
        source may be 10-bit HEVC with four audio tracks; a clip is H.264 at
        540p with the one track asked for."""
        if end <= start or end - start > MAX_CLIP or start < 0:
            raise HTTPException(422, f"a clip is between 0 and {MAX_CLIP:.0f} seconds")
        script = locate(path)
        source = source_video(script)
        streams = audio_streams(source)
        if audio is not None and audio not in {s["stream"] for s in streams}:
            raise HTTPException(422, "no such audio track in this episode")
        cache = Path(config.work_dir) / "cache" / "clips"
        key = hashlib.sha1(f"{source}|{source.stat().st_mtime_ns}|{start:.2f}|{end:.2f}|"
                           f"{audio}".encode()).hexdigest()[:20]
        clip = cache / f"{key}.mp4"
        if not clip.is_file():
            cache.mkdir(parents=True, exist_ok=True)
            temp = cache / f"{key}.{threading.get_ident()}.part"
            mapping = ["-map", "0:v:0"] + (["-map", f"0:{audio}"] if audio is not None
                                           else ["-map", "0:a:0?"])
            result = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", str(source),
                 "-t", f"{end - start:.3f}", *mapping, "-sn",
                 "-vf", f"scale=-2:'min({VIDEO_HEIGHT},ih)'", "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart",
                 "-f", "mp4", str(temp)], capture_output=True, check=False)
            if result.returncode or not temp.is_file():
                temp.unlink(missing_ok=True)
                raise HTTPException(500, "could not cut the clip: "
                                    + result.stderr.decode(errors="replace")[-300:])
            temp.replace(clip)
            with cutting:
                kept = sorted(cache.glob("*.mp4"), key=lambda f: f.stat().st_mtime,
                              reverse=True)
                for old in kept[CLIP_CACHE:]:
                    old.unlink(missing_ok=True)
        return FileResponse(clip, media_type="video/mp4",
                            headers={"Cache-Control": "private, max-age=86400"})

    @api.get("/api/analysis/clip")
    def clip(path: str, start: float, end: float, track: str = "vocals"):
        """One line as audio: the separated dialogue, or the original mix."""
        if end <= start or end - start > MAX_CLIP or start < 0:
            raise HTTPException(422, f"a clip is between 0 and {MAX_CLIP:.0f} seconds")
        script = locate(path)
        stem = script.name.removesuffix(".script.json")
        source = (sidecar(script, "vocals.wav") if track == "vocals"
                  else sidecar(script, "source.wav"))
        if source is None:
            raise HTTPException(404, "the analysed audio is no longer on disk")
        try:
            source.resolve().relative_to(Path(config.work_dir).resolve())
        except ValueError as exc:
            raise HTTPException(403, "outside the work folder") from exc
        audio = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start - 0.15):.3f}",
             "-t", f"{end - start + 0.3:.3f}", "-i", str(source), "-ac", "1", "-ar", "24000",
             "-f", "wav", "-"], capture_output=True, check=False).stdout
        if not audio:
            raise HTTPException(500, f"could not cut {stem}")
        return Response(content=audio, media_type="audio/wav")

    return api
