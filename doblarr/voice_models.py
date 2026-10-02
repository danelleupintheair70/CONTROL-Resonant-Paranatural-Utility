"""The voice models that tell speakers apart, and where they come from.

A voice model turns a line of speech into a vector; lines by the same person
land close together. Doblarr only needs that much: the subtitles already cut
the lines, so "who speaks" is a question of which lines sound alike.

Four families are offered, all without an account:

- WeSpeaker ResNet34, run through pyannote (the default; Hub download, ungated).
- Alibaba 3D-Speaker (CAM++, ERes2NetV2) and NVIDIA NeMo (TitaNet), as ONNX
  files that sherpa-onnx publishes on GitHub and runs the same way.
- Any other sherpa-onnx speaker-embedding ONNX a person registers under
  `speakers.custom` (by URL or local path).

Several models can be chosen at once: their vectors are joined. ResNet34 with
ERes2NetV2 (the default) grouped the lines of a hand-labelled anime episode
better than any model alone.
The `scores` are those measurements (recognise = a line matched to the right
named character; group = how well blind grouping found the cast, B-cubed F1).
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("doblarr.voice_models")

RATE = 16000
SHERPA_RELEASE = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                  "speaker-recongition-models/")
DEFAULT = "wespeaker-resnet34"
# Measured on all 248 lines of a hand-labelled anime episode: 16 voices, purity 0.87, F1 0.85,
# against 25 voices and F1 0.77 for ResNet34 alone.
RECOMMENDED = [DEFAULT, "3dspeaker-eres2netv2"]


@dataclass(frozen=True)
class VoiceModel:
    id: str
    name: str
    family: str
    runtime: str               # "pyannote" (Hub model) or "onnx" (sherpa-onnx file)
    source: str                # Hub repo, download URL or local path
    threshold: float           # grouping distance tuned for this model
    size_mb: int = 0
    note: str = ""
    scores: dict = field(default_factory=dict)
    custom: bool = False

    @property
    def filename(self) -> str:
        return self.source.replace("\\", "/").rsplit("/", 1)[-1]


def _onnx(id_, name, family, file, threshold, size_mb, note, recognise, group):
    return VoiceModel(id_, name, family, "onnx", SHERPA_RELEASE + file, threshold, size_mb,
                      note, {"recognise": recognise, "group": group})


BUILT_IN: dict[str, VoiceModel] = {m.id: m for m in (
    VoiceModel(DEFAULT, "WeSpeaker ResNet34", "WeSpeaker", "pyannote",
               "pyannote/wespeaker-voxceleb-resnet34-LM", 0.7, 26,
               "Trained on interviews (VoxCeleb). Fast, needs nothing downloaded from GitHub.",
               {"recognise": 0.88, "group": 0.76}),
    _onnx("3dspeaker-campplus", "CAM++ (Chinese + English)", "3D-Speaker (Alibaba)",
          "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx", 0.65, 28,
          "Trained on 200k speakers in varied conditions. Best blind grouping.", 0.87, 0.80),
    _onnx("3dspeaker-eres2netv2", "ERes2NetV2", "3D-Speaker (Alibaba)",
          "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx", 0.55, 71,
          "Purest groups: rarely mixes two people, splits more.", 0.88, 0.79),
    _onnx("nemo-titanet-large", "TitaNet Large", "NeMo (NVIDIA)",
          "nemo_en_titanet_large.onnx", 0.7, 101,
          "Strong at recognising named voices; splits more when grouping blind.", 0.88, 0.75),
    _onnx("nemo-titanet-small", "TitaNet Small", "NeMo (NVIDIA)",
          "nemo_en_titanet_small.onnx", 0.7, 40, "Lighter TitaNet.", 0.87, 0.68),
    _onnx("wespeaker-cnceleb-resnet34", "ResNet34 (CN-Celeb)", "WeSpeaker",
          "wespeaker_zh_cnceleb_resnet34_LM.onnx", 0.45, 27,
          "Trained on acted, sung and broadcast speech.", 0.84, 0.79),
)}


def catalog(config=None) -> dict[str, VoiceModel]:
    """Built-in models plus the ones registered under `speakers.custom`."""
    models = dict(BUILT_IN)
    section = (config.get("speakers") if config is not None else None) or {}
    for entry in section.get("custom") or []:
        if not isinstance(entry, dict) or not entry.get("id") or not (
                entry.get("url") or entry.get("path")):
            log.warning("speakers.custom: an entry needs an id and a url or path (%r)", entry)
            continue
        models[str(entry["id"])] = VoiceModel(
            str(entry["id"]), str(entry.get("name") or entry["id"]),
            str(entry.get("family") or "Custom"), "onnx",
            str(entry.get("url") or entry.get("path")),
            float(entry.get("threshold") or 0.6), note=str(entry.get("note") or ""),
            custom=True)
    return models


def chosen(config=None) -> list[str]:
    section = (config.get("speakers") if config is not None else None) or {}
    picked = section.get("models") or RECOMMENDED
    return [picked] if isinstance(picked, str) else [str(m) for m in picked]


def resolve(ids: list[str] | str, config=None) -> list[VoiceModel]:
    known = catalog(config)
    ids = [ids] if isinstance(ids, str) else ids
    missing = [i for i in ids if i not in known]
    if missing:
        raise ValueError(f"unknown voice model(s): {', '.join(missing)} "
                         f"(known: {', '.join(known)})")
    return [known[i] for i in ids] or [known[DEFAULT]]


def combined_id(models: list[VoiceModel]) -> str:
    return "+".join(m.id for m in models)


def threshold(models: list[VoiceModel], override: float | None = None) -> float:
    """Joined vectors compare as the mean of each model's cosine, so the
    distance to stop grouping at is the mean of their tuned ones."""
    if override:
        return float(override)
    return round(sum(m.threshold for m in models) / len(models), 3)


def folder(config=None) -> Path:
    section = (config.get("speakers") if config is not None else None) or {}
    if section.get("models_dir"):
        return Path(section["models_dir"])
    base = getattr(config, "work_dir", None) or Path("work")
    return Path(base) / "models" / "speakers"


def local_file(model: VoiceModel, models_dir: Path) -> Path | None:
    """Where an ONNX model lives on disk (None for Hub models)."""
    if model.runtime != "onnx":
        return None
    if not model.source.startswith(("http://", "https://")):
        return Path(model.source)
    return models_dir / model.filename


def is_ready(model: VoiceModel, models_dir: Path) -> bool:
    path = local_file(model, models_dir)
    return path is None or path.is_file()


def download(model: VoiceModel, models_dir: Path,
             progress: Callable[[int, int], None] | None = None) -> Path | None:
    """Fetch an ONNX model once; a partial download never passes for a model."""
    path = local_file(model, models_dir)
    if path is None or path.is_file():
        return path
    if not model.source.startswith(("http://", "https://")):
        raise FileNotFoundError(f"{model.name}: {path} does not exist")
    import requests

    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    log.info("voice model: downloading %s from %s", model.name, model.source)
    with requests.get(model.source, stream=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with part.open("wb") as out:
            for chunk in response.iter_content(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if total and part.stat().st_size != total:
        part.unlink(missing_ok=True)
        raise OSError(f"{model.name}: download stopped at {done} of {total} bytes")
    os.replace(part, path)
    return path


def _sherpa():
    """sherpa_onnx, loading the onnxruntime it ships with.

    On Windows a bare `import` can bind to the older onnxruntime.dll that
    Windows itself carries in System32 and fail on the API version; the wheel's
    own copy sits in the environment's Scripts folder.
    """
    if os.name == "nt":
        for candidate in (Path(sys.prefix) / "Scripts", Path(sys.prefix)):
            if (candidate / "onnxruntime.dll").is_file():
                os.add_dll_directory(str(candidate))
                break
    import sherpa_onnx

    return sherpa_onnx


def extractor(model: VoiceModel, models_dir: Path, device: str = "cpu"):
    """A function from 16 kHz mono float32 samples to one voice vector."""
    import numpy as np

    if model.runtime == "pyannote":
        import torch
        from pyannote.audio import Inference, Model

        loaded = Model.from_pretrained(model.source)
        if loaded is None:
            raise RuntimeError(f"{model.source} could not be loaded")
        inference = Inference(loaded, window="whole")
        inference.to(torch.device(device))

        def run_pyannote(samples):
            return np.asarray(inference({"waveform": torch.from_numpy(samples.copy())[None],
                                         "sample_rate": RATE})).ravel()
        return run_pyannote

    path = download(model, models_dir)
    sherpa_onnx = _sherpa()
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        # The published wheel is CPU-only, and a whole episode takes seconds.
        model=str(path), num_threads=max(1, min(8, os.cpu_count() or 1)), provider="cpu")
    if not config.validate():
        raise RuntimeError(f"{model.name}: {path} is not a speaker-embedding model")
    engine = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def run_onnx(samples):
        stream = engine.create_stream()
        stream.accept_waveform(RATE, samples)
        stream.input_finished()
        return np.asarray(engine.compute(stream), dtype=np.float32)
    return run_onnx


def describe(config=None) -> list[dict]:
    """The catalog for the UI: which are chosen and which are on disk."""
    picked = chosen(config)
    where = folder(config)
    return [{**asdict(m), "chosen": m.id in picked, "ready": is_ready(m, where)}
            for m in catalog(config).values()]
