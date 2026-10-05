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


def test_the_latin_american_verified_track_is_preferred():
    evidence = [{"stream": 6, "lang": "es", "title": "Castellano", "state": "verified"},
                {"stream": 5, "lang": "es", "title": "Latino", "state": "verified"},
                {"stream": 7, "lang": "es", "title": "Latino 2", "state": "rejected"}]
    assert ref.published_track(evidence, "es")["stream"] == 5
    assert ref.published_track(evidence, "fr") is None


def _pipeline_job(tmp_path):
    from doblarr.models import DubJob, Segment

    job = DubJob(tmp_path / "Harbor Lights - 01.mkv", "ja", "es", target_locale="es-419")
    job.segments = [Segment(0, 0.0, 1.0, "Hi, Mina.", text_translated="Hola, Mina.")]
    job.translation_options = {"target_locale": "es-419"}
    return job


class _Translator:
    direction: dict = {}


def test_the_pipeline_follows_the_episodes_own_dub(tmp_path, monkeypatch):
    import json

    from doblarr import pipeline
    from doblarr.stages.common import work_stem

    job = _pipeline_job(tmp_path)
    stem = work_stem(job)
    (tmp_path / f"{stem}.speakers.json").write_text(json.dumps({"track_evidence": [
        {"stream": 5, "lang": "es", "title": "Latino", "state": "verified",
         "offset": 0.0, "rate": 1.0}]}), encoding="utf-8")
    payload = ref.reference({"language": "es", "stream": 5, "words": WORDS})
    target = tmp_path / "ref.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(ref, "ensure", lambda *a, **k: (
        {"stream": 5, "lines": [{"index": 0, "text": "Hola, Mina."}]}, target))
    translator = _Translator()
    config = {"translate": {"published_dub": "follow"}}
    got = pipeline._published_dub(job, config, tmp_path, translator, dry_run=False)
    assert got["groups"][0]["text"] == "Hola, Mina."
    assert job.translation_options["reference_policy"] == "follow_edition"
    assert job.segments[0].text_translated is None          # retranslated along it
    assert translator.direction["reference_policy"] == "follow_edition"
    assert job.metrics["published_dub"]["lines_heard"] == 1

    for setting in ({"published_dub": "off"}, {"reference_file": "studio.json"}):
        fresh = _pipeline_job(tmp_path)
        assert pipeline._published_dub(fresh, {"translate": setting}, tmp_path,
                                       _Translator(), dry_run=False) is None
        assert fresh.segments[0].text_translated == "Hola, Mina."
