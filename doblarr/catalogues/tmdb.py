"""TMDB: a title's names in other languages and regions (free key).

Not a cast source. A title Doblarr already knows by its TMDB id gets its
alternative titles and translated names, which help search other catalogues
by the name they use and give the dub's locale the title it was released
under. Needs `research.tmdb_api_key`; without it the source is off.
"""

from __future__ import annotations

from . import base
from .base import Fetch, Unreachable

API = "https://api.themoviedb.org/3"


def names(tmdb_id: int, kind: str, *, api_key: str, fetch: Fetch | None = None) -> list[dict]:
    """[{title, language, region, source}] from alternative titles and translations."""
    if not api_key:
        raise Unreachable("TMDB needs research.tmdb_api_key")
    if kind not in ("tv", "movie"):
        raise ValueError("kind is tv or movie")
    params = {"api_key": api_key}

    def get(path: str):
        return base.cached(f"tmdb:{kind}:{tmdb_id}:{path}", lambda: base.get_json(
            fetch, f"{API}/{kind}/{int(tmdb_id)}/{path}", params=params, interval=0.3))

    alternative = get("alternative_titles")
    out = [{"title": t.get("title"), "language": "", "region": t.get("iso_3166_1") or "",
            "note": t.get("type") or "", "source": "tmdb"}
           for t in (alternative.get("results") or alternative.get("titles") or [])
           if t.get("title")]
    for t in get("translations").get("translations") or []:
        name = (t.get("data") or {}).get("name") or (t.get("data") or {}).get("title")
        if name:
            out.append({"title": name, "language": t.get("iso_639_1") or "",
                        "region": t.get("iso_3166_1") or "", "note": "translation",
                        "source": "tmdb"})
    seen, unique = set(), []
    for row in out:
        key = (row["title"], row["language"], row["region"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique
