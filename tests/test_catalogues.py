"""Catalogue providers read recorded answers into the published-cast shape."""

import json

import pytest

from doblarr import catalogues, identity, published_cast
from doblarr.catalogues import base
from doblarr.catalogues.ann import ANN
from doblarr.catalogues.bangumi import Bangumi
from doblarr.catalogues.jikan import Jikan, given_first
from doblarr.store import Database
from doblarr.studio import records

SERIES = "show:tvdb:4242"

ANN_ENTRY = """<ann><anime id="77" gid="1" type="TV" name="Harbor Lights" precision="TV">
<info type="Main title" lang="EN">Harbor Lights</info>
<info type="Alternative title" lang="JA">Minato no Akari</info>
<info type="Number of episodes">12</info>
<info type="Vintage">2001-04-02 to 2001-06-25</info>
<cast lang="JA"><role>Mira Tavel</role><person id="1">Aki Sora</person></cast>
<cast lang="JA"><role>Oren Pask</role><person id="2">Ren Tomoe</person></cast>
<cast lang="EN"><role>Mira Tavel</role><person id="3">Dana Wells</person></cast>
<cast lang="ES"><role>Mira</role><person id="4">Lucia Prado</person></cast>
<cast lang="EN"><role>Oren Pask</role><person id="5">Sam Reed</person></cast>
<staff><task>Director</task><person id="9">Kaito Mina</person></staff>
<staff><task>ADR Director</task><person id="10">Pat Lane</person></staff>
</anime></ann>"""

ANN_SEARCH = ANN_ENTRY.replace("</ann>", """<anime id="78" type="movie" name="Harbor Lights: Tide">
<info type="Vintage">2003</info></anime></ann>""")


@pytest.fixture(autouse=True)
def _fresh_cache():
    base.configure(cache_dir=None)
    base.clear_memory()
    yield
    base.configure(cache_dir=None, cache_days=30)
    base.clear_memory()


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "cat.db")
    identity.ensure_series(database, SERIES, {"provider": "tvdb"}, "Harbor Lights")
    yield database
    database.close()


def recorder(answers):
    """A fetch stand-in: the first answer whose key is in the URL or params."""
    calls = []

    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        where = url + json.dumps(kwargs.get("params") or {}) + json.dumps(
            kwargs.get("json_body") or {})
        for key, answer in answers.items():
            if key in where:
                return answer if isinstance(answer, str) else json.dumps(answer)
        raise AssertionError(f"unexpected request {where}")
    fetch.calls = calls
    return fetch


def test_ann_reads_every_dub_and_folds_short_names():
    ann = ANN(fetch=recorder({'"anime": 77': ANN_ENTRY}))
    doc = ann.read("https://www.animenewsnetwork.com/encyclopedia/anime.php?id=77")
    assert doc["title"] == "Harbor Lights" and doc["year"] == 2001 and doc["episodes"] == 12
    mira = doc["characters"][0]
    assert mira["name"] == "Mira Tavel" and "Mira" in mira["alternative"]
    assert [(v["language"], v["name"]) for v in mira["voice_actors"]] == [
        ("Japanese", "Aki Sora"), ("English", "Dana Wells"), ("Spanish", "Lucia Prado")]
    assert mira["role"] == ""
    assert {"task": "ADR Director", "name": "Pat Lane"} in doc["staff"]


def test_ann_search_lists_entries_and_is_cached():
    fetch = recorder({"~Harbor Lights": ANN_SEARCH})
    ann = ANN(fetch=fetch)
    hits = ann.search("Harbor  Lights")
    assert [(h["id"], h["format"], h["year"]) for h in hits] == [(77, "TV", 2001),
                                                                 (78, "MOVIE", 2003)]
    assert hits[0]["url"].endswith("anime.php?id=77")
    ann.search("harbor lights")
    assert len(fetch.calls) == 1


def test_ann_batch_reads_fifty_at_a_time():
    fetch = recorder({"anime": ANN_ENTRY})
    ANN(fetch=fetch).entries(list(range(1, 61)))
    sent = [c[1]["params"]["anime"] for c in fetch.calls]
    assert len(sent) == 2 and sent[0].count("/") == 49


def test_an_unreachable_catalogue_is_skipped_not_fatal(monkeypatch):
    def down(*a, **k):
        raise base.Unreachable("api.jikan.moe did not answer: ConnectTimeout")

    monkeypatch.setitem(catalogues.PROVIDERS, "jikan", Jikan(fetch=down))
    monkeypatch.setitem(catalogues.PROVIDERS, "ann", ANN(fetch=recorder({"~": ANN_SEARCH})))
    found = published_cast.search_all("Harbor Lights", sources=["ann", "jikan"])
    assert [h["id"] for h in found["hits"]["ann"]] == [77, 78]
    assert "did not answer" in found["skipped"]["jikan"]


