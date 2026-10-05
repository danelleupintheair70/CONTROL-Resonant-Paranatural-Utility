"""Reference scripts: parsed, kept apart, aligned only where the words match."""

import json

import pytest

from doblarr import identity, published_cast
from doblarr.catalogues import base
from doblarr.catalogues.base import Unreachable
from doblarr.config import Config
from doblarr.knowledge import narrative
from doblarr.research import fandom, jpsubs, opensubs, probe, screenplays, scripts
from doblarr.store import Database
from doblarr.studio import records

from .test_catalogues import recorder
from .test_narrative import LINES, FakeModel, _claims, _episode

SERIES = "show:tvdb:4242"

TABLE = """{| class="wikitable"
|-
|
|''The harbor at dusk. Mira watches the boats.''
|-
!Mira
|[''Calling out.''] Kaito, the boats are leaving!
|-
!Kaito
|I know. [[Ren (character)|Ren]] said to wait.
|}
== Act Two ==
'''Mira''': We cannot wait for '''Ren'''.
Ren: Then go.<ref>aired cut</ref>
{{Navbox|harbor}}
[[Category:Transcripts]]"""

SCREENPLAY = """INT. LIGHTHOUSE - NIGHT

Mira climbs the stairs.

                    MIRA
          The lamp is out again.

                    KAITO (O.S.)
          (shouting)
          Then light it!

CUT TO:

EXT. HARBOR - DAWN
""" + "\n".join(f"\n                    MIRA\n          Line number {n} about the tide.\n"
                for n in range(60))


@pytest.fixture(autouse=True)
def _fresh_cache():
    base.configure(cache_dir=None)
    base.clear_memory()
    yield
    base.clear_memory()


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "scripts.db")
    identity.ensure_series(database, SERIES, {"provider": "tvdb"}, "Harbor Lights")
    yield database
    database.close()


def test_wiki_transcripts_keep_speakers_and_drop_markup():
    lines = scripts.wikitext_lines(TABLE)
    spoken = [(line["speaker"], line["text"]) for line in lines if line["kind"] == "dialogue"]
    assert spoken == [("Mira", "Kaito, the boats are leaving!"),
                      ("Kaito", "I know. Ren said to wait."),
                      ("Mira", "We cannot wait for Ren."), ("Ren", "Then go.")]
    assert lines[0] == {"kind": "action", "speaker": None,
                        "text": "The harbor at dusk. Mira watches the boats."}
    assert {"kind": "scene", "speaker": None, "text": "Act Two"} in lines
    assert not any("Navbox" in line["text"] or "Category" in line["text"] for line in lines)


def test_screenplays_read_cues_and_skip_directions():
    lines = scripts.screenplay_lines(SCREENPLAY)
    spoken = [(line["speaker"], line["text"]) for line in lines if line["kind"] == "dialogue"]
    assert spoken[:2] == [("Mira", "The lamp is out again."), ("Kaito", "Then light it!")]
    assert lines[0]["kind"] == "scene" and "LIGHTHOUSE" in lines[0]["text"]


@pytest.mark.parametrize("title,expected", [
    ("Episode 4: The Night Tide", (None, 4)), ("Harbor Lights S02E07", (2, 7)),
    ("[Fansub] Harbor Lights - 03 [720p]", (None, 3)), ("Transcript:The Night Tide", (None, None)),
    ("12 The Lamp", (None, 12)),
])
def test_episode_numbers_from_titles(title, expected):
    assert scripts.episode_of(title) == expected


def test_alignment_matches_in_order_and_leaves_misses_out():
    lines = scripts.wikitext_lines(TABLE)
    cues = [{"ordinal": 0, "text": "Kaito! The boats are leaving!"},
            {"ordinal": 1, "text": "Something nobody wrote down."},
            {"ordinal": 2, "text": "I know, Ren said to wait."},
            {"ordinal": 3, "text": "Then go."}]
    aligned = scripts.align(lines, cues)
    assert set(aligned) == {0, 2, 3}
    assert aligned[0]["speaker"] == "Mira" and aligned[2]["speaker"] == "Kaito"
    assert aligned[3]["speaker"] == "Ren"


def _fandom_answers(namespace_has_transcripts=True):
    spaces = {"0": {"*": ""}, "116": {"*": "Transcript"}} if namespace_has_transcripts else \
        {"0": {"*": ""}}
    return {
        '"siprop": "namespaces"': {"query": {"namespaces": spaces}},
        '"apnamespace": 116': {"query": {"allpages": [{"title": "Transcript:The Night Tide"},
                                                      {"title": "Transcript:Stub"}]}},
        '"srsearch"': {"query": {"search": [{"title": "Episode 5/Transcript"},
                                            {"title": "Unrelated page"}]}},
        '"page": "Transcript:The Night Tide"': {"parse": {"wikitext": {"*": TABLE}}},
        '"page": "Transcript:Stub"': {"parse": {"wikitext": {"*": "Mira: Hi."}}},
        '"page": "Episode 5/Transcript"': {"parse": {"wikitext": {"*": TABLE}}},
    }


