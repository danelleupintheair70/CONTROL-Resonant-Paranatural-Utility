"""A title's ids (Wikidata) and other names (TMDB), each source skipped quietly."""

import pytest

from doblarr import identity
from doblarr.catalogues import base, tmdb, wikidata
from doblarr.catalogues.base import Unreachable
from doblarr.research import titles
from doblarr.store import Database
from doblarr.studio import records

from .test_catalogues import recorder

SERIES = "show:tvdb:4242"


@pytest.fixture(autouse=True)
def _fresh_cache():
    base.configure(cache_dir=None)
    base.clear_memory()
    yield
    base.clear_memory()


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "titles.db")
    identity.ensure_series(database, SERIES, {"provider": "tvdb"}, "Harbor Lights")
    yield database
    database.close()


def binding(**values):
    return {k: {"value": v} for k, v in values.items()}


WIKIDATA = {"results": {"bindings": [binding(item="http://www.wikidata.org/entity/Q1",
                                             tvdb="4242", ann="77", mal="5", tmdb_tv="900")]}}
TMDB = {
    "/alternative_titles": {"results": [{"iso_3166_1": "MX", "title": "Luces del Puerto",
                                         "type": ""}]},
    "/translations": {"translations": [
        {"iso_3166_1": "ES", "iso_639_1": "es", "data": {"name": "Luces del Puerto"}},
        {"iso_3166_1": "JP", "iso_639_1": "ja", "data": {"name": "港の灯"}},
        {"iso_3166_1": "DE", "iso_639_1": "de", "data": {"name": ""}}]},
}


def test_the_query_unions_every_known_id_and_escapes_values():
    query = wikidata.query_for({"tvdb": '42"42', "anilist": "1", "unknown": "x"})
    assert '{ ?item wdt:P4835 "4242" } UNION { ?item wdt:P8729 "1" }' in query
    with pytest.raises(ValueError):
        wikidata.query_for({"unknown": "x"})


def test_ids_that_point_at_two_titles_are_not_trusted():
    split = {"results": {"bindings": [binding(item="Q1", ann="1"), binding(item="Q2", ann="2")]}}
    assert wikidata.external_ids({"ann": "1", "tvdb": "9"},
                                 fetch=recorder({"sparql": split})) == {}


def test_refresh_keeps_ids_and_names(db):
    fetch = recorder({"sparql": WIKIDATA, **TMDB})
    info = titles.refresh(db, SERIES, tmdb_api_key="key", fetch=fetch)
    assert info["external_ids"] == {"tvdb": "4242", "ann": "77", "mal": "5", "tmdb_tv": "900",
                                    "wikidata": "Q1"}
    assert [(a["title"], a["language"], a["region"]) for a in info["aliases"]] == [
        ("Luces del Puerto", "", "MX"), ("Luces del Puerto", "es", "ES"), ("港の灯", "ja", "JP")]
    assert info["skipped"] == {}
    assert titles.aliases_for(db, SERIES, "ja")[0] == "港の灯"
    tmdb_call = next(c for c in fetch.calls if "themoviedb" in c[0])
    assert tmdb_call[0] == "https://api.themoviedb.org/3/tv/900/alternative_titles"


def test_a_linked_cast_supplies_an_id_and_missing_keys_are_skipped(db):
    records.put(db, "published_cast", SERIES, {"series_id": SERIES, "source": "anilist",
                                               "source_id": 123, "season": None,
                                               "characters": []}, scope=SERIES)
    assert titles.known_ids(db, SERIES) == {"tvdb": "4242", "anilist": "123"}

    def down(*a, **k):
        raise Unreachable("query.wikidata.org did not answer")

    info = titles.refresh(db, SERIES, fetch=down)
    assert info["skipped"] == {"wikidata": "query.wikidata.org did not answer",
                               "tmdb": "no TMDB id known for this title"}
    with pytest.raises(Unreachable):
        tmdb.names(1, "tv", api_key="")


def test_the_api(client_factory, monkeypatch):
    client = client_factory({"research.enabled": True})
    identity.ensure_series(client.app.state.jobs.db, SERIES, {"provider": "tvdb"},
                           "Harbor Lights")
    monkeypatch.setattr(wikidata, "external_ids", lambda known, fetch=None: {"ann": "77"})
    info = client.post("/api/research/titles", json={"series_id": SERIES}).json()
    assert info["external_ids"]["ann"] == "77" and "tmdb" in info["skipped"]
    shown = client.get("/api/research/titles", params={"series_id": SERIES}).json()
    assert shown["known"] == {"tvdb": "4242"} and shown["info"]["external_ids"]["ann"] == "77"
    assert client.post("/api/research/titles", json={"series_id": "show:tvdb:1"}
                       ).status_code == 404
