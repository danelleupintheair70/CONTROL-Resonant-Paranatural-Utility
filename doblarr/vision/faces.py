"""Face detection and face embeddings, per domain (see doblarr.vision.capability).

A detection is a box in one frame with the detector that found it. An
embedding is a vector for comparing a face crop with other crops *of the same
embedder*: SFace vectors and DINOv2 vectors are different spaces and are never
compared with each other. Nothing here names anyone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import capability

log = logging.getLogger("doblarr.vision.faces")

YUNET_SCORE = 0.75
MIN_FACE = 24          # pixels, on the sampled frame


@dataclass
class Face:
    box: tuple[int, int, int, int]       # x, y, w, h on the sampled frame
    score: float | None                  # None: the detector gives no score
    detector: str
    domain: str
    landmarks: list[float] = field(default_factory=list)
    vector: list[float] | None = None
    embedder: str = ""


class YuNet:
    name = "yunet-2023mar"
    domain = "live_action"

    def __init__(self, model: Path, score: float = YUNET_SCORE):
        import cv2

        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(str(model), "", (320, 320), score, 0.3, 50)
        self.size = (0, 0)

    def detect(self, frame) -> list[Face]:
        h, w = frame.shape[:2]
        if (w, h) != self.size:
            self.detector.setInputSize((w, h))
            self.size = (w, h)
        _ok, found = self.detector.detect(frame)
        faces = []
        for row in found if found is not None else []:
            x, y, bw, bh = (int(round(v)) for v in row[:4])
            if bw < MIN_FACE or bh < MIN_FACE:
                continue
            faces.append(Face((max(0, x), max(0, y), bw, bh), round(float(row[14]), 3),
                              self.name, self.domain, [float(v) for v in row[:15]]))
        return faces


class AnimeCascade:
    name = "lbpcascade-animeface"
    domain = "anime"

    def __init__(self, model: Path):
        import cv2

        self.cv2 = cv2
        self.cascade = cv2.CascadeClassifier(str(model))
        if self.cascade.empty():
            raise OSError(f"could not load {model}")

    def detect(self, frame) -> list[Face]:
        gray = self.cv2.equalizeHist(self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY))
        found = self.cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                              minSize=(MIN_FACE, MIN_FACE))
        return [Face((int(x), int(y), int(w), int(h)), None, self.name, self.domain)
                for (x, y, w, h) in (found if len(found) else [])]


class SFace:
    name = "sface-2021dec"

    def __init__(self, model: Path):
        import cv2

        self.recognizer = cv2.FaceRecognizerSF.create(str(model), "")

    def embed(self, frame, faces: list[Face]) -> None:
        import numpy as np

        for face in faces:
            if len(face.landmarks) < 15:
                continue
            aligned = self.recognizer.alignCrop(frame, np.asarray(face.landmarks,
                                                                  dtype=np.float32))
            vector = np.asarray(self.recognizer.feature(aligned), dtype=np.float32).ravel()
            norm = float(np.linalg.norm(vector))
            if norm:
                face.vector = [round(float(v), 4) for v in vector / norm]
                face.embedder = self.name


class Dino:
    """DINOv2-small image embeddings of face crops, from the local model cache only."""

    name = "dinov2-small"

    def __init__(self):
        import torch
        from transformers import AutoImageProcessor, AutoModel

        self.torch = torch
        self.processor = AutoImageProcessor.from_pretrained(capability.DINO,
                                                            local_files_only=True)
        self.model = AutoModel.from_pretrained(capability.DINO, local_files_only=True)
        self.model.eval()

    def embed(self, frame, faces: list[Face]) -> None:
        import numpy as np

        crops, owners = [], []
        for face in faces:
            x, y, w, h = face.box
            pad = int(0.15 * max(w, h))
            crop = frame[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
            if crop.size == 0:
                continue
            crops.append(crop[:, :, ::-1])     # BGR -> RGB
            owners.append(face)
        if not crops:
            return
        with self.torch.no_grad():
            inputs = self.processor(images=crops, return_tensors="pt")
            output = self.model(**inputs).last_hidden_state[:, 0]
        for face, vector in zip(owners, output.numpy(), strict=True):
            norm = float(np.linalg.norm(vector))
            if norm:
                face.vector = [round(float(v), 4) for v in vector / norm]
                face.embedder = self.name


@dataclass
class Backend:
    detectors: list
    embedders: dict          # domain -> embedder
    unavailable: dict        # domain -> reason

    def describe(self) -> dict:
        return {"detectors": [d.name for d in self.detectors],
                "embedders": {k: v.name for k, v in self.embedders.items()},
                "unavailable": self.unavailable}


def load(config=None, domain: str = "auto") -> Backend:
    """Whatever this machine can run for the asked domain(s), and why not the rest."""
    status = capability.status(config)
    wanted = ("live_action", "anime") if domain == "auto" else (domain,)
    detectors: list = []
    embedders: dict = {}
    unavailable: dict = {}
    for name in wanted:
        if not status[name]["detector"]:
            unavailable[name] = "; ".join(status["reasons"]) or "no detector"
            continue
        try:
            if name == "live_action":
                detectors.append(YuNet(capability.path_of("yunet", config)))
                if status[name]["embedding"]:
                    embedders[name] = SFace(capability.path_of("sface", config))
            else:
                detectors.append(AnimeCascade(capability.path_of("animeface", config)))
                if status[name]["embedding"]:
                    embedders[name] = Dino()
        except Exception as exc:  # noqa: BLE001 - a backend that fails to load is unavailable
            unavailable[name] = f"could not load: {exc}"
            log.warning("vision: %s backend unavailable (%s)", name, exc)
        if name in embedders or name in unavailable:
            continue
        unavailable.setdefault(f"{name}_embedding",
                               "no embedding model; faces are detected but not matched")
    return Backend(detectors, embedders, unavailable)


def detect(backend: Backend, frame) -> list[Face]:
    found: list[Face] = []
    for detector in backend.detectors:
        faces = detector.detect(frame)
        embedder = backend.embedders.get(detector.domain)
        if embedder is not None and faces:
            embedder.embed(frame, faces)
        found.extend(faces)
    return found
