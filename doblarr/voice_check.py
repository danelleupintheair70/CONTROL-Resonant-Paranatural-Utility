"""Does a generated take still sound like the voice it was cloned from?

A cloning TTS samples every take, and now and then a take drifts: the timbre
slides toward a generic voice or toward somebody else's. Recognition cannot
hear that, because the words are right. This compares a take with its
speaker's reference clip using the same local speaker-embedding model that
groups voices (WeSpeaker ResNet34, no download beyond that model).

The number is a cosine similarity, from about 0 (unrelated) to 1. A Spanish
take against a Japanese reference scores lower than two clips in one language,
so the floor is low: on a test anime episode own-reference similarity
had a median of 0.52, the closest other voice 0.27, and the takes below 0.25
were almost all closer to another character than to their own.
"""

from __future__ import annotations

import logging
from functools import cache
from pathlib import Path

log = logging.getLogger("doblarr.voice_check")

DETECTOR = "voice-similarity/1"
MIN_SIMILARITY = 0.25
MIN_SECONDS = 0.5   # shorter takes carry too little voice to judge


@cache
def _extractor():
    from . import voice_models

    model = voice_models.resolve(voice_models.DEFAULT)[0]
    return voice_models.extractor(model, voice_models.folder(), "cpu")


def vector(path: Path):
    """A normalised voice vector for a whole file, or None when too short."""
    import numpy as np

    from .speakers import _audio

    samples = _audio(Path(path))
    if len(samples) < MIN_SECONDS * 16000:
        return None
    v = np.asarray(_extractor()(samples), dtype=np.float32).ravel()
    norm = float(np.linalg.norm(v))
    return v / norm if norm else None


class VoiceCheck:
    """Similarity of takes to their speaker's reference, references cached."""

    def __init__(self, references: dict[str, Path | None], minimum: float = MIN_SIMILARITY):
        self.references = references
        self.minimum = float(minimum)
        self._refs: dict[str, object] = {}

    def _reference(self, speaker: str):
        if speaker not in self._refs:
            path = self.references.get(speaker)
            self._refs[speaker] = vector(path) if path and Path(path).exists() else None
        return self._refs[speaker]

    def similarity(self, speaker: str, take: Path) -> float | None:
        """Cosine similarity of `take` to the speaker's reference; None = unknown."""
        import numpy as np

        ref = self._reference(speaker)
        if ref is None:
            return None
        try:
            v = vector(take)
        except Exception as exc:  # noqa: BLE001 - an unreadable take is unknown
            log.debug("voice check: cannot read %s: %s", take, exc)
            return None
        if v is None:
            return None
        return round(float(np.dot(v, ref)), 4)

    def drifted(self, similarity: float | None) -> bool:
        return similarity is not None and similarity < self.minimum


def for_job(job, minimum: float = MIN_SIMILARITY) -> VoiceCheck:
    refs = {label: spk.reference_clip for label, spk in (job.speakers or {}).items()}
    return VoiceCheck(refs, minimum)
