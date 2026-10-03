"""Ask the web a question about a title, through Prompture's research agent.

`research_title` sends one question (with the title, when the question does
not already name it) to Prompture's `ResearchAgent`: a keyless web search, a
few pages read, and one model that plans the searches and writes a Markdown
answer whose `[n]` citations point only at pages it opened. The run is kept
as a `research_run` record, so the answer can be read again without paying
for it twice.

What the answer finds lands for review, never applied:

- the cited answer becomes an external narrative claim (`proposed`), apart
  from what episodes taught;
- names and terms worth keeping become show- or film-scoped knowledge
  entries with status `proposed`, which the resolver ignores until a person
  reviews them (a personal entry would apply at once, so none is made);
- a dub voice the linked catalogues do not list becomes a cast lead on the
  run; a person accepts it with `accept_lead`.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .. import identity, published_cast
from ..artifacts import digest
from ..catalogues.base import name_key
from ..studio import records

log = logging.getLogger("doblarr.research")

KIND = "research_run"
LEADS_SOURCE = "research"
MAX_QUESTION = 500


class Term(BaseModel):
    source_form: str = Field(description="the wording in the original language, as written")
    source_lang: str = Field(default="", description="ISO 639-1 code of source_form, e.g. ja")
    phrase: str = Field(description="how the dub should say it in the target language")
    usage: str = Field(default="", description="when to use it, and why, citing [n]")
    register: Literal["formal", "neutral", "colloquial", "vulgar"] | None = None


class Terms(BaseModel):
    terms: list[Term] = Field(default_factory=list, max_length=40)


class Lead(BaseModel):
    character: str = Field(description="the character's name as the source writes it")
    language: str = Field(description="language of the dub, in English: Spanish, English...")
    voice_actor: str = Field(description="the person who voices the character in that dub")
    cited: list[int] = Field(default_factory=list, description="citation numbers [n] used")


class Leads(BaseModel):
    leads: list[Lead] = Field(default_factory=list, max_length=60)


TERMS_SYSTEM = (
    "You read a cited research answer about a show or film and list names and terms a "
    "dubbing team should keep consistent: proper names, places, organisations, invented "
    "words, honorifics and how the target-language dub renders them. Only list what the "
    "answer states, never guess a translation it does not give. Keep usage short and cite "
    "the [n] it came from. An empty list is a good answer.")
LEADS_SYSTEM = (
    "You read a cited research answer about a show or film and list every dub voice actor "
    "it names: which character, in which language's dub, played by whom. Only list what the "
    "answer states with a citation. An empty list is a good answer.")


def resolve_model(config) -> str:
    research = config.get("research") or {}
    model = str(research.get("model") or (config.get("analysis") or {}).get("knowledge_model")
                or "")
    if not model:
        try:
            from prompture.research import default_research_model

            model = default_research_model() or ""
        except ImportError:
            model = ""
    if not model:
        raise ValueError("choose a research model (research.model or "
                         "analysis.knowledge_model)")
    return model


def compose_query(db, series_id: str, question: str) -> str:
    """The text that leaves the machine: the question, with the title if it is missing."""
    question = " ".join(str(question or "").split())
    if not question:
        raise ValueError("a research run needs a question")
    if len(question) > MAX_QUESTION:
        raise ValueError(f"keep the question under {MAX_QUESTION} characters")
    title = published_cast.series_title(db, series_id)
    if title and name_key(title) not in name_key(question):
        kind = "film" if series_id.startswith("movie:") else "show"
        question = f'{question} (about the {kind} "{title}")'
    return question


def build_agent(config, model: str, on_event: Callable | None = None):
    from prompture.research import ResearchAgent, ResearchBudget

    research = config.get("research") or {}
    budget = ResearchBudget(max_cost=float(research.get("max_cost_usd") or 1.0))
    return ResearchAgent(model, depth=str(research.get("depth") or "quick"), budget=budget,
                         on_event=on_event)


def _plain(report: Any) -> dict:
    if isinstance(report, dict):
        return report
    return report.to_dict()


def research_title(db, series_id: str, question: str, *, config, agent=None, ask=None,
                   target_locale: str = "", on_event: Callable | None = None) -> dict:
    """Run one question, store it, and land what it found for review. Returns the run."""
    if not records.get(db, "series", series_id):
        raise KeyError(f"unknown series {series_id}")
    sent = compose_query(db, series_id, question)
    model = getattr(agent, "model", "") or resolve_model(config)
    agent = agent or build_agent(config, model, on_event)
    started = time.monotonic()
    report = agent.run(sent)
    data = _plain(report)
    markdown = report.to_markdown() if hasattr(report, "to_markdown") else data.get("answer", "")
    sources = [{"n": s.get("n"), "url": s.get("url"), "title": s.get("title") or "",
                "opened": bool(s.get("opened")), "cited": bool(s.get("cited"))}
               for s in data.get("sources") or [] if s.get("url")]
    run_id = "rr-" + digest([series_id, sent, records.now_marker()])[:16]
    run = {
        "series_id": series_id, "question": question, "sent": sent,
        "model": data.get("model") or model, "depth": data.get("depth") or "",
        "answer": data.get("answer") or "", "report": markdown,
        "sources": sources, "conflicts": data.get("conflicts") or [],
        "gaps": data.get("gaps") or [], "warnings": data.get("warnings") or [],
        "synthesis": data.get("synthesis") or "", "cost": float(data.get("cost") or 0.0),
        "elapsed_s": round(float(data.get("elapsed_s") or time.monotonic() - started), 1),
        "created_at": records.now_marker(), "claim_id": None, "terms": [], "leads": [],
    }
    answer = run["answer"].strip()
    if answer and run["synthesis"] != "none":
        cited = [s["url"] for s in sources if s["cited"]]
        claim = _land_claim(db, series_id, answer, run_id, cited)
        run["claim_id"] = claim["id"]
        if ask is None:
            from ..llm import Client

            ask = Client(run["model"])
        locale = target_locale or str((config.get("dub") or {}).get("target_locale") or "")
        run["terms"] = _land_terms(db, series_id, run_id, answer, sources, ask, locale, config)
        run["leads"] = _cast_leads(db, series_id, answer, sources, ask)
    return records.put(db, KIND, run_id, run, scope=series_id)


def _land_claim(db, series_id: str, answer: str, run_id: str, cited: list[str]) -> dict:
    from ..knowledge import narrative

    return narrative.add_external(db, series_id, series_id, answer[:2000],
                                  source=f"research:{run_id}",
                                  fetched_at=records.now_marker(), sources=cited[:20])


def _numbered(answer: str, sources: list[dict]) -> dict:
    return {"answer": answer[:12000],
            "sources": [{"n": s["n"], "title": s["title"], "url": s["url"]}
                        for s in sources if s.get("n") is not None]}


def knowledge_scope(db, series_id: str) -> tuple[str, str] | None:
    """Where research terms are kept: the show, or the film's file. None: nowhere safe."""
    ref = identity.show_ref(series_id)
    if ref:
        return "show", ref
    if series_id.startswith("movie:"):
        from ..voices import cast_key

        for media in records.list_latest(db, "media", scope=series_id):
            for revision in (media.get("revisions") or {}).values():
                for location in revision.get("locations") or []:
                    return "movie", cast_key(path=location)
    return None


