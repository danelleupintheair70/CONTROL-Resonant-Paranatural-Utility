"""The published cast of a series: who the characters are, from a public source.

An analysis learns who speaks from the episode itself. A public catalogue
already knows the cast of a published show: each character's role, gender,
sometimes an age, a description and the original voice actors. This module
fetches that list once per series, so later stages can match what they hear
and see against real characters instead of naming voices from scratch.

Nothing here runs on its own and nothing is guessed:

- `search` only lists candidate catalogue entries for a title; it stores
  nothing. Sending a title to the catalogue is the only data that leaves the
  machine, and it happens when a person asks.
- `link` records that a person chose one entry for a series (optionally for
  one season, since catalogues list each season as its own title). The cast
  is stored as a `published_cast` record, apart from what episodes taught.
  Library metadata is shown apart and is not evidence from the episode.
- `candidates` narrows the cast for one episode: the main cast always, guests
  only when their description names that episode.
- `import_characters` creates series characters from the cast, or attaches the
  published facts to a character that already has the name. It never renames
  or overwrites a character.

The catalogue today is AniList (anime), read through Prompture's keyless
AniList reader.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any

from . import identity
from .studio import records

KIND = "published_cast"
SOURCE = "anilist"
ROLES = ("MAIN", "SUPPORTING", "BACKGROUND")

# "episode 14", "episodes 3 and 5", "Episode #4", "episodes 7-9", "ep. 12"
_EPISODES = re.compile(
    r"\bep(?:isode)?s?\.?\s*#?\s*(\d{1,4}(?:\s*(?:,|and|&|-|–|to)\s*#?\s*\d{1,4})*)",
    re.IGNORECASE)
_NUMBER = re.compile(r"\d{1,4}")
_RANGE = re.compile(r"(\d{1,4})\s*(?:-|–|to)\s*(\d{1,4})")
# Catalogue formats that fit a show or a film, for ordering search results.
SHOW_FORMATS = ("TV", "TV_SHORT", "ONA")
FILM_FORMATS = ("MOVIE",)
# Romanizations of one long vowel: Hyūga, Hyuuga, Hyuga; Kōichi, Kouichi.
_LONG_VOWELS = (("ou", "o"), ("oo", "o"), ("uu", "u"), ("aa", "a"), ("ii", "i"), ("ee", "e"))

SearchFn = Callable[..., list[dict]]
ReadFn = Callable[..., Any]


def _prompture_search(query: str, **kwargs: Any) -> list[dict]:
    try:
        from prompture.tools.web import search_anilist
    except ImportError as exc:  # pragma: no cover - depends on the installed Prompture
        raise RuntimeError("the published cast needs prompture>=1.13.6 (the AniList reader); "
                           "reinstall Doblarr's requirements") from exc
    return search_anilist(query, **kwargs)


def _prompture_read(url: str, **kwargs: Any) -> Any:
    from prompture.tools.web import read_url

    return read_url(url, **kwargs)


def record_id(series_id: str, season: int | None = None) -> str:
    return f"{series_id}#s{int(season)}" if season is not None else series_id


def episode_mentions(text: str) -> list[int]:
    """Episode numbers a description names ("appears in episode 14")."""
    found: set[int] = set()
    for match in _EPISODES.finditer(text or ""):
        span = match.group(1)
        for low, high in _RANGE.findall(span):
            a, b = int(low), int(high)
            if 0 < a <= b and b - a <= 50:
                found.update(range(a, b + 1))
        found.update(int(n) for n in _NUMBER.findall(span))
    return sorted(n for n in found if n > 0)


def series_title(db, series_id: str) -> str:
    """The best title to search with: the series record, then the library scan,
    then the show folder's name. Only ever used as a search query."""
    series = records.get(db, "series", series_id) or {}
    if series.get("title"):
        return str(series["title"])
    if series_id.startswith("show:tvdb:"):
        tvdb = series_id.rsplit(":", 1)[-1]
        row = db.query_one("SELECT items FROM scan_state WHERE id = 1")
        if row is not None:
            import json

            try:
                items = json.loads(row["items"] or "[]")
            except ValueError:
                items = []
            for item in items:
                if (isinstance(item, dict) and item.get("media_type") == "show"
                        and str(item.get("tvdb_id") or "") == tvdb and item.get("title")):
                    return str(item["title"])
    folders = series.get("folders") or []
    if folders:
        return str(folders[0]).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return ""


