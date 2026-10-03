"""What an official dub track says, laid on the source lines."""

import json

from doblarr import dub_text

TRACKS = [{"stream": 1, "lang": "en", "title": "English"},
          {"stream": 5, "lang": "es", "title": "Latino"},
          {"stream": 6, "lang": "es", "title": "Castellano"}]


def test_the_dub_in_the_target_language_and_region_is_picked():
    assert dub_text.pick_track(TRACKS, "es-419", "ja")["stream"] == 5
    assert dub_text.pick_track(TRACKS, "es-ES", "ja")["stream"] == 6
    # Two Spanish tracks and no region asked: neither is safe to pick.
    assert dub_text.pick_track(TRACKS, "es", "ja") is None
    # The original language is not a dub.
    assert dub_text.pick_track(TRACKS, "en", "en") is None
    # A lone track with no region in its title is the language's dub.
    assert dub_text.pick_track([{"stream": 3, "lang": "es", "title": ""}], "es-MX", "ja")[
        "stream"] == 3


def test_words_go_to_the_nearest_line_on_the_source_clock():
    words = [{"start": 0.2, "end": 0.6, "text": "hola"},
             {"start": 3.1, "end": 3.4, "text": "adiós"},
             {"start": 9.0, "end": 9.3, "text": "lejos"}]
    assert dub_text.lines(words, [(0.0, 1.0), (3.0, 4.0)]) == ["hola", "adiós"]
    # The track runs two seconds early: shifted onto the source clock.
    assert dub_text.lines(words, [(2.0, 3.0), (5.0, 6.0)], offset=2.0) == ["hola", "adiós"]


def test_the_transcript_on_disk_is_read_for_the_matching_region(tmp_path):
    (tmp_path / "e.dubtext.6.json").write_text(json.dumps({
        "stream": 6, "lang": "es", "title": "Castellano",
        "words": [{"start": 0.1, "end": 0.4, "text": "vale"}]}), encoding="utf-8")
    assert dub_text.for_script(tmp_path, "e", [(0.0, 1.0)], "es-419") is None
    found = dub_text.for_script(tmp_path, "e", [(0.0, 1.0)], "es-ES")
    assert found == {"title": "Castellano", "stream": 6, "lines": ["vale"]}
