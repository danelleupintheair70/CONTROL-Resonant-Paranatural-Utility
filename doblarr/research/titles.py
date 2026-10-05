"""A title's other names and catalogue ids, gathered into one `title_info` record.

From the ids Doblarr already has (the TVDB or TMDB id in the series id, and
the entries a person linked for the cast), Wikidata gives the same title's
ids in the other catalogues, and TMDB (with a key) its names in other
languages and regions. Searches and probes then use those names and ids.
Each source is skipped quietly when it cannot answer.
"""

from __future__ import annotations

from .. import published_cast
from ..catalogues import tmdb, wikidata
from ..catalogues.base import Fetch, Unreachable
from ..studio import records

KIND = "title_info"
# Which published-cast source holds which Wikidata id.
_CAST_IDS = {"anilist": "anilist", "ann": "ann", "jikan": "mal", "bangumi": "bangumi",
             "kitsu": "kitsu"}


def known_ids(db, series_id: str) -> dict[str, str]:
    ids: dict[str, str] = {}
    if series_id.startswith("show:tvdb:"):
        ids["tvdb"] = series_id.rsplit(":", 1)[-1]
    if series_id.startswith("movie:tmdb:"):
        ids["tmdb_film"] = series_id.rsplit(":", 1)[-1]
    for record in published_cast.links(db, series_id):
        key = _CAST_IDS.get(published_cast.source_of(record))
        if key and record.get("source_id") and record.get("season") is None:
            ids.setdefault(key, str(record["source_id"]))
    return ids


def refresh(db, series_id: str, *, tmdb_api_key: str = "", fetch: Fetch | None = None) -> dict:
    """Look the title up again and keep what was found, with what was skipped."""
    if not records.get(db, "series", series_id):
        raise KeyError(f"unknown series {series_id}")
    known = known_ids(db, series_id)
    skipped: dict[str, str] = {}
    ids = dict(known)
    try:
        ids.update({k: v for k, v in wikidata.external_ids(known, fetch=fetch).items()
                    if k not in known})
    except (Unreachable, LookupError, ValueError) as exc:
        skipped["wikidata"] = str(exc)
    aliases: list[dict] = []
    tmdb_id, kind = ((ids.get("tmdb_film"), "movie") if series_id.startswith("movie:")
                     else (ids.get("tmdb_tv"), "tv"))
    if tmdb_id:
        try:
            aliases = tmdb.names(int(tmdb_id), kind, api_key=tmdb_api_key, fetch=fetch)
        except (Unreachable, LookupError, ValueError) as exc:
            skipped["tmdb"] = str(exc)
    else:
        skipped["tmdb"] = "no TMDB id known for this title"
    current = records.get(db, KIND, series_id)
    return records.put(db, KIND, series_id, {
        "series_id": series_id, "external_ids": ids, "aliases": aliases, "skipped": skipped,
        "fetched_at": records.now_marker()}, scope=series_id,
        base_revision=current["revision"] if current else 0)


def get(db, series_id: str) -> dict | None:
    return records.get(db, KIND, series_id)


def aliases_for(db, series_id: str, language: str = "") -> list[str]:
    """The title's other names, those in `language` first."""
    rows = (get(db, series_id) or {}).get("aliases") or []
    ordered = sorted(rows, key=lambda r: r.get("language") != language)
    return list(dict.fromkeys(str(r["title"]) for r in ordered if r.get("title")))
