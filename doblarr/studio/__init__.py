"""The episode studio: one persistent workspace over the existing dub run.

The studio does not own a second copy of any cue, take, selection or job. It
stores only what the pipeline had no place for — which reference plays which
role, how two editions line up, what an experiment was allowed to read, what a
listener concluded — and reaches everything else through the review snapshot,
the decisions sidecar, the job queue and the saved versions that already exist.
"""

from .records import FrozenRecord, StudioConflict  # noqa: F401
