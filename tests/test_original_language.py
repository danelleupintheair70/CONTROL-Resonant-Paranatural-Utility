"""Which audio track is the original, from the file alone."""

from doblarr import original_language as ol


def audio(index, lang, title="", default=False, original=False):
    return {"index": index, "kind": "audio", "lang": lang, "title": title, "default": default,
            "original": original, "forced": False, "described": False, "sdh": False}


def subs(index, lang, title="", forced=False):
    return {"index": index, "kind": "subtitle", "lang": lang, "title": title, "default": False,
            "original": False, "forced": forced, "described": False, "sdh": False}


def test_a_four_track_release_shows_its_original_without_any_service():
    streams = [audio(1, "en", "[Group] 2.0 ENG"), audio(2, "ja", "2.0 JPN", default=True),
               subs(3, "en", "[Fansub] English"), subs(4, "en", "Signs and Songs"),
               audio(5, "es", "Latino"), audio(6, "es", "Castellano")]
    found = ol.detect(streams)
    assert (found["lang"], found["stream"], found["confidence"]) == ("ja", 2, "strong")
    assert any("Latino" in e for e in found["evidence"])


def test_the_library_language_decides_when_the_file_carries_it():
    streams = [audio(1, "en", default=True), audio(2, "fr", "VF")]
    assert ol.detect(streams, metadata="fr")["lang"] == "fr"
    assert ol.detect(streams)["lang"] == "en"              # the dub title and default agree


def test_no_clear_clue_is_unknown_with_the_candidates_never_a_guess():
    found = ol.detect([audio(1, "en"), audio(2, "de")])
    assert found["lang"] == "" and found["stream"] is None
    assert set(found["candidates"]) == {"en", "de"}


def test_commentary_and_single_language_files():
    streams = [audio(1, "en", "Director's Commentary", default=True), audio(2, "ko")]
    assert ol.detect(streams)["lang"] == "ko"               # a commentary is not a candidate
    assert ol.detect([audio(1, "it"), audio(2, "it", "Stereo")])["confidence"] == "only"


def test_a_shows_answer_is_kept_and_a_persons_choice_wins(tmp_path):
    from doblarr.store import Database

    db = Database(tmp_path / "d.db")
    key = ol.cache_key("show", 81234)
    ol.remember(db, key, {"lang": "ja", "confidence": "strong", "evidence": []}, source="file")
    assert ol.for_title(db, key, [])["lang"] == "ja"       # no file probed again
    ol.remember(db, key, {"lang": "ko", "confidence": "manual", "evidence": []}, source="manual")
    assert ol.for_title(db, key, [], metadata="ja")["lang"] == "ko"
    db.close()