def _land_terms(db, series_id, run_id, answer, sources, ask, locale, config) -> list[dict]:
    from ..languages import base_language, parse

    try:
        found = ask.ask(Terms, TERMS_SYSTEM, {**_numbered(answer, sources),
                                              "target_locale": locale or "es"})
    except Exception as exc:  # noqa: BLE001 - a failed extraction leaves the answer intact
        log.warning("research: term extraction failed: %s", exc)
        return []
    terms = [t.model_dump() for t in found.terms
             if t.source_form.strip() and t.phrase.strip()
             and max(len(t.source_form), len(t.phrase)) <= 300]
    if not terms:
        return []
    target = parse(locale or "") or "es"
    for t in terms:
        t["source_lang"] = base_language(parse(t.get("source_lang") or "") or "") or "und"
    _write_candidates(config, run_id, target, terms)
    scope = knowledge_scope(db, series_id)
    if scope is None:
        return [{**t, "entry_id": None} for t in terms]
    from ..knowledge import save_entry
    from ..knowledge.models import Entry

    out = []
    for t in terms:
        entry = save_entry(db, Entry(
            phrase=t["phrase"].strip(), kind="term", locale=target,
            source_lang=None if t["source_lang"] == "und" else t["source_lang"],
            source_form=t["source_form"].strip(), usage=(t.get("usage") or "")[:1800],
            register=t.get("register"), scope=scope[0], scope_ref=scope[1],
            status="proposed", contributor=f"Title research {run_id}"))
        out.append({**t, "entry_id": entry.id})
    return out


def _write_candidates(config, run_id, locale, terms) -> None:
    """The same terms as JSONL for scripts/import_knowledge_candidates.py."""
    try:
        folder = Path(config.work_dir) / "research" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "candidates.jsonl").open("w", encoding="utf-8") as out:
            for t in terms:
                out.write(json.dumps({"source_lang": t["source_lang"], "locale": locale,
                                      "source_form": t["source_form"], "phrase": t["phrase"],
                                      "usage": t.get("usage") or "",
                                      "register": t.get("register")},
                                     ensure_ascii=False) + "\n")
    except (OSError, TypeError, AttributeError):
        log.warning("research: could not write the candidates file for %s", run_id)


def _cast_leads(db, series_id, answer, sources, ask) -> list[dict]:
    """Dub voices the answer names that no linked catalogue lists."""
    try:
        found = ask.ask(Leads, LEADS_SYSTEM, _numbered(answer, sources))
    except Exception as exc:  # noqa: BLE001 - leads are optional
        log.warning("research: cast-lead extraction failed: %s", exc)
        return []
    merged = published_cast.merged_cast(db, series_id)["characters"]
    by_n = {s["n"]: s["url"] for s in sources if s.get("n") is not None}
    out = []
    for lead in found.leads:
        if not (lead.character.strip() and lead.voice_actor.strip() and lead.language.strip()):
            continue
        row = next((r for r in merged
                    if published_cast._same_person(r, {"name": lead.character})), None)
        known = any(name_key(v["name"]) == name_key(lead.voice_actor)
                    and str(v.get("language") or "").casefold() == lead.language.casefold()
                    for v in (row or {}).get("voice_actors") or [])
        if known:
            continue
        out.append({"character": lead.character.strip(),
                    "matches": row["name"] if row else None,
                    "language": lead.language.strip().title(),
                    "voice_actor": lead.voice_actor.strip(),
                    "urls": [by_n[n] for n in lead.cited if n in by_n], "state": "open"})
    return out


def runs(db, series_id: str) -> list[dict]:
    return sorted(records.list_latest(db, KIND, scope=series_id),
                  key=lambda r: str(r.get("created_at") or ""), reverse=True)


def accept_lead(db, run_id: str, index: int, *, reviewer: str = "you") -> dict:
    """A person confirms a cast lead: it joins the series' `research` cast record."""
    run = records.get(db, KIND, run_id)
    if run is None:
        raise KeyError(f"no research run {run_id}")
    leads = list(run.get("leads") or [])
    if not 0 <= index < len(leads):
        raise KeyError(f"run {run_id} has no lead {index}")
    lead = leads[index]
    series_id = run["series_id"]
    rid = published_cast.record_id(series_id, source=LEADS_SOURCE)
    current = records.get(db, published_cast.KIND, rid)
    document = {k: v for k, v in (current or {}).items()
                if k not in ("id", "revision", "scope", "updated_at")} or {
        "series_id": series_id, "season": None, "source": LEADS_SOURCE, "source_id": None,
        "url": None, "title": "Accepted research leads", "titles": {}, "characters": [],
        "staff": [], "complete": False, "linked_by": "person"}
    characters = list(document.get("characters") or [])
    name = lead.get("matches") or lead["character"]
    member = next((c for c in characters if name_key(c["name"]) == name_key(name)), None)
    if member is None:
        member = {"source_id": None, "name": name, "native": "", "alternative": [], "role": "",
                  "gender": None, "age": None, "description": "", "episodes": [],
                  "voice_actors": [], "url": None}
        characters.append(member)
    member["voice_actors"] = [*member["voice_actors"],
                              {"name": lead["voice_actor"], "native": "",
                               "language": lead["language"], "urls": lead.get("urls") or [],
                               "run": run_id}]
    document.update(characters=characters, fetched_at=records.now_marker())
    records.put(db, published_cast.KIND, rid, document, scope=series_id,
                base_revision=current["revision"] if current else 0)
    leads[index] = {**lead, "state": "accepted", "reviewer": reviewer}
    return records.update(db, KIND, run_id, {"leads": leads}, base_revision=run["revision"])


def dismiss_lead(db, run_id: str, index: int, *, reviewer: str = "you") -> dict:
    run = records.get(db, KIND, run_id)
    if run is None:
        raise KeyError(f"no research run {run_id}")
    leads = list(run.get("leads") or [])
    if not 0 <= index < len(leads):
        raise KeyError(f"run {run_id} has no lead {index}")
    leads[index] = {**leads[index], "state": "dismissed", "reviewer": reviewer}
    return records.update(db, KIND, run_id, {"leads": leads}, base_revision=run["revision"])
