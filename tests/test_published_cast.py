"""The published cast of a series: linked by a person, narrowed per episode."""

from types import SimpleNamespace

import pytest

from doblarr import identity, published_cast
from doblarr.store import Database
from doblarr.studio import records

SERIES = "show:tvdb:4242"
URL = "https://anilist.co/anime/123"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "cast.db")
    identity.ensure_series(database, SERIES, {"provider": "tvdb"}, "Harbor Lights")
    yield database
    database.close()


def _person(cid, name, role, description="", gender=None, alternative=()):
    return {"id": cid, "name": name, "native": "", "alternative": list(alternative), "role": role,
            "gender": gender, "age": None, "description": description,
            "voice_actors": [{"name": f"Actor {cid}", "native": "", "language": "Japanese"}],
            "url": f"https://anilist.co/character/{cid}"}


CAST = [
    _person(1, "Mira Tavel", "MAIN", "Keeps the lighthouse.", "Female",
            alternative=["Lamp Keeper"]),
    _person(2, "Oren Pask", "SUPPORTING", "A ferryman who appears in episode 4, The Night Tide."),
    _person(3, "Ilse Varro", "SUPPORTING", "She returns in episodes 7-9 and episode 12."),
    _person(4, "Dock Hand", "BACKGROUND", "Works the pier."),
]


