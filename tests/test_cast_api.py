"""The published-cast API: search is gated by research.enabled, reads are not."""

from types import SimpleNamespace

import pytest

from doblarr import catalogues, identity
from doblarr.catalogues import base
from doblarr.catalogues.anilist import AniList
from doblarr.catalogues.ann import ANN

from .test_catalogues import ANN_ENTRY, ANN_SEARCH, recorder

SERIES = "show:tvdb:4242"


@pytest.fixture(autouse=True)
def _fresh_cache():
    base.clear_memory()
    yield
    base.configure(cache_dir=None, cache_days=30)
    base.clear_memory()


def fake_anilist():
    def search(query, **kwargs):
        return [{"id": 123, "title": "Harbor Lights", "year": 2001, "format": "TV",
                 "episodes": 12, "url": "https://anilist.co/anime/123"}]

    def read(url, **kwargs):
        return SimpleNamespace(reader="anilist", title="Harbor Lights", meta={
            "id": 123, "page_url": url, "titles": {"english": "Harbor Lights"}, "format": "TV",
            "year": 2001, "episodes": 12, "more_characters": False, "characters": [
                {"id": 1, "name": "Mira Tavel", "role": "MAIN", "gender": "Female",
                 "voice_actors": [{"name": "Aki Sora", "native": "", "language": "Japanese"}],
                 "url": "https://anilist.co/character/1"}]})
    return AniList(search_fn=search, read_fn=read)


@pytest.fixture
def client(client_factory, monkeypatch):
    monkeypatch.setitem(catalogues.PROVIDERS, "anilist", fake_anilist())
    monkeypatch.setitem(catalogues.PROVIDERS, "ann", ANN(fetch=recorder({
        '"anime": 77': ANN_ENTRY, "~": ANN_SEARCH})))
    made = client_factory({"research.enabled": True})
    identity.ensure_series(made.app.state.jobs.db, SERIES, {"provider": "tvdb"},
                           "Harbor Lights")
    return made


def test_search_is_refused_while_research_is_off(client_factory):
    off = client_factory()
    response = off.get("/api/published-cast/search", params={"series_id": SERIES, "query": "x"})
    assert response.status_code == 403 and "Settings" in response.json()["error"]
    assert off.get("/api/published-cast", params={"series_id": SERIES}).status_code == 200


def test_search_link_suggest_and_merge(client):
    found = client.get("/api/published-cast/search", params={"series_id": SERIES}).json()
    assert found["query"] == "Harbor Lights" and found["sent_to"] == ["anilist.co"]
    url = found["hits"]["anilist"][0]["url"]
    linked = client.post("/api/published-cast/link", json={"series_id": SERIES, "url": url}).json()
    assert linked == {"id": SERIES, "source": "anilist", "title": "Harbor Lights",
                      "characters": 1, "complete": True}

    suggested = client.get("/api/published-cast/suggest", params={"series_id": SERIES,
                                                        "source": "ann"}).json()
    top = suggested["hits"][0]
    assert top["id"] == 77 and "same year" in top["why"]
    client.post("/api/published-cast/link", json={"series_id": SERIES, "url": top["url"],
                                        "why": top["why"]})

    cast = client.get("/api/published-cast", params={"series_id": SERIES}).json()
    assert [s["source"] for s in cast["sources"]] == ["anilist", "ann"]
    mira = cast["characters"][0]
    assert {v["language"] for v in mira["voice_actors"]} == {"Japanese", "English", "Spanish"}
    assert {link["source"] for link in cast["links"]} == {"anilist", "ann"}

    imported = client.post("/api/published-cast/import", json={"series_id": SERIES}).json()
    assert imported["created"] == ["Mira Tavel"]
    series = client.get("/api/published-cast/series").json()["series"]
    assert series[0]["sources"] == ["anilist", "ann"]


def test_errors_are_specific(client):
    assert client.post("/api/published-cast/link", json={"series_id": SERIES,
                                               "url": "https://example.com/x"}
                       ).status_code == 422
    assert client.post("/api/published-cast/import", json={"series_id": SERIES}).status_code == 404
    assert client.get("/api/published-cast/search", params={"series_id": SERIES,
                                                  "source": "nowhere"}).status_code == 422
    assert client.post("/api/published-cast/link", json={"series_id": SERIES, "url": "x" * 9,
                                               "extra": 1}).status_code == 422


def test_an_unreachable_catalogue_reports_503(client, monkeypatch):
    def down(*a, **k):
        raise base.Unreachable("cdn.animenewsnetwork.com did not answer")

    client.post("/api/published-cast/link", json={"series_id": SERIES,
                                        "url": "https://anilist.co/anime/123"})
    monkeypatch.setitem(catalogues.PROVIDERS, "ann", ANN(fetch=down))
    response = client.get("/api/published-cast/suggest",
                          params={"series_id": SERIES, "source": "ann"})
    assert response.status_code == 503 and "did not answer" in response.json()["error"]
