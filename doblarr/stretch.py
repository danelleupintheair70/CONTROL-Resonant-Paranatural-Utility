"""The time-stretch filter both timing owners use.

`atempo` is ffmpeg's built-in overlap-add stretcher. It is always there, and
past about 1.15x it starts to sound chopped: it repeats or drops whole pitch
periods. `rubberband` is the Rubber Band library's phase vocoder, which keeps
voiced speech smoother at the same factor. It needs an ffmpeg built with
librubberband (the common Windows and Debian builds are); when it is missing
the stretch falls back to `atempo` and says so once in the log.
"""

from __future__ import annotations

import logging
import subprocess
from functools import cache

log = logging.getLogger("doblarr.stretch")

STRETCHERS = ("atempo", "rubberband")
DEFAULT = "atempo"

# Rubber Band's R2 engine with options suited to one voice: transients reset
# only above the low band, so plosives stay sharp without smearing vowels;
# independent phase, because a single voice has no other channel to stay
# coherent with; and a short window, which keeps fast syllables apart.
RUBBERBAND_OPTIONS = "transients=mixed:phase=independent:window=short"


def normalize(name: object) -> str:
    value = str(name or DEFAULT).strip().lower()
    if value not in STRETCHERS:
        raise ValueError(f"timing.stretcher must be one of {', '.join(STRETCHERS)}")
    return value


@cache
def _has_rubberband() -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[1:2] == ["rubberband"] for line in out.stdout.splitlines()
               if len(line.split()) > 1)


def resolve(name: object) -> str:
    """The stretcher that will actually run for a configured one."""
    value = normalize(name)
    if value == "rubberband" and not _has_rubberband():
        if not getattr(resolve, "_warned", False):
            log.warning("timing.stretcher is rubberband but this ffmpeg has no rubberband "
                        "filter; using atempo")
            resolve._warned = True  # type: ignore[attr-defined]
        return "atempo"
    return value


def atempo_chain(factor: float) -> str:
    """atempo only accepts 0.5-2.0; chain filters for larger corrections."""
    parts = []
    f = factor
    while f > 2.0:
        parts.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        parts.append("atempo=0.5")
        f /= 0.5
    parts.append(f"atempo={f:.4f}")
    return ",".join(parts)


def tempo_filter(factor: float, stretcher: str = DEFAULT) -> str:
    """An ffmpeg filter that plays audio `factor` times faster, pitch unchanged."""
    if stretcher == "rubberband":
        return f"rubberband=tempo={factor:.4f}:{RUBBERBAND_OPTIONS}"
    return atempo_chain(factor)
