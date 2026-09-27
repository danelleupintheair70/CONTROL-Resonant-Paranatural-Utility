"""Keep held-out and condition-forbidden dialogue out of every generation request.

A clean experiment is only clean if the boundary holds on *every* path that can
reach a model: the first request, the retry after an invalid reply, the
shortening repair, the resume after a crash. Hiding a tab in the UI proves none
of that, so the boundary lives here, at the last point before a request leaves
the process:

- `Fingerprints` turns forbidden text into word/character n-grams (and, for a
  short line, the whole line) without keeping the text itself. Lines too short
  to fingerprint safely are counted, not guessed at, so a report can say how
  much of the holdout the check could actually see.
- `HoldoutGuard` scans an outgoing request against each forbidden label. It
  never echoes what it matched: a violation names the label and where it was
  found, and nothing else, so the log cannot become the leak.
- `GuardedDriver` wraps a Prompture driver so every `generate*` call — whoever
  makes it, however it retries — is scanned before it is sent.

Text the pipeline generated itself (the model's own Spanish candidates) is
allowed back in: a generator may read what it wrote. It is removed from the
haystack before scanning so a common line that happens to match the official
dub does not block the experiment that produced it.
"""

from __future__ import annotations

import contextlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..artifacts import digest
from ..errors import DoblarrError

NGRAM = 6          # tokens per fingerprint window
MIN_NEEDLE = 3     # a shorter line cannot be told apart from ordinary words

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]")
_WORD = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)


class HoldoutViolation(DoblarrError):
    """A request was about to carry content its condition must not see."""

    http_status = 409

    def __init__(self, label: str, where: str):
        super().__init__(
            f"blocked a {where} request: it contained {label} content that this "
            f"condition is not allowed to read. Nothing was sent.")
        self.label = label
        self.where = where


def tokens(text: str) -> list[str]:
    """Accent- and case-insensitive tokens; CJK characters are tokens on their own."""
    folded = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    out: list[str] = []
    for word in _WORD.findall(folded):
        if _CJK.search(word):
            out.extend(ch for ch in word if not ch.isspace())
        else:
            out.append(word)
    return out


def _grams(seq: list[str], size: int) -> set[tuple[str, ...]]:
    return {tuple(seq[i:i + size]) for i in range(0, len(seq) - size + 1)}


@dataclass
class Fingerprints:
    """Forbidden text reduced to hashes of what it would look like in a request."""

    grams: set[tuple[str, ...]] = field(default_factory=set)
    needles: set[tuple[str, ...]] = field(default_factory=set)
    lines: int = 0
    fingerprinted: int = 0
    too_short: int = 0

    @classmethod
    def of(cls, texts, sentinels=()) -> Fingerprints:
        found = cls()
        for text in texts:
            seq = tokens(text)
            if not seq:
                continue
            found.lines += 1
            if len(seq) >= NGRAM:
                found.grams |= _grams(seq, NGRAM)
                found.fingerprinted += 1
            elif len(seq) >= MIN_NEEDLE:
                found.needles.add(tuple(seq))
                found.fingerprinted += 1
            else:
                found.too_short += 1
        for sentinel in sentinels:
            seq = tokens(sentinel)
            if seq:
                found.needles.add(tuple(seq))
        return found

    def summary(self) -> dict:
        return {"lines": self.lines, "fingerprinted": self.fingerprinted,
                "too_short_to_check": self.too_short}


def _strings(value: Any) -> list[str]:
    """Every string inside a request, decoding JSON payloads so escapes cannot hide text."""
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
        stripped = value.strip()
        if stripped[:1] in "{[":
            with contextlib.suppress(ValueError):
                found.extend(_strings(json.loads(stripped)))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(_strings(key))
            found.extend(_strings(item))
    elif isinstance(value, list | tuple):
        for item in value:
            found.extend(_strings(item))
    return found


class HoldoutGuard:
    """Scans outgoing requests against labelled forbidden fingerprints."""

    def __init__(self, forbidden: dict[str, Fingerprints] | None = None):
        self.forbidden = dict(forbidden or {})
        self.generated: list[tuple[str, ...]] = []
        self.checked = 0
        self.blocked = 0
        self.audit: list[dict] = []

    def allow_generated(self, text: str) -> None:
        """Mark text as the pipeline's own output, which it may read back."""
        seq = tokens(text)
        if len(seq) >= 1 and tuple(seq) not in self.generated:
            self.generated.append(tuple(seq))

    def _haystack(self, value: Any) -> list[str]:
        seq: list[str] = []
        for text in _strings(value):
            seq.extend(tokens(text))
            seq.append("\x00")  # never let an n-gram straddle two strings
        if not self.generated:
            return seq
        covered = [False] * len(seq)
        for own in self.generated:
            size = len(own)
            for i in range(0, len(seq) - size + 1):
                if tuple(seq[i:i + size]) == own:
                    for j in range(i, i + size):
                        covered[j] = True
        return [tok if not covered[i] else "\x00" for i, tok in enumerate(seq)]

    def hits(self, value: Any) -> list[str]:
        """The labels whose content appears in `value` (never the content)."""
        seq = self._haystack(value)
        found = []
        for label, prints in self.forbidden.items():
            if prints.grams and _grams(seq, NGRAM) & prints.grams:
                found.append(label)
                continue
            sizes = {len(n) for n in prints.needles}
            if any(_grams(seq, size) & {n for n in prints.needles if len(n) == size}
                   for size in sizes):
                found.append(label)
        return found

    def check(self, value: Any, where: str = "generation") -> None:
        self.checked += 1
        found = self.hits(value)
        self.audit.append({"where": where, "request": digest(_strings(value))[:16],
                           "blocked": bool(found), "labels": found})
        if found:
            self.blocked += 1
            raise HoldoutViolation(found[0], where)

    def summary(self) -> dict:
        return {"checked": self.checked, "blocked": self.blocked,
                "labels": {k: v.summary() for k, v in self.forbidden.items()}}


class GuardedDriver:
    """A Prompture driver whose every generation request passes the guard first."""

    def __init__(self, inner, guard: HoldoutGuard, where: str = "generation"):
        self._inner = inner
        self._guard = guard
        self._where = where

    def __getattr__(self, name):
        value = getattr(self._inner, name)
        if callable(value) and (name.startswith("generate") or name.startswith("stream")):
            def guarded(*args, **kwargs):
                self._guard.check({"args": list(args), "kwargs": kwargs}, self._where)
                return value(*args, **kwargs)
            return guarded
        return value


def guard_translator(translator, guard: HoldoutGuard, where: str = "translation"):
    """Wrap a Prompture translator's driver so all its requests are scanned.

    Lazy: the driver is still built on first use (a provider that is not
    configured fails where it always did), but whatever it builds is wrapped
    before any request can go through it.
    """
    original = getattr(translator, "_get_driver", None)
    if original is None:
        return translator   # a passthrough stub sends nothing anywhere

    def guarded():
        inner = original()
        if not isinstance(inner, GuardedDriver):
            translator._driver = GuardedDriver(inner, guard, where)
        return translator._driver

    translator._get_driver = guarded
    return translator