def search(query: str, *, kind: str = "", max_results: int = 8,
           search_fn: SearchFn | None = None) -> list[dict]:
    """Catalogue entries that might be this title, best match first. Stores nothing.

    `kind` ("show" or "movie", from the series id) moves the entries of that
    format to the front: a show's search also returns its films.
    """
    query = " ".join(str(query or "").split())
    if not query:
        raise ValueError("a search needs a title")
    hits = (search_fn or _prompture_search)(query, max_results=max_results)
    preferred = {"show": SHOW_FORMATS, "movie": FILM_FORMATS}.get(kind, ())
    if preferred:
        hits = sorted(hits, key=lambda h: h.get("format") not in preferred)
    return [{"source": SOURCE, "id": h.get("id"), "title": h.get("title"),
             "titles": h.get("titles") or {}, "year": h.get("year"),
             "format": h.get("format"), "episodes": h.get("episodes"), "url": h.get("url")}
            for h in hits]


def _character(c: dict) -> dict:
    return {
        "source_id": c.get("id"),
        "name": " ".join(str(c.get("name") or "").split()),
        "native": c.get("native") or "",
        "alternative": [a for a in c.get("alternative") or [] if a],
        "role": str(c.get("role") or "").upper(),
        "gender": c.get("gender"),
        "age": c.get("age"),
        "description": c.get("description") or "",
        "episodes": episode_mentions(c.get("description") or ""),
        "voice_actors": c.get("voice_actors") or [],
        "url": c.get("url"),
    }


def link(db, series_id: str, url: str, *, season: int | None = None,
         max_characters: int = 100, read_fn: ReadFn | None = None) -> dict:
    """Record that a person chose this catalogue entry for the series, with its cast."""
    if not records.get(db, "series", series_id):
        raise KeyError(f"unknown series {series_id}")
    result = (read_fn or _prompture_read)(url, max_characters=max_characters, use_cache=False)
    meta = getattr(result, "meta", None) or {}
    if getattr(result, "reader", "") != SOURCE or not isinstance(meta.get("characters"), list):
        raise ValueError(f"{url} is not an AniList title page")
    characters = [_character(c) for c in meta["characters"] if c.get("name")]
    document = {
        "series_id": series_id,
        "season": season,
        "source": SOURCE,
        "source_id": meta.get("id"),
        "url": meta.get("page_url") or url,
        "title": getattr(result, "title", "") or "",
        "titles": meta.get("titles") or {},
        "format": meta.get("format"),
        "year": meta.get("year"),
        "episodes": meta.get("episodes"),
        "characters": characters,
        "complete": not meta.get("more_characters"),
        "linked_by": "person",
        "fetched_at": records.now_marker(),
    }
    rid = record_id(series_id, season)
    current = records.get(db, KIND, rid)
    return records.put(db, KIND, rid, document, scope=series_id,
                       base_revision=current["revision"] if current else 0)


def refresh(db, series_id: str, *, season: int | None = None,
            read_fn: ReadFn | None = None) -> dict:
    """Fetch the linked entry again (the catalogue may have grown)."""
    current = get(db, series_id, season=season)
    if current is None:
        raise KeyError(f"{series_id} has no published cast linked")
    return link(db, series_id, current["url"], season=season,
                max_characters=max(100, len(current.get("characters") or [])), read_fn=read_fn)


def get(db, series_id: str, *, season: int | None = None) -> dict | None:
    """The linked cast for a season, falling back to the whole-series link."""
    if season is not None:
        found = records.get(db, KIND, record_id(series_id, season))
        if found is not None:
            return found
    return records.get(db, KIND, record_id(series_id))


def links(db, series_id: str) -> list[dict]:
    return records.list_latest(db, KIND, scope=series_id)


def candidates(cast: dict | None, *, episode: int | None = None) -> list[dict]:
    """Characters who may speak in one episode, each with why.

    The main cast always. A supporting or background character whose
    description names episodes is a candidate only in those episodes; one
    whose description names none stays a candidate everywhere, marked as
    unplaced so a matcher can weigh it lower.
    """
    out = []
    for c in (cast or {}).get("characters") or []:
        role = c.get("role") or ""
        named = c.get("episodes") or []
        if role == "MAIN":
            why = "main cast"
        elif episode is not None and named:
            if episode not in named:
                continue
            why = f"described as appearing in episode {episode}"
        elif named:
            why = "appears in episodes " + ", ".join(str(n) for n in named)
        else:
            why = "recurring, episodes not stated"
        out.append({**c, "why": why})
    return out


