"""dub_reference — a published dub's words, lined up with the script."""

from doblarr import dub_reference as ref


def w(start, end, word):
    return {"start": start, "end": end, "word": word}


WORDS = [w(0.0, 0.3, "Hola,"), w(0.35, 0.7, "Mina."), w(2.0, 2.4, "¿Vienes"),
         w(2.45, 2.9, "conmigo?"), w(5.0, 5.5, "Kaito")]


def test_words_go_to_the_line_spoken_over_them():
    lines = [{"index": 0, "start": 0.0, "end": 1.0}, {"index": 1, "start": 2.0, "end": 3.0},
             {"index": 2, "start": 8.0, "end": 9.0}]
    out = ref.assign(WORDS, lines)
    assert [x["text"] for x in out] == ["Hola, Mina.", "¿Vienes conmigo?", ""]
    assert out[0]["seconds"] == 0.7 and out[2]["seconds"] is None


def test_the_track_offset_moves_the_lines():
    # The dub runs 1 s later than the source: a line at 1-2 s is heard at 2-3 s.
    out = ref.assign(WORDS, [{"index": 0, "start": 1.0, "end": 2.0}], offset=-1.0)
    assert out[0]["text"] == "¿Vienes conmigo?"


def test_phrases_split_at_sentence_ends_and_pauses():
    assert [p["text"] for p in ref.phrases(WORDS)] == ["Hola, Mina.", "¿Vienes conmigo?",
                                                      "Kaito"]


def test_reference_is_on_the_source_timeline_and_matched():
    payload = ref.reference({"language": "es", "stream": 5, "offset": -1.0, "rate": 1.0,
                             "words": WORDS})
    first = payload["groups"][0]
    assert first["state"] == "matched" and first["text"] == "Hola, Mina."
    assert first["start"] < -1.0 + 0.0 + 0.01 and payload["language"] == "es"


def test_frequent_names_skip_sentence_starts():
    lines = [{"text": "Oye Kaito, ven."}, {"text": "Dile a Kaito que sí."}, {"text": "Bien."}]
    assert ref.frequent_names(lines) == [("Kaito", 2)]
