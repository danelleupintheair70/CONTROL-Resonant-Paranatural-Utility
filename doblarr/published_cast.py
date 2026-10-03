"""The published cast of a series: who the characters are, from a public source.

An analysis learns who speaks from the episode itself. A public catalogue
already knows the cast of a published show: each character's role, gender,
sometimes an age, a description and the voice actors in each language. This
module fetches that list once per series, so later stages can match what they
hear and see against real characters instead of naming voices from scratch.

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
- `merged_cast` lays the records of several catalogues side by side: one row
  per character with the sources that list it and every language's voices.
  Where catalogues disagree (gender, age) the row says so; nothing picks one.

AniList is the first choice; ANN, MyAnimeList (Jikan) and Bangumi add dub
casts and other scripts (`doblarr.catalogues`). A record's id carries its
source (`<series>#ann`, `<series>#ann#s2`); AniList's keeps the plain id
(`<series>`, `<series>#s2`) it had before there were other sources.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from . import catalogues, identity
from .catalogues.anilist import AniList
from .catalogues.base import ROLES, CastProvider, name_key
from .studio import records

KIND = "published_cast"
SOURCE = catalogues.PRIMARY
__all__ = ["ROLES", "name_key"]

# "episode 14", "episodes 3 and 5", "Episode #4", "episodes 7-9", "ep. 12"
_EPISODES = re.compile(
    r"\bep(?:isode)?s?\.?\s*#?\s*(\d{1,4}(?:\s*(?:,|and|&|-|–|to)\s*#?\s*\d{1,4})*)",
    re.IGNORECASE)
_NUMBER = re.compile(r"\d{1,4}")
_RANGE = re.compile(r"(\d{1,4})\s*(?:-|–|to)\s*(\d{1,4})")
# Catalogue formats that fit a show or a film, for ordering search results.
SHOW_FORMATS = ("TV", "TV_SHORT", "ONA")
FILM_FORMATS = ("MOVIE",)

SearchFn = Callable[..., list[dict]]
ReadFn = Callable[..., Any]


def record_id(series_id: str, season: int | None = None, source: str = SOURCE) -> str:
    rid = series_id if source == SOURCE else f"{series_id}#{source}"
    return f"{rid}#s{int(season)}" if season is not None else rid


def source_of(record: dict) -> str:
    """A record's catalogue; records from before there were others are AniList."""
    return str(record.get("source") or SOURCE)


def _provider(source: str | None, *, search_fn: SearchFn | None = None,
              read_fn: ReadFn | None = None, url: str = "") -> CastProvider:
    # search_fn/read_fn are Prompture-shaped stand-ins for AniList (tests, or a
    # caller that already holds a reader).
    if search_fn is not None or read_fn is not None:
        return AniList(search_fn=search_fn, read_fn=read_fn)
    if source:
        return catalogues.provider(source)
    found = catalogues.for_url(url)
    if found is None:
        raise ValueError(f"{url} is not a title page of a known catalogue")
    return found


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
           search_fn: SearchFn | None = None, source: str = SOURCE) -> list[dict]:
    """Catalogue entries that might be this title, best match first. Stores nothing.

    `kind` ("show" or "movie", from the series id) moves the entries of that
    format to the front: a show's search also returns its films.
    """
    query = " ".join(str(query or "").split())
    if not query:
        raise ValueError("a search needs a title")
    hits = _provider(source, search_fn=search_fn).search(query, max_results=max_results)
    preferred = {"show": SHOW_FORMATS, "movie": FILM_FORMATS}.get(kind, ())
    if preferred:
        hits = sorted(hits, key=lambda h: h.get("format") not in preferred)
    return hits


