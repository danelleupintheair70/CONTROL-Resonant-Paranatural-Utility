"""The optional visual pass of an episode analysis.

shots → faces → tracks → active speaker → association and scenes, each stage
cached by what it was computed from and recorded in the revision's snapshot
(doblarr.snapshots). A stage this machine cannot run is recorded as
unsupported with the reason; the audio analysis is never touched by it.

Frames are sampled at a bounded rate (at most `vision.max_frames` for the whole
title) and streamed; only detections, small face crops for thumbnails and
vectors are kept. Nothing is sent anywhere.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .. import identity, snapshots
from ..artifacts import digest, read_json, stamp
from . import active, association, capability, faces, media, references, scenes, tracks

log = logging.getLogger("doblarr.vision.pipeline")

VERSION = "visual/1"
SAMPLE_FPS = 2.0
CROP_SIZE = 96
MAX_TRACKS_PER_LINE = 3


def visual_path(work: Path, stem: str) -> Path:
    return Path(work) / f"{stem}.visual.json"


def _record(db, ident, language, stage, state, **kw):
    if db is not None and ident.get("revision_id"):
        snapshots.record_stage(db, ident["revision_id"], language, stage, state,
                               identity=ident, version=VERSION, **kw)


def run(job, work: Path, config, *, db=None, cancel=None, progress=None) -> dict:
    from ..stages.common import work_stem

    ident = job.metrics.get("identity") or {}
    language = job.source_lang or ""
    section = dict(config.get("vision", {}) or {})
    video = Path(job.input_file)
    out_path = visual_path(work, work_stem(job))
    saved = read_json(out_path)
    result: dict = {"version": VERSION, "stages": {}}
    if section.get("backend", "auto") == "off":
        for stage in ("shots", "faces", "tracks", "active_speaker", "association", "scenes"):
            _record(db, ident, language, stage, "skipped", error="vision.backend is off")
        return result
    if not video.is_file():
        for stage in ("shots", "faces", "tracks", "active_speaker", "association", "scenes"):
            _record(db, ident, language, stage, "failed", error="the video is not reachable")
        return result
    timings: dict[str, float] = {}

    # -- shots -------------------------------------------------------------
    started = time.perf_counter()
    shot_request = digest([stamp(video), media.SCENE_THRESHOLD, VERSION])[:16]
    if (saved.get("shots") or {}).get("request") == shot_request:
        shot_data = saved["shots"]
    else:
        shot_data = {**media.shots(video, cancel=cancel), "request": shot_request}
    result["shots"] = shot_data
    timings["shots"] = time.perf_counter() - started
    _record(db, ident, language, "shots", "done", inputs=shot_request,
            metrics={"shots": len(shot_data["shots"]), "seconds": round(timings["shots"], 1),
                     "method": shot_data["method"]})

    # -- faces -------------------------------------------------------------
    backend = faces.load(config, section.get("domain", "auto"))
    if not backend.detectors:
        why = "; ".join(f"{k}: {v}" for k, v in backend.unavailable.items())
        for stage in ("faces", "tracks", "active_speaker"):
            _record(db, ident, language, stage, "unsupported", error=why)
        result["stages"]["faces"] = {"state": "unsupported", "reason": why}
        _write(out_path, result)
        return result
    duration = shot_data["video"].get("duration") or 0.0
    height = int(section.get("frame_height", 360))
    fps = min(SAMPLE_FPS, max(0.05, int(section.get("max_frames", 4000)) / max(1.0, duration)))
    crops_dir = Path(work) / "vision" / (ident.get("revision_id") or work_stem(job)) / "crops"
    face_request = digest([stamp(video), fps, height, backend.describe(), VERSION])[:16]
    started = time.perf_counter()
    if (saved.get("faces") or {}).get("request") == face_request:
        face_data = saved["faces"]
    else:
        detections: list[dict] = []
        sampled = 0
        crops_dir.mkdir(parents=True, exist_ok=True)
        import cv2

        frame: Any
        for t, frame in media.frames(video, fps, height, cancel=cancel):
            sampled += 1
            for n, face in enumerate(faces.detect(backend, frame)):
                x, y, w, h = face.box
                crop = frame[max(0, y):y + h, max(0, x):x + w]
                name = ""
                if crop.size and len(detections) < 6000:
                    name = f"{int(t * 1000):08d}-{n}-{face.detector[:6]}.jpg"
                    cv2.imwrite(str(crops_dir / name),
                                cv2.resize(crop, (CROP_SIZE, CROP_SIZE)),
                                [cv2.IMWRITE_JPEG_QUALITY, 80])
                detections.append({"t": t, "box": list(face.box), "score": face.score,
                                   "detector": face.detector, "domain": face.domain,
                                   "vector": face.vector, "embedder": face.embedder,
                                   "crop": name})
            if progress is not None and sampled % 50 == 0:
                progress(sampled, max(1, int(duration * fps)), f"frame {sampled}")
        face_data = {"request": face_request, "fps": fps, "height": height,
                     "sampled": sampled, "backend": backend.describe(),
                     "detections": detections, "crops": str(crops_dir)}
    result["faces"] = face_data
    timings["faces"] = time.perf_counter() - started
    by_detector: dict[str, int] = {}
    for det in face_data["detections"]:
        by_detector[det["detector"]] = by_detector.get(det["detector"], 0) + 1
    _record(db, ident, language, "faces", "done", inputs=face_request,
            metrics={"frames": face_data["sampled"], "detections": len(face_data["detections"]),
                     "by_detector": by_detector, "seconds": round(timings["faces"], 1),
                     "unavailable": backend.unavailable})

    # -- tracks ------------------------------------------------------------
    revision_id = ident.get("revision_id") or work_stem(job)
    built = tracks.build(face_data["detections"], shot_data["shots"], revision_id)
    corrected = tracks.apply(db, revision_id, built) if db is not None else built
    refs = references.load(db, ident["series_id"])["references"] \
        if db is not None and ident.get("series_id") else []
    threshold = float(section.get("match_threshold", 0.55))
    for track in corrected:
        track["matches"] = references.match(track, refs, threshold)
    result["tracks"] = corrected
    _record(db, ident, language, "tracks", "done",
            inputs=[face_request, [t["id"] for t in built]],
            metrics={"tracks": len(corrected),
                     "assigned": sum(1 for t in corrected if t.get("assigned")),
                     "proposed": sum(1 for t in corrected
                                     if any(m.get("proposed") for m in t["matches"]))})

    # -- active speaker ----------------------------------------------------
    features_doc = read_json(Path((job.metrics.get("features") or {}).get("path") or ""))
    feature_rows = {row.get("cue"): row for row in features_doc.get("lines") or []}
    asd_fps = float(section.get("asd_fps", 8.0))
    saved_asd = (saved.get("active") or {})
    asd_request = digest([face_request, [t["id"] for t in corrected], asd_fps,
                          features_doc.get("request")])[:16]
    started = time.perf_counter()
    if saved_asd.get("request") == asd_request:
        speaking = saved_asd["lines"]
    else:
        speaking = {}
        lines = [s for s in job.segments if s.duration > 0.3]
        for n, seg in enumerate(lines):
            if cancel is not None and cancel.is_set():
                from ..errors import JobCancelled

                raise JobCancelled("cancelled during active-speaker analysis")
            visible = association.overlapping(corrected, seg.start, seg.end)
            visible = sorted(visible, key=lambda t: -t["frames"])[:MAX_TRACKS_PER_LINE]
            if not visible or seg.cue_id not in feature_rows:
                continue
            frames = media.span_frames(video, seg.start, seg.end, asd_fps, height, cancel)
            speaking[seg.cue_id] = {track["id"]: active.score(frames, track,
                                                              feature_rows[seg.cue_id],
                                                              seg.start, 1.0)
                                    for track in visible}
            if progress is not None and n % 10 == 0:
                progress(n, len(lines), f"line {n}/{len(lines)} mouth motion")
    result["active"] = {"request": asd_request, "fps": asd_fps, "method": active.METHOD,
                        "lines": speaking}
    timings["active_speaker"] = time.perf_counter() - started
    _record(db, ident, language, "active_speaker", "done", inputs=asd_request,
            metrics={"lines": len(speaking), "seconds": round(timings["active_speaker"], 1)})

    # -- scenes and association --------------------------------------------
    line_rows = [{"cue": s.cue_id, "start": s.start, "end": s.end} for s in job.segments]
    manual_scenes = scenes.corrections(db, revision_id) if db is not None else None
    scene_rows = scenes.group(shot_data["shots"], line_rows, duration, manual_scenes)
    result["scenes"] = scene_rows
    _record(db, ident, language, "scenes", "done",
            inputs=[shot_request, [r["cue"] for r in line_rows]],
            metrics={"scenes": len(scene_rows),
                     "uncertain": sum(1 for s in scene_rows if s["uncertain"])})
    result["associations"] = associate(db, job, ident, corrected, speaking, shot_data["shots"],
                                       scene_rows, section)
    states: dict[str, int] = {}
    for row in result["associations"]:
        states[row["decision"]["state"]] = states.get(row["decision"]["state"], 0) + 1
    _record(db, ident, language, "association", "done",
            inputs=[asd_request, len(result["associations"])],
            outputs={"visual": str(out_path)},
            metrics={"decisions": states,
                     "conflicts": sum(1 for r in result["associations"] if r["conflicts"])})
    result["timings"] = {k: round(v, 1) for k, v in timings.items()}
    result["capability"] = capability.status(config)
    _write(out_path, result)
    job.metrics["visual"] = {"path": str(out_path), "timings": result["timings"],
                             "decisions": states}
    return result


def associate(db, job, ident: dict, track_rows: list[dict], speaking: dict, shot_rows: list,
              scene_rows: list, section: dict) -> list[dict]:
    """Fuse audio, visible and mouth evidence for every line."""
    from .. import speaker_memory

    revision_id = ident.get("revision_id") or ""
    links = identity.cluster_characters(db, revision_id) if db is not None and revision_id \
        else {}
    locks = speaker_memory.line_locks(db, revision_id) if db is not None and revision_id \
        else {}
    sidecar_path = Path(job.vocals).parent / f"{Path(job.input_file).stem}.speakers.json" \
        if job.vocals else None
    why_by_cue = {}
    if sidecar_path is not None and sidecar_path.is_file():
        for line in json.loads(sidecar_path.read_text(encoding="utf-8")).get("lines") or []:
            why_by_cue[line.get("cue")] = line.get("why")
    calibration = (section.get("calibration") or {}) if isinstance(section, dict) else {}
    threshold = float(calibration.get("threshold") or association.SPEAKING)
    out = []
    for seg in job.segments:
        character = links.get(seg.speaker)
        row = association.fuse(
            {"cue": seg.cue_id, "start": seg.start, "end": seg.end},
            audio_character=character["id"] if character else None,
            why=why_by_cue.get(seg.cue_id), locked=locks.get(seg.cue_id),
            tracks=track_rows, speaking=speaking.get(seg.cue_id, {}), threshold=threshold)
        row["context"] = scenes.line_context({"start": seg.start, "end": seg.end}, shot_rows,
                                             scene_rows)
        out.append(row)
    return out


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".partial.json")
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def refresh(db, job, visual_file: Path, config) -> dict:
    """Re-apply corrections, references and fusion to a saved visual pass.

    Used after a person assigns, splits or merges tracks or edits scene
    boundaries: detection and mouth motion are reused as they are; only what
    depends on the corrections is recomputed.
    """
    saved = read_json(visual_file)
    if not saved.get("faces"):
        return saved
    ident = job.metrics.get("identity") or {}
    revision_id = ident.get("revision_id") or ""
    section = dict(config.get("vision", {}) or {})
    built = tracks.build(saved["faces"]["detections"], saved["shots"]["shots"], revision_id)
    corrected = tracks.apply(db, revision_id, built)
    refs = (references.load(db, ident["series_id"])["references"]
            if ident.get("series_id") else [])
    for track in corrected:
        track["matches"] = references.match(track, refs, float(section.get("match_threshold",
                                                                           0.55)))
    line_rows = [{"cue": s.cue_id, "start": s.start, "end": s.end} for s in job.segments]
    duration = saved["shots"]["video"].get("duration") or 0.0
    scene_rows = scenes.group(saved["shots"]["shots"], line_rows, duration,
                              scenes.corrections(db, revision_id))
    saved["tracks"] = corrected
    saved["scenes"] = scene_rows
    saved["associations"] = associate(db, job, ident, corrected,
                                      (saved.get("active") or {}).get("lines") or {},
                                      saved["shots"]["shots"], scene_rows, section)
    _write(visual_file, saved)
    return saved
