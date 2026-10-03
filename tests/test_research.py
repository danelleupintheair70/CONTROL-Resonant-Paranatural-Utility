"""Title research lands cited findings for review and applies nothing."""

from types import SimpleNamespace

import pytest

from doblarr import identity, published_cast
from doblarr.config import Config
from doblarr.knowledge import store as knowledge_store
from doblarr.knowledge.resolver import _entry_active
from doblarr.research import agent
from doblarr.store import Database
from doblarr.studio import records

SERIES = "show:tvdb:4242"
ANSWER = ("The Spanish dub calls the harbor guild la Cofradía del Puerto [1]. "
          "In the Latin American dub Mira Tavel is voiced by Lucia Prado [2].")


class FakeAgent:
    model = "ollama/fake"

    def __init__(self, answer=ANSWER, synthesis="llm"):
        self.asked = []
        self.answer = answer
        self.synthesis = synthesis

    def run(self, question):
        self.asked.append(question)
        return {"question": question, "answer": self.answer, "model": self.model,
                "depth": "quick", "cost": 0.0012, "elapsed_s": 12.5,
                "synthesis": self.synthesis, "gaps": ["no episode list"], "conflicts": [],
                "sources": [{"n": 1, "url": "https://wiki.example/guild", "title": "Guild",
                             "opened": True, "cited": True},
                            {"n": 2, "url": "https://dubs.example/harbor", "title": "Dub",
                             "opened": True, "cited": True},
                            {"n": None, "url": "https://unopened.example", "opened": False,
                             "cited": False}]}


class FakeAsk:
    def __init__(self, terms=(), leads=()):
        self.terms, self.leads, self.payloads = list(terms), list(leads), []

    def ask(self, schema, system, payload, **kw):
        self.payloads.append(payload)
        if schema is agent.Terms:
            return agent.Terms(terms=[agent.Term(**t) for t in self.terms])
        return agent.Leads(leads=[agent.Lead(**lead) for lead in self.leads])


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "research.db")
    identity.ensure_series(database, SERIES, {"provider": "tvdb"}, "Harbor Lights")
    yield database
    database.close()


@pytest.fixture
def config(tmp_path):
    return Config.load(tmp_path / "none.yaml").with_overrides({
        "paths.work_dir": str(tmp_path / "work"), "research.model": "ollama/fake"})


GUILD = {"source_form": "港組合", "source_lang": "ja", "phrase": "la Cofradía del Puerto",
         "usage": "Spanish dub's name for the guild [1]", "register": "formal"}
LEAD = {"character": "Mira Tavel", "language": "spanish", "voice_actor": "Lucia Prado",
        "cited": [2]}


def test_the_question_names_the_title_once():
    database = Database(":memory:")
    identity.ensure_series(database, SERIES, {"provider": "tvdb"}, "Harbor Lights")
    assert agent.compose_query(database, SERIES, "Who dubs Mira?") == \
        'Who dubs Mira? (about the show "Harbor Lights")'
    assert agent.compose_query(database, SERIES, "harbor lights   dub cast") == \
        "harbor lights dub cast"
    with pytest.raises(ValueError):
        agent.compose_query(database, SERIES, "  ")
    database.close()


def test_a_run_is_kept_and_lands_only_proposals(db, config):
    fake, ask = FakeAgent(), FakeAsk(terms=[GUILD], leads=[LEAD])
    run = agent.research_title(db, SERIES, "What does the dub call the guild?", config=config,
                               agent=fake, ask=ask, target_locale="es-MX")
    assert fake.asked == ['What does the dub call the guild? (about the show "Harbor Lights")']
    assert records.get(db, "research_run", run["id"])["answer"] == ANSWER
    assert [s["n"] for s in run["sources"]] == [1, 2, None]

    claim = records.get(db, "claim", run["claim_id"])
    assert claim["origin"] == "external" and claim["state"] == "proposed"
    assert claim["source"] == f"research:{run['id']}"
    assert claim["sources"] == ["https://wiki.example/guild", "https://dubs.example/harbor"]

    entry = knowledge_store.get_entry(db, run["terms"][0]["entry_id"])
    assert (entry.scope, entry.scope_ref, entry.status) == ("show", "series:4242", "proposed")
    assert entry.locale == "es-MX" and entry.source_lang == "ja" and entry.register == "formal"
    assert not _entry_active(entry)    # inert until a person reviews it
    candidates = (config.work_dir / "research" / run["id"] / "candidates.jsonl").read_text(
        encoding="utf-8")
    assert "la Cofradía del Puerto" in candidates

    assert run["leads"] == [{"character": "Mira Tavel", "matches": None, "language": "Spanish",
                             "voice_actor": "Lucia Prado", "urls": ["https://dubs.example/harbor"],
                             "state": "open"}]
    assert ask.payloads[0]["target_locale"] == "es-MX"


def test_leads_the_catalogues_already_list_are_dropped(db, config):
    published_cast.link(db, SERIES, "https://anilist.co/anime/1", read_fn=lambda u, **k:
                        SimpleNamespace(reader="anilist", title="Harbor Lights", meta={
                            "id": 1, "page_url": u, "titles": {}, "characters": [
                                {"id": 1, "name": "Mira Tavel", "role": "MAIN",
                                 "voice_actors": [{"name": "Lucia Prado", "native": "",
                                                   "language": "Spanish"}]}]}))
    run = agent.research_title(db, SERIES, "Spanish cast?", config=config, agent=FakeAgent(),
                               ask=FakeAsk(leads=[LEAD, {**LEAD, "voice_actor": "Ana Ruiz"}]))
    assert [(lead["voice_actor"], lead["matches"]) for lead in run["leads"]] == [
        ("Ana Ruiz", "Mira Tavel")]