def name_key(text: str) -> str:
    """A name folded for matching only: accents, case and long-vowel spellings."""
    text = "".join(ch for ch in unicodedata.normalize("NFKD", str(text or ""))
                   if not unicodedata.combining(ch))
    text = " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())
    for long, short in _LONG_VOWELS:
        text = text.replace(long, short)
    return text


def _cast_names(c: dict) -> list[str]:
    return [n for n in (c.get("name"), c.get("native"), *(c.get("alternative") or [])) if n]


def _words(c: dict) -> set[str]:
    return {w for n in _cast_names(c) for w in name_key(n).split()}


def match_existing(series_characters: list[dict], cast: list[dict], member: dict
                   ) -> tuple[dict | None, list[str]]:
    """The series character a cast member already is, if exactly one fits.

    A matching full name or alias wins. Otherwise a one-word character name
    ("Lamp") matches the cast member with that word in their name, but only
    when no other cast member has it too. Returns (character, []) on a match,
    (None, rivals) when the word fits several cast members, else (None, []).
    """
    member_keys = {name_key(n) for n in _cast_names(member)}
    for character in series_characters:
        names = [character.get("name"), *(character.get("aliases") or [])]
        if member_keys & {name_key(n) for n in names if n}:
            return character, []
    member_words = _words(member)
    for character in series_characters:
        for name in [character.get("name"), *(character.get("aliases") or [])]:
            key = name_key(name or "")
            if not key or " " in key or key not in member_words:
                continue
            rivals = [m["name"] for m in cast if m is not member and key in _words(m)]
            return (None, rivals) if rivals else (character, [])
    return None, []


def import_characters(db, series_id: str, *, season: int | None = None,
                      roles: Iterable[str] = ("MAIN",), names: Iterable[str] | None = None) -> dict:
    """Create series characters from the linked cast, or annotate existing ones.

    Only the given roles (or the given names) are imported. A character that
    already exists under the name, an alias or a unique part of the name
    (`match_existing`) keeps its name; it gains the published facts once and
    the published name as an alias, and is reported as matched. A name part
    that fits several cast members creates nothing and is reported as
    ambiguous, for a person to settle.
    """
    cast = get(db, series_id, season=season)
    if cast is None:
        raise KeyError(f"{series_id} has no published cast linked")
    wanted_roles = {r.upper() for r in roles}
    wanted_names = {identity._fold(n) for n in names} if names is not None else None
    created, matched, ambiguous = [], [], []
    members = cast.get("characters") or []
    # Only characters that existed before this import can match, each once:
    # one created a moment ago is the cast member itself, not evidence.
    before = identity.characters(db, series_id)
    for c in members:
        if wanted_names is not None:
            if identity._fold(c["name"]) not in wanted_names:
                continue
        elif c.get("role") not in wanted_roles:
            continue
        published = {"source": cast["source"], "source_id": c.get("source_id"),
                     "url": c.get("url"), "role": c.get("role"), "gender": c.get("gender"),
                     "age": c.get("age"), "voice_actors": c.get("voice_actors") or [],
                     "linked_at": records.now_marker()}
        existing, rivals = match_existing(before, members, c)
        if rivals:
            ambiguous.append({"name": c["name"], "also": rivals})
            continue
        if existing is not None:
            before = [b for b in before if b["id"] != existing["id"]]
            existing = records.get(db, "character", existing["id"]) or existing
            patch: dict[str, Any] = {}
            if not existing.get("published"):
                patch["published"] = published
            aliases = list(existing.get("aliases") or [])
            if name_key(c["name"]) != name_key(existing["name"]) and c["name"] not in aliases:
                patch["aliases"] = [*aliases, c["name"]]
            if patch:
                records.update(db, "character", existing["id"], patch,
                               base_revision=existing["revision"])
            matched.append(f"{existing['name']} = {c['name']}")
            continue
        made = identity.ensure_character(db, series_id, c["name"], origin="published_cast",
                                         role=str(c.get("role") or "").lower())
        aliases = [a for a in c.get("alternative") or []
                   if identity.find_character(db, series_id, a) is None][:8]
        records.update(db, "character", made["id"], {"published": published, "aliases": aliases},
                       base_revision=made["revision"])
        created.append(c["name"])
    return {"created": created, "matched": matched, "ambiguous": ambiguous}