def search_all(query: str, *, kind: str = "", max_results: int = 5,
               sources: Iterable[str] | None = None) -> dict:
    """Every catalogue's entries for a title; one that cannot answer is listed as skipped."""
    found: dict[str, list[dict]] = {}
    skipped: dict[str, str] = {}
    for name in sources or list(catalogues.PROVIDERS):
        try:
            found[name] = search(query, kind=kind, max_results=max_results, source=name)
        except (catalogues.Unreachable, LookupError, RuntimeError) as exc:
            skipped[name] = str(exc)
    return {"hits": found, "skipped": skipped}


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
         max_characters: int = 100, read_fn: ReadFn | None = None,
         source: str | None = None, why: str = "") -> dict:
    """Record that a person chose this catalogue entry for the series, with its cast.

    The catalogue is the one whose pages the URL belongs to, unless named.
    `why` keeps the person's reason when they confirmed a suggested match.
    """
    if not records.get(db, "series", series_id):
        raise KeyError(f"unknown series {series_id}")
    reader = _provider(source, read_fn=read_fn, url=url)
    found = reader.read(url, max_characters=max_characters, fresh=True)
    characters = [_character(c) for c in found["characters"] if c.get("name")]
    document = {
        "series_id": series_id,
        "season": season,
        "source": reader.name,
        "source_id": found.get("source_id"),
        "url": found.get("url") or url,
        "title": found.get("title") or "",
        "titles": found.get("titles") or {},
        "format": found.get("format"),
        "year": found.get("year"),
        "episodes": found.get("episodes"),
        "characters": characters,
        "staff": found.get("staff") or [],
        "episode_titles": found.get("episode_titles") or {},
        "complete": bool(found.get("complete", True)),
        "linked_by": "person",
        "fetched_at": records.now_marker(),
    }
    if why:
        document["why"] = str(why)[:400]
    rid = record_id(series_id, season, reader.name)
    current = records.get(db, KIND, rid)
    return records.put(db, KIND, rid, document, scope=series_id,
                       base_revision=current["revision"] if current else 0)


def refresh(db, series_id: str, *, season: int | None = None, source: str | None = None,
            read_fn: ReadFn | None = None) -> dict:
    """Fetch the linked entry again (the catalogue may have grown)."""
    current = get(db, series_id, season=season, source=source)
    if current is None:
        raise KeyError(f"{series_id} has no published cast linked")
    return link(db, series_id, current["url"], season=season,
                max_characters=max(100, len(current.get("characters") or [])), read_fn=read_fn,
                source=None if read_fn else source_of(current), why=current.get("why") or "")


def get(db, series_id: str, *, season: int | None = None,
        source: str | None = None) -> dict | None:
    """The linked cast for a season, falling back to the whole-series link.

    Without a source, AniList's record when there is one, else the first
    other catalogue a person linked.
    """
    if source is not None:
        if season is not None:
            found = records.get(db, KIND, record_id(series_id, season, source))
            if found is not None:
                return found
        return records.get(db, KIND, record_id(series_id, source=source))
    for name in sources(db, series_id):
        found = get(db, series_id, season=season, source=name)
        if found is not None:
            return found
    return None


def links(db, series_id: str) -> list[dict]:
    return records.list_latest(db, KIND, scope=series_id)


def sources(db, series_id: str) -> list[str]:
    """The catalogues linked for a series, AniList first, then in link order."""
    names: list[str] = []
    for record in sorted(links(db, series_id), key=lambda r: str(r.get("fetched_at") or "")):
        if source_of(record) not in names:
            names.append(source_of(record))
    return sorted(names, key=lambda n: n != SOURCE)


def episode_titles(db, series_id: str) -> dict[str, int]:
    """Episode titles the linked catalogues list, folded, to their numbers."""
    out: dict[str, int] = {}
    for record in links(db, series_id):
        for number, title in (record.get("episode_titles") or {}).items():
            if str(number).isdigit():
                out.setdefault(name_key(title), int(number))
    return out


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


def _cast_names(c: dict) -> list[str]:
    return [n for n in (c.get("name"), c.get("native"), *(c.get("alternative") or [])) if n]


def _words(c: dict) -> set[str]:
    return {w for n in _cast_names(c) for w in name_key(n).split()}


def _same_person(a: dict, b: dict) -> bool:
    """Two catalogues' entries are one character when a name matches, in any order."""
    keys_a = {name_key(n) for n in _cast_names(a)}
    keys_b = {name_key(n) for n in _cast_names(b)}
    if keys_a & keys_b:
        return True
    words_a = {" ".join(sorted(k.split())) for k in keys_a if " " in k}
    return bool(words_a & {" ".join(sorted(k.split())) for k in keys_b if " " in k})