def test_an_accepted_lead_joins_the_merged_cast(db, config):
    run = agent.research_title(db, SERIES, "Spanish cast?", config=config, agent=FakeAgent(),
                               ask=FakeAsk(leads=[LEAD]))
    saved = agent.accept_lead(db, run["id"], 0)
    assert saved["leads"][0]["state"] == "accepted"
    merged = published_cast.merged_cast(db, SERIES)
    assert merged["sources"][0]["source"] == "research"
    voice = merged["characters"][0]["voice_actors"][0]
    assert (voice["name"], voice["language"], voice["sources"]) == ("Lucia Prado", "Spanish",
                                                                    ["research"])
    with pytest.raises(KeyError):
        agent.accept_lead(db, run["id"], 5)


def test_no_answer_lands_nothing(db, config):
    run = agent.research_title(db, SERIES, "anything?", config=config,
                               agent=FakeAgent(answer="", synthesis="none"), ask=FakeAsk())
    assert run["claim_id"] is None and run["terms"] == [] and run["leads"] == []


def test_a_film_without_a_file_keeps_terms_out_of_knowledge(db, config):
    movie = "movie:tmdb:77"
    identity.ensure_series(db, movie, {"provider": "tmdb"}, "Harbor Lights: Tide")
    run = agent.research_title(db, movie, "names?", config=config, agent=FakeAgent(),
                               ask=FakeAsk(terms=[GUILD]))
    assert run["terms"][0]["entry_id"] is None
    assert agent.knowledge_scope(db, movie) is None


def test_a_model_is_required(tmp_path, monkeypatch):
    monkeypatch.setattr("prompture.research.default_research_model", lambda: None)
    bare = Config.load(tmp_path / "none.yaml")
    with pytest.raises(ValueError, match="research model"):
        agent.resolve_model(bare.with_overrides({"research.model": "",
                                                 "analysis.knowledge_model": ""}))
    assert agent.resolve_model(bare.with_overrides({"analysis.knowledge_model": "ollama/x"})) \
        == "ollama/x"


# -- API ---------------------------------------------------------------------

def test_the_api_queues_a_research_job(client_factory, monkeypatch):
    client = client_factory({"research.enabled": True, "research.model": "ollama/fake"})
    db = client.app.state.jobs.db
    identity.ensure_series(db, SERIES, {"provider": "tvdb"}, "Harbor Lights")
    queued = client.post("/api/research", json={"series_id": SERIES,
                                                "question": "Who dubs Mira?"}).json()
    assert queued["sent"] == 'Who dubs Mira? (about the show "Harbor Lights")'
    job = client.app.state.jobs.get(queued["job_id"])
    assert job.kind == "studio_research" and job.task["question"] == "Who dubs Mira?"

    from doblarr.studio import runner

    monkeypatch.setattr(agent, "build_agent", lambda config, model, on_event=None: FakeAgent())
    monkeypatch.setattr("doblarr.llm.Client", lambda model: FakeAsk(leads=[LEAD]))
    import threading

    message = runner.run(job, client.app.state.worker.config, db=db, services=None,
                         cancel=threading.Event())
    assert "1 cast lead(s)" in message
    listed = client.get("/api/research/runs", params={"series_id": SERIES}).json()["runs"]
    assert listed[0]["open_leads"] == 1
    run_id = listed[0]["id"]
    assert client.get(f"/api/research/runs/{run_id}").json()["answer"] == ANSWER
    decided = client.post("/api/research/leads", json={"run_id": run_id, "index": 0,
                                                       "decision": "dismiss"}).json()
    assert decided["leads"][0]["state"] == "dismissed"


def test_the_api_refuses_while_off_or_without_a_model(client_factory, monkeypatch):
    client = client_factory()
    response = client.post("/api/research", json={"series_id": SERIES, "question": "who?"})
    assert response.status_code == 403
    monkeypatch.setattr("prompture.research.default_research_model", lambda: None)
    on = client_factory({"research.enabled": True, "research.model": "",
                         "analysis.knowledge_model": ""})
    identity.ensure_series(on.app.state.jobs.db, SERIES, {"provider": "tvdb"}, "Harbor Lights")
    response = on.post("/api/research", json={"series_id": SERIES, "question": "who?"})
    assert response.status_code == 422 and "research model" in response.json()["error"]


def test_the_cli_prints_the_cited_answer_and_what_waits(tmp_path, monkeypatch, capsys):
    from doblarr import cli

    work = tmp_path / "work"
    config = tmp_path / "config.yaml"
    config.write_text(f"paths:\n  work_dir: '{work.as_posix()}'\nresearch:\n  model: ollama/fake\n",
                      encoding="utf-8")
    database = Database(work / "doblarr.db")
    identity.ensure_series(database, SERIES, {"provider": "tvdb"}, "Harbor Lights")
    database.close()
    monkeypatch.setattr(agent, "build_agent", lambda config, model, on_event=None: FakeAgent())
    monkeypatch.setattr("doblarr.llm.Client", lambda model: FakeAsk(terms=[GUILD], leads=[LEAD]))
    assert cli.main(["-c", str(config), "research", SERIES, "Guild name?"]) == 0
    out = capsys.readouterr().out
    assert "sends this question out" in out and "Cofradía del Puerto [1]" in out
    assert "term for review: 港組合 -> la Cofradía del Puerto" in out
    assert "cast lead: Mira Tavel (Spanish): Lucia Prado" in out
