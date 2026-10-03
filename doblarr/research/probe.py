"""Look for a title's reference scripts in every source a person chose.

Each source is tried on its own and fails quietly: one that is unreachable,
has no key, or simply does not have the title is reported as skipped with
why, and the others still run.
"""

from __future__ import annotations

from ..catalogues.base import Unreachable

SOURCES = ("fandom", "screenplays", "kitsunekko", "opensubtitles", "dubbing")


def probe_all(db, config, series_id: str, sources: list[str], *, wiki: str = "",
              lang: str = "", languages: str = "en", season: int | None = None,
              episode: int | None = None, ask=None) -> dict:
    research = config.get("research") or {}
    results: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for name in sources:
        try:
            if name == "fandom":
                from . import fandom

                results[name] = fandom.probe(db, series_id, wiki=wiki, lang=lang)
            elif name == "screenplays":
                from . import screenplays

                results[name] = screenplays.probe(db, series_id)
            elif name == "kitsunekko":
                from . import jpsubs

                mirror = str(research.get("kitsunekko_mirror") or "")
                if not mirror:
                    raise Unreachable("set research.kitsunekko_mirror to a local clone")
                results[name] = jpsubs.import_title(db, series_id, mirror)
            elif name == "opensubtitles":
                from . import opensubs

                results[name] = opensubs.fetch_title(
                    db, series_id, api_key=str(research.get("opensubtitles_api_key") or ""),
                    languages=languages, season=season, episode=episode)
            elif name == "dubbing":
                from . import agent, fandom

                if ask is None:
                    from ..llm import Client

                    ask = Client(agent.resolve_model(config))
                run = fandom.dubbing_database(db, series_id, ask)
                results[name] = {"run_id": run["id"] if run else None,
                                 "leads": len(run["leads"]) if run else 0}
            else:
                skipped[name] = "unknown source"
        except (Unreachable, LookupError, ValueError) as exc:
            skipped[name] = str(exc) or exc.__class__.__name__
    saved = sum(len(r.get("saved") or []) for r in results.values())
    return {"results": results, "skipped": skipped, "saved": saved}