def test_fandom_probe_keeps_transcripts_and_places_episodes(db):
    records.put(db, "published_cast", f"{SERIES}#ann", {
        "series_id": SERIES, "source": "ann", "title": "Harbor Lights", "characters": [],
        "episode_titles": {"4": "The Night Tide"}}, scope=SERIES)
    fetch = recorder(_fandom_answers())
    found = fandom.Fandom(fetch)
    assert found.transcript_pages("harborlights") == ["Transcript:The Night Tide",
                                                      "Transcript:Stub",
                                                      "Episode 5/Transcript"]
    result = fandom.probe(db, SERIES, wiki="harborlights", fetch=fetch)
    assert len(result["saved"]) == 2    # the stub has too little dialogue
    kept = {r["title"]: r for r in scripts.listing(db, SERIES)}
    assert kept["Transcript:The Night Tide"]["episode"] == 4
    assert kept["Episode 5/Transcript"]["episode"] == 5
    assert kept["Transcript:The Night Tide"]["source"] == "fandom:harborlights"
    assert records.get(db, "title_script", result["saved"][0])["speakers"] == ["Kaito", "Mira",
                                                                               "Ren"]


def test_fandom_guesses_quietly(db):
    def missing(url, **kwargs):
        raise LookupError(f"{url} was not found")

    result = fandom.probe(db, SERIES, fetch=missing)
    assert result["saved"] == [] and set(result["tried"]) == {"harborlights", "harbor-lights",
                                                               "harbor"}
    assert fandom.wiki_guesses(["Harbor Lights: Tide (2003)"])[0] == "harborlights"


def test_screenplays_for_a_film(db):
    movie = "movie:tmdb:77"
    identity.ensure_series(db, movie, {"provider": "tmdb"}, "Harbor Lights")
    asked = []

    def fetch(url):
        asked.append(url)
        if "imsdb" in url:
            return SCREENPLAY
        if "scriptslug" in url:
            raise Unreachable("no")
        return "short page"

    result = screenplays.probe(db, movie, fetch=fetch)
    assert asked[0] == "https://imsdb.com/scripts/Harbor-Lights.html"
    assert len(result["saved"]) == 1
    kept = records.get(db, "title_script", result["saved"][0])
    assert kept["kind"] == "screenplay" and kept["source"] == "imsdb"


def test_episode_transcripts_for_a_show(db, tmp_path):
    ident, _ = _episode(db, tmp_path, "e04", 1, 4, LINES, tvdb=4242)
    long_text = "Mira: The boats are leaving. " * 200

    def fetch(url):
        assert "tv-show=harbor-lights&episode=s01e04" in url
        return long_text

    result = screenplays.probe(db, ident["series_id"], fetch=fetch)
    kept = records.get(db, "title_script", result["saved"][0])
    assert (kept["season"], kept["episode"], kept["kind"]) == (1, 4, "transcript")


def test_a_local_subtitle_mirror(db, tmp_path):
    folder = tmp_path / "mirror" / "subtitles" / "Harbor Lights"
    folder.mkdir(parents=True)
    (folder / "Harbor Lights - 02.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,500\n港が見える。\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n行こう！\n", encoding="utf-8")
    (folder / "notes.txt").write_text("not a subtitle", encoding="utf-8")
    result = jpsubs.import_title(db, SERIES, tmp_path / "mirror")
    assert result["folder"] == "Harbor Lights" and len(result["saved"]) == 1
    kept = records.get(db, "title_script", result["saved"][0])
    assert kept["episode"] == 2 and kept["language"] == "ja"
    assert kept["lines"][0] == {"kind": "dialogue", "speaker": None, "text": "港が見える。",
                                "start_ms": 1000, "end_ms": 2500}
    assert jpsubs.import_title(db, SERIES, tmp_path / "mirror", titles=["Other"])["saved"] == []
    with pytest.raises(ValueError):
        jpsubs.find_folder(tmp_path / "nowhere", ["Harbor Lights"])


SRT = "1\n00:00:01,000 --> 00:00:02,000\nThe boats are leaving.\n"


