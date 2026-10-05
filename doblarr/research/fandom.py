"""Episode transcripts from Fandom wikis, and dub casts from the Dubbing Database.

Many fan wikis keep episode transcripts, with a speaker on every line, in a
`Transcript` namespace or as `.../Transcript` subpages. `probe` guesses a
show's wiki from its titles (or takes one a person names), lists those pages
through the wiki's public MediaWiki API, and keeps each transcript as a
`title_script` record. A page whose title names no episode number is matched
to an episode by the episode titles a linked catalogue lists.

The Dubbing Database (dubbing.fandom.com) lists which dubs a title has and
their casts in free text; `dubbing_database` reads a title's page and turns
the voices it names into cast leads, the same as a research run's.

Only the wiki name and page titles leave the machine; one request per second.
"""

from __future__ import annotations

import re

from .. import published_cast
from ..artifacts import digest
from ..catalogues import base
from ..catalogues.base import Fetch, Unreachable, name_key
from ..studio import records
from . import scripts

MIN_DIALOGUE = 3
DUBBING_WIKI = "dubbing"


def _api(wiki: str, lang: str = "") -> str:
    return f"https://{wiki}.fandom.com/{lang + '/' if lang else ''}api.php"


def page_url(wiki: str, page: str, lang: str = "") -> str:
    return (f"https://{wiki}.fandom.com/{lang + '/' if lang else ''}wiki/"
            + page.replace(" ", "_"))


def wiki_guesses(titles: list[str]) -> list[str]:
    """Wiki subdomains a title is likely to have: "harborlights", "harbor-lights"."""
    out: list[str] = []
    for title in titles:
        words = re.sub(r"[^a-z0-9 ]", "", name_key(re.split(r"[:(]", title)[0])).split()
        for guess in ("".join(words), "-".join(words), words[0] if words else ""):
            if len(guess) >= 3 and guess not in out:
                out.append(guess)
    return out


class Fandom:
    def __init__(self, fetch: Fetch | None = None):
        self._fetch = fetch

    def _query(self, wiki: str, params: dict, lang: str = "") -> dict:
        data = base.get_json(self._fetch, _api(wiki, lang),
                             params={"format": "json", **params}, interval=1.0)
        if not isinstance(data, dict):
            raise Unreachable(f"{wiki}.fandom.com answered something unexpected")
        if data.get("error"):
            raise LookupError(str(data["error"].get("info") or data["error"]))
        return data

    def namespaces(self, wiki: str, lang: str = "") -> dict[str, int]:
        data = self._query(wiki, {"action": "query", "meta": "siteinfo",
                                  "siprop": "namespaces"}, lang)
        return {str(v.get("*") or v.get("name") or ""): int(k)
                for k, v in (data.get("query") or {}).get("namespaces", {}).items()}

    def transcript_pages(self, wiki: str, lang: str = "", limit: int = 500) -> list[str]:
        pages: list[str] = []
        spaces = self.namespaces(wiki, lang)
        namespace = spaces.get("Transcript")
        if namespace is not None:
            cont: dict = {}
            for _ in range(5):
                data = self._query(wiki, {"action": "query", "list": "allpages",
                                          "apnamespace": namespace, "aplimit": 500, **cont},
                                   lang)
                pages += [p["title"] for p in data["query"]["allpages"]]
                cont = data.get("continue") or {}
                if not cont or len(pages) >= limit:
                    break
        data = self._query(wiki, {"action": "query", "list": "search", "srnamespace": 0,
                                  "srsearch": "intitle:Transcript", "srlimit": 50}, lang)
        pages += [p["title"] for p in (data.get("query") or {}).get("search") or []
                  if p["title"].endswith("/Transcript") or p["title"].startswith("Transcript")]
        return list(dict.fromkeys(pages))[:limit]

    def wikitext(self, wiki: str, page: str, lang: str = "") -> str:
        data = self._query(wiki, {"action": "parse", "page": page, "prop": "wikitext",
                                  "redirects": 1}, lang)
        return str(((data.get("parse") or {}).get("wikitext") or {}).get("*") or "")


def _titles(db, series_id: str) -> list[str]:
    titles = [published_cast.series_title(db, series_id)]
    for record in published_cast.links(db, series_id):
        titles += [record.get("title") or "", *(record.get("titles") or {}).values()]
    info = records.get(db, "title_info", series_id) or {}
    titles += [a.get("title") or "" for a in info.get("aliases") or []]
    return [t for t in dict.fromkeys(str(t) for t in titles if t) if str(t).isascii()]


def _episode(page: str, by_title: dict[str, int]) -> tuple[int | None, int | None]:
    season, episode = scripts.episode_of(page.split(":", 1)[-1])
    if episode is None:
        name = page.split(":", 1)[-1].removesuffix("/Transcript")
        episode = by_title.get(name_key(name))
    return season, episode


def probe(db, series_id: str, *, wiki: str = "", lang: str = "", fetch: Fetch | None = None,
          max_pages: int = 60) -> dict:
    """Find and keep a show's transcripts. A wiki that is not there is skipped quietly."""
    client = Fandom(fetch)
    tried: dict[str, str] = {}
    by_title = published_cast.episode_titles(db, series_id)
    for guess in [wiki] if wiki else wiki_guesses(_titles(db, series_id)):
        try:
            pages = client.transcript_pages(guess, lang)
        except (Unreachable, LookupError) as exc:
            tried[guess] = str(exc) or "not found"
            continue
        if not pages:
            tried[guess] = "no transcript pages"
            continue
        saved = []
        for page in pages[:max_pages]:
            try:
                lines = scripts.wikitext_lines(client.wikitext(guess, page, lang))
            except (Unreachable, LookupError):
                continue
            if scripts.summary(lines)["dialogue"] < MIN_DIALOGUE:
                continue
            season, episode = _episode(page, by_title)
            record = scripts.save(db, series_id, source=f"fandom:{guess}",
                                  url=page_url(guess, page, lang), lines=lines,
                                  kind="transcript", title=page, season=season,
                                  episode=episode, language=lang or "en")
            saved.append(record["id"])
        return {"wiki": guess, "pages": len(pages), "saved": saved, "tried": tried}
    return {"wiki": None, "pages": 0, "saved": [], "tried": tried}


def dubbing_database(db, series_id: str, ask, *, page: str = "",
                     fetch: Fetch | None = None) -> dict | None:
    """Read a title's Dubbing Database page; the voices it names become cast leads."""
    from . import agent

    client = Fandom(fetch)
    for title in [page] if page else _titles(db, series_id):
        try:
            text = client.wikitext(DUBBING_WIKI, title)
        except (Unreachable, LookupError):
            continue
        if not text.strip():
            continue
        plain = "\n".join(line["text"] for line in scripts.wikitext_lines(text))[:12000]
        url = page_url(DUBBING_WIKI, title)
        sources = [{"n": 1, "url": url, "title": title, "opened": True, "cited": True}]
        leads = agent._cast_leads(db, series_id, plain + " [1]", sources, ask)
        run_id = "rr-" + digest([series_id, url, records.now_marker()])[:16]
        return records.put(db, agent.KIND, run_id, {
            "series_id": series_id, "question": f"Dubbing Database: {title}", "sent": title,
            "model": getattr(ask, "model", ""), "depth": "page", "answer": plain[:4000],
            "report": plain[:4000], "sources": sources, "conflicts": [], "gaps": [],
            "warnings": [], "synthesis": "page", "cost": 0.0, "elapsed_s": 0.0,
            "created_at": records.now_marker(), "claim_id": None, "terms": [],
            "leads": leads}, scope=series_id)
    return None