def merged_cast(db, series_id: str, *, season: int | None = None) -> dict:
    """Every linked catalogue's cast side by side, one row per character.

    Each row keeps which sources list the character and every voice by
    language, each voice with the sources that credit it. Facts the sources
    disagree on are listed under `conflicts` and on the row; none is chosen.
    """
    rows: list[dict] = []
    used: list[dict] = []
    seen_values: list[dict] = []
    for name in sources(db, series_id):
        record = get(db, series_id, season=season, source=name)
        if record is None:
            continue
        used.append({"source": name, "title": record.get("title"), "url": record.get("url"),
                     "season": record.get("season"), "complete": record.get("complete"),
                     "fetched_at": record.get("fetched_at"), "why": record.get("why") or "",
                     "characters": len(record.get("characters") or []),
                     "staff": record.get("staff") or []})
        for c in record.get("characters") or []:
            at = next((i for i, r in enumerate(rows)
                       if name not in r["sources"] and _same_person(r, c)), None)
            if at is None:
                rows.append({**c, "alternative": list(c.get("alternative") or []),
                             "sources": [], "voice_actors": [], "conflicts": [], "urls": {}})
                seen_values.append({})
                at = len(rows) - 1
            row, values = rows[at], seen_values[at]
            row["sources"].append(name)
            row["urls"][name] = c.get("url")
            known = {name_key(n) for n in _cast_names(row)}
            for alias in _cast_names(c):
                if name_key(alias) not in known:
                    row["alternative"].append(alias)
                    known.add(name_key(alias))
            for field in ("role", "gender", "age", "description", "native"):
                if c.get(field) and not row.get(field):
                    row[field] = c[field]
            for field in ("gender", "age"):
                if c.get(field):
                    values.setdefault(field, {})[name] = c[field]
            for v in c.get("voice_actors") or []:
                same = next((x for x in row["voice_actors"]
                             if x.get("language") == v.get("language")
                             and name_key(x["name"]) == name_key(v.get("name") or "")), None)
                if same is None:
                    row["voice_actors"].append({**v, "sources": [name]})
                elif name not in same["sources"]:
                    same["sources"].append(name)
    conflicts = []
    for row, values in zip(rows, seen_values, strict=True):
        for field, seen in values.items():
            if len({str(v).casefold() for v in seen.values()}) > 1:
                row["conflicts"].append(field)
                conflicts.append({"name": row["name"], "field": field, "values": seen})
    return {"series_id": series_id, "season": season, "sources": used, "characters": rows,
            "conflicts": conflicts}


def suggest_links(db, series_id: str, source: str, *, season: int | None = None,
                  max_results: int = 5) -> list[dict]:
    """Entries of another catalogue that may be the title already linked, likeliest first.

    Searches by the linked title and ranks by matching title, year and episode
    count. Stores nothing: a person confirms one with `link(..., why=...)`.
    """
    linked = get(db, series_id, season=season)
    if linked is None:
        raise KeyError(f"{series_id} has no published cast linked")
    titles = [str(t) for t in [linked.get("title"), *(linked.get("titles") or {}).values()]
              if t]
    if not titles:
        raise ValueError("the linked entry has no title to search with")
    query = next((t for t in titles if t.isascii()), titles[0])
    hits = search(query, kind="movie" if series_id.startswith("movie:") else "show",
                  max_results=max_results, source=source)
    known = {name_key(t) for t in titles}

    def checks(h: dict) -> tuple[bool, bool, bool]:
        names = {name_key(str(t)) for t in [h.get("title"), *(h.get("titles") or {}).values()]
                 if t}
        return (bool(known & names),
                bool(h.get("year") and h.get("year") == linked.get("year")),
                bool(h.get("episodes") and h.get("episodes") == linked.get("episodes")))

    out = []
    for h in sorted(hits, key=lambda h: tuple(not ok for ok in checks(h))):
        reasons = [label for label, ok in zip(("same title", "same year", "same episode count"),
                                              checks(h), strict=True) if ok]
        out.append({**h, "why": ", ".join(reasons) or "title search only"})
    return out


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
                      roles: Iterable[str] = ("MAIN",), names: Iterable[str] | None = None,
                      source: str | None = None) -> dict:
    """Create series characters from the linked cast, or annotate existing ones.

    Only the given roles (or the given names) are imported. A character that
    already exists under the name, an alias or a unique part of the name
    (`match_existing`) keeps its name; it gains the published facts once and
    the published name as an alias, and is reported as matched. A name part
    that fits several cast members creates nothing and is reported as
    ambiguous, for a person to settle. The published facts carry the voices
    every linked catalogue credits, each with its sources.
    """
    cast = get(db, series_id, season=season, source=source)
    if cast is None:
        raise KeyError(f"{series_id} has no published cast linked")
    merged = merged_cast(db, series_id, season=season)["characters"]
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
        row = next((r for r in merged if source_of(cast) in r["sources"]
                    and _same_person(r, c)), None)
        published = {"source": source_of(cast), "source_id": c.get("source_id"),
                     "url": c.get("url"), "role": c.get("role"), "gender": c.get("gender"),
                     "age": c.get("age"),
                     "voice_actors": (row or {}).get("voice_actors") or c.get("voice_actors")
                     or [],
                     "sources": (row or {}).get("sources") or [source_of(cast)],
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
