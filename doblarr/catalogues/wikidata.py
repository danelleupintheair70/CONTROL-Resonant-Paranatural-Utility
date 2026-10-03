"""Wikidata: one title's ids in every catalogue, from any id already known.

A series known by its TVDB id (or a film by its TMDB id, or a linked AniList
entry) is looked up once on Wikidata's public SPARQL endpoint, which returns
the same title's ANN, MyAnimeList, AniList, Bangumi, Kitsu, IMDb, TVDB and
TMDB ids. Later probes can then go to the right entry instead of searching by
name. Only the known id leaves the machine; answers are cached.
"""

from __future__ import annotations

from . import base
from .base import Fetch

SPARQL = "https://query.wikidata.org/sparql"
PROPERTIES = {
    "ann": "P1985", "mal": "P4086", "anilist": "P8729", "bangumi": "P5732", "kitsu": "P11495",
    "imdb": "P345", "tvdb": "P4835", "tmdb_tv": "P4983", "tmdb_film": "P4947",
}


def _literal(value: str) -> str:
    return '"' + str(value).replace("\\", "").replace('"', "") + '"'


def query_for(known: dict[str, str]) -> str:
    matches = " UNION ".join(f"{{ ?item wdt:{PROPERTIES[k]} {_literal(v)} }}"
                             for k, v in known.items() if k in PROPERTIES and v)
    if not matches:
        raise ValueError("no id Wikidata can look up")
    optional = " ".join(f"OPTIONAL {{ ?item wdt:{p} ?{k} }}" for k, p in PROPERTIES.items())
    columns = " ".join("?" + k for k in PROPERTIES)
    return f"SELECT ?item {columns} WHERE {{ {matches} {optional} }} LIMIT 5"


def external_ids(known: dict[str, str], *, fetch: Fetch | None = None) -> dict[str, str]:
    """Every catalogue id of the title one of `known` names; {} when Wikidata has none."""
    query = query_for(known)
    data = base.cached(f"wikidata:{query}", lambda: base.get_json(
        fetch, SPARQL, params={"query": query, "format": "json"},
        headers={"Accept": "application/sparql-results+json"}, interval=1.0))
    rows = ((data or {}).get("results") or {}).get("bindings") or []
    if len({r.get("item", {}).get("value") for r in rows}) > 1:
        return {}    # the known ids point at different titles: trust none of them
    out: dict[str, str] = {}
    for row in rows:
        for key in PROPERTIES:
            if key in row and key not in out:
                out[key] = str(row[key]["value"])
        if row.get("item"):
            out["wikidata"] = str(row["item"]["value"]).rsplit("/", 1)[-1]
    return out
