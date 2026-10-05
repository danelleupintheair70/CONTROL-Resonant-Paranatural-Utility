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

DETECTOR = "voice-similarity/2"
MIN_SIMILARITY = 0.25
MIN_SECONDS = 0.5   # shorter takes carry too little voice to judge
# A voice's takes are compared with each other as well as with the floor: a
# voice borrowed from another group, or cast from another episode, scores low
# on every take against this run's reference clip, and that is not a drift.
# Only a take this far below its voice's typical score counts.
MARGIN = 0.15
MIN_SAMPLES = 4


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
        self._seen: dict[tuple, float | None] = {}
        self.baselines: dict[str, float] = {}

    def calibrate(self, rows: list[tuple[str, float | None]]) -> None:
        """Each voice's typical similarity, from (voice, similarity) rows."""
        import statistics

        by_voice: dict[str, list[float]] = {}
        for voice, value in rows:
            if value is not None:
                by_voice.setdefault(voice, []).append(value)
        self.baselines = {voice: statistics.median(values)
                          for voice, values in by_voice.items() if len(values) >= MIN_SAMPLES}

    def _reference(self, speaker: str):
        if speaker not in self._refs:
            path = self.references.get(speaker)
            self._refs[speaker] = vector(path) if path and Path(path).exists() else None
        return self._refs[speaker]

    def similarity(self, speaker: str, take: Path) -> float | None:
        """Cosine similarity of `take` to the speaker's reference; None = unknown."""
        import numpy as np

        # A line's takes share one file name, so the key must say which audio.
        try:
            info = Path(take).stat()
            key = (speaker, str(take), info.st_mtime_ns, info.st_size)
        except OSError:
            return None
        if key in self._seen:
            return self._seen[key]
        ref = self._reference(speaker)
        if ref is None:
            return None
        try:
            v = vector(take)
        except Exception as exc:  # noqa: BLE001 - an unreadable take is unknown
            log.debug("voice check: cannot read %s: %s", take, exc)
            return None
        value = None if v is None else round(float(np.dot(v, ref)), 4)
        self._seen[key] = value
        return value

    def floor(self, voice: str | None = None) -> float:
        typical = self.baselines.get(voice) if voice else None
        return self.minimum if typical is None else min(self.minimum, typical - MARGIN)

    def drifted(self, similarity: float | None, voice: str | None = None) -> bool:
        return similarity is not None and similarity < self.floor(voice)


def for_job(job, minimum: float = MIN_SIMILARITY) -> VoiceCheck:
    refs = {label: spk.reference_clip for label, spk in (job.speakers or {}).items()}
    return VoiceCheck(refs, minimum)