def test_opensubtitles_needs_a_key_and_keeps_one_track_per_language(db):
    with pytest.raises(Unreachable):
        opensubs.OpenSubtitles("")
    fetch = recorder({
        "/subtitles": {"data": [
            {"attributes": {"language": "en", "download_count": 9, "url": "https://os/1",
                            "files": [{"file_id": 1, "file_name": "a.srt"}],
                            "feature_details": {"season_number": 1, "episode_number": 4}}},
            {"attributes": {"language": "en", "download_count": 3,
                            "files": [{"file_id": 2, "file_name": "b.srt"}]}},
            {"attributes": {"language": "es", "download_count": 5, "url": "https://os/3",
                            "files": [{"file_id": 3, "file_name": "c.srt"}]}}]},
        "/download": {"link": "https://dl.example/file.srt"},
        "dl.example": SRT,
    })
    result = opensubs.fetch_title(db, SERIES, api_key="k", languages="en,es", season=1,
                                  episode=4, fetch=fetch)
    assert result["found"] == 3 and len(result["saved"]) == 2
    langs = {records.get(db, "title_script", s)["language"] for s in result["saved"]}
    assert langs == {"en", "es"}
    sent = fetch.calls[0][1]
    assert sent["headers"]["Api-Key"] == "k" and sent["params"]["episode_number"] == 4


def test_probe_all_reports_what_it_skipped(db, tmp_path):
    config = Config.load(tmp_path / "none.yaml").with_overrides(
        {"paths.work_dir": str(tmp_path / "work")})
    found = probe.probe_all(db, config, SERIES, ["kitsunekko", "opensubtitles", "nope"])
    assert "kitsunekko_mirror" in found["skipped"]["kitsunekko"]
    assert "opensubtitles_api_key" in found["skipped"]["opensubtitles"]
    assert found["skipped"]["nope"] == "unknown source" and found["saved"] == 0


def test_the_dubbing_database_page_becomes_cast_leads(db):
    from .test_research import FakeAsk

    fetch = recorder({'"page": "Harbor Lights"': {"parse": {"wikitext": {"*": (
        "== Latin American Spanish ==\n* Mira Tavel: Lucia Prado\n")}}}})
    lead = {"character": "Mira Tavel", "language": "Spanish", "voice_actor": "Lucia Prado",
            "cited": [1]}
    run = fandom.dubbing_database(db, SERIES, FakeAsk(leads=[lead]), fetch=fetch)
    assert run["question"] == "Dubbing Database: Harbor Lights"
    assert run["leads"][0]["urls"] == ["https://dubbing.fandom.com/wiki/Harbor_Lights"]


def test_extraction_reads_an_aligned_reference_only_when_given(db, tmp_path):
    ident, script = _episode(db, tmp_path, "e01", 1, 1, LINES)
    lines = [{"kind": "dialogue", "speaker": "Mira", "text": "Big brother, wait!"},
             {"kind": "dialogue", "speaker": "Kaito", "text": "Mina, stay at the harbor."}]
    scripts.save(db, ident["series_id"], source="fandom:harborlights", url="u", lines=lines,
                 kind="transcript", season=1, episode=1)
    cues = narrative.script_cues(json.loads(script.read_text(encoding="utf-8")), {})
    reference = scripts.reference_for(db, ident, cues)
    assert {k: v["speaker"] for k, v in reference.items()} == {0: "Mira", 1: "Kaito"}

    plain, guided = FakeModel(_claims), FakeModel(_claims)
    narrative.extract(db, ident, script, plain)
    narrative.extract(db, ident, script, guided, reference=reference)
    assert "reference_transcript" not in plain.payloads[0]
    assert guided.payloads[0]["reference_transcript"][0] == {
        "id": "L0", "speaker": "Mira", "text": "Big brother, wait!"}


def test_a_person_places_a_found_script(client_factory):
    client = client_factory({"research.enabled": True})
    db = client.app.state.jobs.db
    identity.ensure_series(db, SERIES, {"provider": "tvdb"}, "Harbor Lights")
    saved = scripts.save(db, SERIES, source="fandom:x", url="u",
                         lines=scripts.wikitext_lines(TABLE), kind="transcript",
                         title="Transcript:The Night Tide")
    listed = client.get("/api/research/scripts", params={"series_id": SERIES}).json()
    assert listed["scripts"][0]["episode"] is None
    assert listed["scripts"][0]["lines"] == len(scripts.wikitext_lines(TABLE))
    placed = client.post(f"/api/research/scripts/{saved['id']}/place",
                         json={"season": 1, "episode": 4}).json()
    assert (placed["season"], placed["episode"]) == (1, 4)
    assert client.get(f"/api/research/scripts/{saved['id']}").json()["placed_by"] == "person"
    queued = client.post("/api/research/scripts", json={"series_id": SERIES,
                                                        "sources": ["fandom"]}).json()
    assert client.app.state.jobs.get(queued["job_id"]).task["action"] == "scripts"
    assert client.post("/api/research/scripts", json={"series_id": SERIES,
                                                      "sources": ["piracy"]}).status_code == 422
    assert published_cast.episode_titles(db, SERIES) == {}
