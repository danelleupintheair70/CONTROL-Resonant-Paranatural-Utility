"""Japanese names as a Spanish voice engine should read them.

A Spanish engine reads romaji with Spanish spelling rules, and four of them
land badly: `j` becomes the throat sound of "jamón" (Jiro as "Hiro"), `h`
goes silent (Hikari as "Ikari"), and `ge`/`gi` soften the same way `j` does
(Kagerou as "Kaherou"). Latin American anime dubs say these as "Yiro",
"Jikari" and "Kaguerou", so the respelling below writes what they say for the
engine only; captions and the script keep the real spelling.

Only terms a person listed are respelled (the translation glossary: the names
and terms kept untranslated), because the same letters in a Spanish word
must stay Spanish. An explicit `dub.pronunciations` entry always wins.
"""

from __future__ import annotations

import re

# Order matters: `h` must become `j` after the old `j` has become `y`, or
# "Jiro" would turn into "Yiro" and then back again.
_RULES = (
    (re.compile(r"j", re.IGNORECASE), "y"),
    (re.compile(r"(?<![sScC])h", re.IGNORECASE), "j"),
    (re.compile(r"g(?=[eiEI])", re.IGNORECASE), "gu"),
)


def respell(term: str) -> str:
    """The Spanish-engine spelling of one romaji term, capitals preserved."""
    out = term
    for pattern, replacement in _RULES:
        out = pattern.sub(_keep_case(replacement), out)
    return out


def _keep_case(replacement: str):
    def swap(match: re.Match[str]) -> str:
        return replacement.capitalize() if match.group()[:1].isupper() else replacement
    return swap


def respellings(terms) -> dict[str, str]:
    """{term: spoken form} for every listed term that reads differently."""
    found = {}
    for term in terms:
        term = str(term or "").strip()
        if term and respell(term) != term:
            found[term] = respell(term)
    return found