def test_jikan_reads_voices_per_language():
    answers = {
        "/anime/5/characters": {"data": [
            {"character": {"mal_id": 11, "name": "Pask, Oren", "url": "https://mal/c/11"},
             "role": "Supporting", "voice_actors": [
                 {"person": {"name": "Tomoe, Ren"}, "language": "Japanese"}]},
            {"character": {"mal_id": 10, "name": "Tavel, Mira", "url": "https://mal/c/10"},
             "role": "Main", "voice_actors": [
                 {"person": {"name": "Sora, Aki"}, "language": "Japanese"},
                 {"person": {"name": "Prado, Lucia"}, "language": "Spanish"}]}]},
        "/anime/5/staff": {"data": [{"person": {"name": "Mina, Kaito"},
                                     "positions": ["Director"]}]},
        "/anime/5": {"data": {"mal_id": 5, "title": "Harbor Lights", "type": "TV",
                              "year": 2001, "episodes": 12,
                              "url": "https://myanimelist.net/anime/5/Harbor_Lights"}},
    }
    doc = Jikan(fetch=recorder(answers)).read("https://myanimelist.net/anime/5")
    assert [c["name"] for c in doc["characters"]] == ["Mira Tavel", "Oren Pask"]
    assert doc["characters"][0]["role"] == "MAIN"
    assert doc["characters"][0]["voice_actors"][1] == {"name": "Lucia Prado", "native": "",
                                                       "language": "Spanish"}
    assert doc["staff"] == [{"task": "Director", "name": "Kaito Mina"}]
    assert given_first("Mira") == "Mira"


def test_bangumi_maps_relations_to_roles():
    answers = {
        "/subjects/9/characters": [
            {"id": 1, "name": "ミラ", "relation": "主角", "actors": [{"name": "空亜希"}]},
            {"id": 2, "name": "オレン", "relation": "客串", "actors": []}],
        "/subjects/9": {"id": 9, "name": "港の灯", "name_cn": "港灯", "date": "2001-04-02",
                        "platform": "TV", "eps": 12},
    }
    doc = Bangumi(fetch=recorder(answers)).read("https://bgm.tv/subject/9")
    assert doc["title"] == "港灯" and doc["year"] == 2001
    assert [(c["name"], c["role"]) for c in doc["characters"]] == [("ミラ", "MAIN"),
                                                                    ("オレン", "BACKGROUND")]
    assert doc["characters"][0]["voice_actors"][0]["language"] == ""


def _link_both(db, monkeypatch, anilist_cast):
    from types import SimpleNamespace

    def read(url, **kwargs):
        return SimpleNamespace(reader="anilist", title="Harbor Lights", meta={
            "id": 123, "page_url": url, "titles": {"english": "Harbor Lights"}, "format": "TV",
            "year": 2001, "episodes": 12, "characters": anilist_cast, "more_characters": False})

    published_cast.link(db, SERIES, "https://anilist.co/anime/123", read_fn=read)
    monkeypatch.setitem(catalogues.PROVIDERS, "ann", ANN(fetch=recorder({'"anime"': ANN_ENTRY})))
    return published_cast.link(db, SERIES,
                               "https://www.animenewsnetwork.com/encyclopedia/anime.php?id=77",
                               why="same title, same year")


def _anilist(cid, name, role, gender=None, voices=()):
    return {"id": cid, "name": name, "native": "", "alternative": [], "role": role,
            "gender": gender, "age": None, "description": "",
            "voice_actors": [{"name": n, "native": "", "language": lang} for lang, n in voices],
            "url": f"https://anilist.co/character/{cid}"}


def test_a_second_source_gets_its_own_record_beside_anilist(db, monkeypatch):
    ann = _link_both(db, monkeypatch, [_anilist(1, "Mira Tavel", "MAIN")])
    assert ann["id"] == f"{SERIES}#ann" and ann["why"] == "same title, same year"
    assert published_cast.sources(db, SERIES) == ["anilist", "ann"]
    assert published_cast.get(db, SERIES)["source"] == "anilist"
    assert published_cast.get(db, SERIES, source="ann")["source_id"] == 77


def test_records_from_before_sources_read_as_anilist(db):
    records.put(db, "published_cast", SERIES, {"series_id": SERIES, "characters": [],
                                               "title": "Harbor Lights", "url": "u"},
                scope=SERIES)
    assert published_cast.sources(db, SERIES) == ["anilist"]
    assert published_cast.get(db, SERIES, source="anilist")["title"] == "Harbor Lights"