def fake_read(cast=CAST, *, reader="anilist"):
    calls = []

    def read(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(reader=reader, title="Harbor Lights", meta={
            "id": 123, "page_url": url, "titles": {"english": "Harbor Lights"}, "format": "TV",
            "year": 2001, "episodes": 12, "characters": cast, "more_characters": False})
    read.calls = calls
    return read


def test_episode_mentions_reads_the_usual_phrasings():
    assert published_cast.episode_mentions("He appears in episode #4, The Pillow Lane.") == [4]
    assert published_cast.episode_mentions("Seen in episodes 3 and 5.") == [3, 5]
    assert published_cast.episode_mentions("Episodes 7-9 and Ep. 12") == [7, 8, 9, 12]
    assert published_cast.episode_mentions("A quiet ferryman.") == []


def test_search_stores_nothing(db):
    hits = published_cast.search("Harbor Lights", search_fn=lambda q, **kw: [
        {"id": 123, "title": "Harbor Lights", "year": 2001, "format": "TV", "url": URL}])
    assert hits[0]["id"] == 123 and hits[0]["source"] == "anilist"
    assert published_cast.links(db, SERIES) == []
    with pytest.raises(ValueError):
        published_cast.search("  ")


def test_link_stores_the_cast_for_a_known_series_only(db):
    read = fake_read()
    linked = published_cast.link(db, SERIES, URL, read_fn=read)
    assert linked["linked_by"] == "person" and linked["source_id"] == 123
    assert [c["name"] for c in linked["characters"]] == ["Mira Tavel", "Oren Pask", "Ilse Varro",
                                                         "Dock Hand"]
    assert linked["characters"][2]["episodes"] == [7, 8, 9, 12]
    assert read.calls[0][1]["use_cache"] is False
    with pytest.raises(KeyError):
        published_cast.link(db, "show:tvdb:999", URL, read_fn=read)
    with pytest.raises(ValueError):
        published_cast.link(db, SERIES, "https://example.com/x",
                            read_fn=fake_read(reader="web_fetch"))


def test_a_season_link_wins_over_the_whole_series(db):
    published_cast.link(db, SERIES, URL, read_fn=fake_read())
    published_cast.link(db, SERIES, URL + "0", season=2, read_fn=fake_read(CAST[:1]))
    assert len(published_cast.get(db, SERIES, season=2)["characters"]) == 1
    assert len(published_cast.get(db, SERIES, season=1)["characters"]) == 4
    assert len(published_cast.links(db, SERIES)) == 2


def test_candidates_narrow_guests_to_their_episodes(db):
    cast = published_cast.link(db, SERIES, URL, read_fn=fake_read())
    names = lambda ep: [c["name"] for c in published_cast.candidates(cast, episode=ep)]  # noqa: E731
    assert names(4) == ["Mira Tavel", "Oren Pask", "Dock Hand"]
    assert names(8) == ["Mira Tavel", "Ilse Varro", "Dock Hand"]
    everyone = published_cast.candidates(cast)
    assert {c["name"]: c["why"] for c in everyone}["Dock Hand"] == "recurring, episodes not stated"


def test_a_show_search_puts_series_before_films():
    hits = [{"id": 1, "title": "Harbor Lights: The Movie", "format": "MOVIE"},
            {"id": 2, "title": "Harbor Lights", "format": "TV"}]
    found = published_cast.search("Harbor Lights", kind="show", search_fn=lambda q, **kw: hits)
    assert [h["id"] for h in found] == [2, 1]
    found = published_cast.search("Harbor Lights", kind="movie", search_fn=lambda q, **kw: hits)
    assert [h["id"] for h in found] == [1, 2]


def test_name_key_folds_romanization():
    assert published_cast.name_key("Hyūga") == published_cast.name_key("Hyuuga") == "hyuga"
    assert published_cast.name_key("Kouichi") == published_cast.name_key("Kōichi")


def test_import_creates_main_cast_and_never_renames_existing(db):
    published_cast.link(db, SERIES, URL, read_fn=fake_read())
    mine = identity.ensure_character(db, SERIES, "Lamp Keeper")
    result = published_cast.import_characters(db, SERIES, roles=("MAIN", "SUPPORTING"))
    assert result["matched"] == ["Lamp Keeper = Mira Tavel"]
    assert result["created"] == ["Oren Pask", "Ilse Varro"]
    kept = records.get(db, "character", mine["id"])
    assert kept["name"] == "Lamp Keeper" and kept["published"]["source_id"] == 1
    assert "Mira Tavel" in kept["aliases"]
    oren = identity.find_character(db, SERIES, "Oren Pask")
    assert oren["origin"] == "published_cast" and oren["published"]["voice_actors"]
    again = published_cast.import_characters(db, SERIES, names=["Oren Pask", "Dock Hand"])
    assert again == {"created": ["Dock Hand"], "matched": ["Oren Pask = Oren Pask"],
                     "ambiguous": []}


def test_a_first_name_matches_only_when_it_is_unique(db):
    cast = [_person(1, "Mira Tavel", "MAIN"), _person(2, "Oren Pask", "MAIN"),
            _person(3, "Ilse Pask", "MAIN"), _person(4, "Juro Hyuuga", "MAIN")]
    published_cast.link(db, SERIES, URL, read_fn=fake_read(cast))
    mira = identity.ensure_character(db, SERIES, "Mira")
    identity.ensure_character(db, SERIES, "Pask")
    identity.ensure_character(db, SERIES, "Hyūga")
    result = published_cast.import_characters(db, SERIES)
    assert result["matched"] == ["Mira = Mira Tavel", "Hyūga = Juro Hyuuga"]
    assert result["created"] == []
    assert result["ambiguous"] == [{"name": "Oren Pask", "also": ["Ilse Pask"]},
                                   {"name": "Ilse Pask", "also": ["Oren Pask"]}]
    assert identity.find_character(db, SERIES, "Mira Tavel")["id"] == mira["id"]


def test_characters_created_by_an_import_are_not_matched_by_it(db):
    cast = [_person(1, "Old Keeper", "MAIN", alternative=["Warden"]),
            _person(2, "Tide Warden", "MAIN"),
            _person(3, "Mira Tavel", "MAIN")]
    published_cast.link(db, SERIES, URL, read_fn=fake_read(cast))
    identity.ensure_character(db, SERIES, "Mira")
    result = published_cast.import_characters(db, SERIES)
    # "Warden" became an alias of a character this import created; it must not
    # swallow "Tide Warden".
    assert result["created"] == ["Old Keeper", "Tide Warden"]
    assert result["matched"] == ["Mira = Mira Tavel"]
