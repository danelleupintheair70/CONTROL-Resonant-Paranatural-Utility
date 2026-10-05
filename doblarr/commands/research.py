"""Find out about a title before dubbing it, and keep the words it uses.

    doblarr lookup SERIES                  # catalogue ids, published cast, characters
    doblarr terms SERIES                   # the show's names and terms per locale
    doblarr terms SERIES add Dora=Tora [--locale es-419]
    doblarr terms SERIES approve ID | retire ID

`lookup` sends only the title and its ids out (Wikidata, then the anime
catalogues it names). A catalogue is linked only when Wikidata says which entry
is this title, so a search result is never linked on a guess. Characters are
created from the linked cast's main and supporting roles; existing ones are
matched, not duplicated.
"""

from __future__ import annotations

from dataclasses import replace

from .base import ApiError, Ctx, pairs

# Catalogue entry pages, keyed by the id names Wikidata gives them.
CATALOGUE_PAGES = {
    "anilist": "https://anilist.co/anime/{id}",
    "ann": "https://www.animenewsnetwork.com/encyclopedia/anime.php?id={id}",
    "kitsu": "https://kitsu.io/anime/{id}",
    "mal": "https://myanimelist.net/anime/{id}",
}


def catalogue_urls(external_ids: dict) -> list[tuple[str, str]]:
    return [(name, page.format(id=external_ids[name]))
            for name, page in CATALOGUE_PAGES.items() if external_ids.get(name)]


def lookup(ctx: Ctx, series: str, *, refresh: bool = False,
           roles: tuple[str, ...] = ("MAIN", "SUPPORTING")) -> dict:
    from .. import catalogues, published_cast
    from ..research import titles
    from ..store import Database

    catalogues.configure_from(ctx.config)
    db = Database(ctx.config.db_path)
    result: dict = {"series": series, "linked": [], "skipped": {}, "created": [],
                    "matched": []}
    try:
        info = titles.get(db, series)
        if refresh or not info or not info.get("external_ids"):
            ctx.say("looking the title up on wikidata.org")
            info = titles.refresh(db, series, tmdb_api_key=str(
                (ctx.config.get("research") or {}).get("tmdb_api_key") or ""))
        ids = dict(info.get("external_ids") or {})
        result["ids"] = ids
        have = set(published_cast.sources(db, series))
        for name, url in catalogue_urls(ids):
            source = "jikan" if name == "mal" else name
            if source in have and not refresh:
                continue
            try:
                linked = published_cast.link(db, series, url,
                                             why=f"Wikidata lists {name} id {ids[name]}")
                result["linked"].append({"source": source, "title": linked["title"],
                                         "characters": len(linked["characters"])})
                ctx.say(f"linked {source}: {linked['title']} "
                        f"({len(linked['characters'])} characters)")
            except Exception as exc:  # noqa: BLE001 - one catalogue down is not fatal
                result["skipped"][source] = str(exc)[:200]
                ctx.say(f"{source}: skipped ({str(exc)[:120]})")
        if published_cast.sources(db, series):
            done = published_cast.import_characters(db, series, roles=list(roles))
            result["created"], result["matched"] = done["created"], done["matched"]
        result["sources"] = published_cast.sources(db, series)
    finally:
        db.close()
    return result


def cmd_lookup(ctx: Ctx) -> int:
    info = lookup(ctx, ctx.args.series, refresh=ctx.args.refresh)
    ctx.result(info, [
        "ids: " + ", ".join(f"{k} {v}" for k, v in sorted(info.get("ids", {}).items())),
        "cast from: " + (", ".join(info.get("sources") or []) or "nothing linked "
                         "(no catalogue ids; `doblarr cast search` to link by hand)"),
        f"characters: {len(info['created'])} created, {len(info['matched'])} matched"])
    return 0


# -- terms ------------------------------------------------------------------------


def _scope(series: str) -> str:
    from ..identity import show_ref

    scope = show_ref(series)
    if not scope:
        raise ApiError(f"{series} is not a show; terms are kept per show")
    return scope


def cmd_terms(ctx: Ctx) -> int:
    from ..knowledge import store
    from ..knowledge.models import Entry
    from ..store import Database

    a = ctx.args
    scope = _scope(a.series)
    db = Database(ctx.config.db_path)
    try:
        entries = [e for e in store.latest_entries(db)
                   if e.scope == "show" and e.scope_ref == scope and e.kind == "term"
                   and (not a.locale or e.locale == a.locale)]
        if a.action == "add":
            added = []
            for source, phrase in pairs(a.values, "terms add"):
                for old in (e for e in entries if e.source_form == source
                            and e.status != "retired"):
                    store.save_entry(db, replace(old, status="retired",
                                                 revision=old.revision + 1))
                saved = store.save_entry(db, Entry(
                    phrase=phrase, kind="term", locale=a.locale or "es-419",
                    source_form=source, scope="show", scope_ref=scope, status="reviewed",
                    usage="kept from the command line"))
                added.append({"id": saved.id, "source": source, "phrase": phrase})
            ctx.result(added, [f"kept {x['source']} -> {x['phrase']} ({x['id']})"
                               for x in added])
            return 0
        if a.action in ("approve", "retire"):
            status = "reviewed" if a.action == "approve" else "retired"
            changed = []
            for entry_id in a.values:
                entry = next((e for e in entries if e.id.startswith(entry_id)), None)
                if entry is None:
                    raise ApiError(f"no term {entry_id} for this show")
                store.save_entry(db, replace(entry, status=status, revision=entry.revision + 1))
                changed.append(entry.id)
            ctx.result(changed, f"{status}: {', '.join(changed)}")
            return 0
        rows = [{"id": e.id, "status": e.status, "locale": e.locale, "source": e.source_form,
                 "phrase": e.phrase} for e in entries if e.status != "retired" or a.all]
        rows.sort(key=lambda r: (r["status"] != "proposed", r["source"].casefold()))
        ctx.result(rows, [f"{r['id'][:8]}  {r['status']:<9} {r['locale']:<6} "
                          f"{r['source']} -> {r['phrase']}" for r in rows]
                   or "no terms kept for this show yet")
        return 0
    finally:
        db.close()


def add_parsers(sub, common) -> None:
    lk = sub.add_parser("lookup", parents=[common],
                        help="look a title up: catalogue ids, published cast, characters")
    lk.add_argument("series", help="series id, e.g. show:tvdb:123 (see `doblarr analyze`)")
    lk.add_argument("--refresh", action="store_true", help="ask the catalogues again")

    t = sub.add_parser("terms", parents=[common], help="a show's names and terms per locale")
    t.add_argument("series")
    t.add_argument("action", nargs="?", choices=["add", "approve", "retire"])
    t.add_argument("values", nargs="*", help="add: SOURCE=PHRASE ...; approve/retire: ID ...")
    t.add_argument("--locale", default=None, help="only this locale (add: default es-419)")
    t.add_argument("--all", action="store_true", help="also list retired terms")


COMMANDS = {"lookup": cmd_lookup, "terms": cmd_terms}
