"""Public catalogues a series' cast can come from (see `base` for the rules).

`PROVIDERS` maps a source name to the provider that reads it. AniList stays
the first choice; the others add dub casts (ANN, MyAnimeList through Jikan)
and native-script coverage (Bangumi).
"""

from __future__ import annotations

from .anilist import AniList
from .ann import ANN
from .bangumi import Bangumi
from .base import CastProvider, Unreachable, configure, configure_from
from .jikan import Jikan

PRIMARY = "anilist"

PROVIDERS: dict[str, CastProvider] = {
    "anilist": AniList(),
    "ann": ANN(),
    "jikan": Jikan(),
    "bangumi": Bangumi(),
}


def provider(name: str) -> CastProvider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ValueError(f"unknown catalogue {name!r}; one of {', '.join(PROVIDERS)}") from None


def for_url(url: str) -> CastProvider | None:
    return next((p for p in PROVIDERS.values() if p.can_handle(url)), None)


__all__ = ["PRIMARY", "PROVIDERS", "CastProvider", "Unreachable", "configure", "configure_from",
           "for_url", "provider"]