def test_merged_cast_unions_voices_and_surfaces_conflicts(db, monkeypatch):
    cast = [_anilist(1, "Mira Tavel", "MAIN", "Female", [("Japanese", "Aki Sora")]),
            _anilist(2, "Pask Oren", "SUPPORTING", "Male")]
    _link_both(db, monkeypatch, cast)
    record = records.get(db, "published_cast", f"{SERIES}#ann")
    record["characters"][1]["gender"] = "Female"
    records.put(db, "published_cast", f"{SERIES}#ann",
                {k: v for k, v in record.items()
                 if k not in ("id", "revision", "scope", "updated_at")},
                scope=SERIES, base_revision=record["revision"])
    merged = published_cast.merged_cast(db, SERIES)
    assert [s["source"] for s in merged["sources"]] == ["anilist", "ann"]
    mira, oren = merged["characters"]
    assert mira["sources"] == ["anilist", "ann"] and mira["role"] == "MAIN"
    voices = {(v["language"], v["name"]): v["sources"] for v in mira["voice_actors"]}
    assert voices[("Japanese", "Aki Sora")] == ["anilist", "ann"]
    assert voices[("Spanish", "Lucia Prado")] == ["ann"]
    # "Pask Oren" and "Oren Pask" are one person written in two orders.
    assert oren["sources"] == ["anilist", "ann"] and oren["conflicts"] == ["gender"]
    assert merged["conflicts"] == [{"name": "Pask Oren", "field": "gender",
                                    "values": {"anilist": "Male", "ann": "Female"}}]


def test_import_carries_every_sources_voices(db, monkeypatch):
    _link_both(db, monkeypatch, [_anilist(1, "Mira Tavel", "MAIN", "Female",
                                          [("Japanese", "Aki Sora")])])
    published_cast.import_characters(db, SERIES)
    mira = identity.find_character(db, SERIES, "Mira Tavel")
    languages = {v["language"] for v in mira["published"]["voice_actors"]}
    assert languages == {"Japanese", "English", "Spanish"}
    assert mira["published"]["sources"] == ["anilist", "ann"]


def test_suggested_links_rank_by_title_and_year(db, monkeypatch):
    from types import SimpleNamespace

    published_cast.link(db, SERIES, "https://anilist.co/anime/123", read_fn=lambda u, **k:
                        SimpleNamespace(reader="anilist", title="Harbor Lights", meta={
                            "id": 123, "page_url": u, "titles": {}, "format": "TV",
                            "year": 2001, "episodes": 12, "characters": []}))
    monkeypatch.setitem(catalogues.PROVIDERS, "ann", ANN(fetch=recorder({"~": ANN_SEARCH})))
    found = published_cast.suggest_links(db, SERIES, "ann")
    assert found[0]["id"] == 77
    assert found[0]["why"] == "same title, same year, same episode count"
    assert published_cast.sources(db, SERIES) == ["anilist"]


def test_the_disk_cache_survives_a_new_process(tmp_path):
    base.configure(cache_dir=tmp_path, cache_days=1)
    calls = []
    assert base.cached("ann:x", lambda: calls.append(1) or {"v": 1}) == {"v": 1}
    base.clear_memory()
    assert base.cached("ann:x", lambda: calls.append(1) or {"v": 2}) == {"v": 1}
    assert len(calls) == 1
    assert base.cached("ann:x", lambda: {"v": 3}, fresh=True) == {"v": 3}


def test_unknown_urls_and_sources_are_refused(db):
    with pytest.raises(ValueError):
        published_cast.link(db, SERIES, "https://example.com/show/1")
    with pytest.raises(ValueError):
        published_cast.search("Harbor Lights", source="nowhere")


def test_cli_searches_the_chosen_sources(tmp_path, monkeypatch, capsys):
    from doblarr import cli

    def down(*a, **k):
        raise base.Unreachable("api.jikan.moe did not answer")

    monkeypatch.setitem(catalogues.PROVIDERS, "ann", ANN(fetch=recorder({"~": ANN_SEARCH})))
    monkeypatch.setitem(catalogues.PROVIDERS, "jikan", Jikan(fetch=down))
    config = tmp_path / "config.yaml"
    config.write_text(f"paths:\n  work_dir: '{(tmp_path / 'work').as_posix()}'\n",
                      encoding="utf-8")
    code = cli.main(["-c", str(config), "cast", "search", SERIES, "--query", "Harbor Lights",
                     "--source", "ann"])
    out = capsys.readouterr().out
    assert code == 0 and "animenewsnetwork.com" in out and "anime.php?id=77" in out
    monkeypatch.setitem(catalogues.PROVIDERS, "anilist", ANN(fetch=recorder({"~": ANN_SEARCH})))
    monkeypatch.setitem(catalogues.PROVIDERS, "bangumi", Jikan(fetch=down))
    cli.main(["-c", str(config), "cast", "search", SERIES, "--query", "Harbor Lights",
              "--source", "all"])
    out = capsys.readouterr().out
    assert "MyAnimeList (Jikan): skipped (api.jikan.moe did not answer)" in out
