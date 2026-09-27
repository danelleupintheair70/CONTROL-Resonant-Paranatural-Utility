"""Reference policy and holdout enforcement on the production translation path."""

import json

import pytest

from doblarr.clients.translator import (
    PromptureTranslator,
    translation_direction,
    translation_options,
)
from doblarr.cues import SOURCE, Span
from doblarr.models import DubJob, Segment
from doblarr.stages import translate
from doblarr.studio.holdout import (
    Fingerprints,
    HoldoutGuard,
    HoldoutViolation,
    guard_translator,
    tokens,
)
from tests.studio_fixtures import SENTINEL, SPANISH, RecordingDriver, install_driver


def reply_for(prompt, n):
    body = prompt[prompt.index("{"):]
    payload, _ = json.JSONDecoder().raw_decode(body)
    if "segments" in payload:
        return json.dumps({"translations": [
            {"segment_id": s["segment_id"], "text": f"linea {s['segment_id']}"}
            for s in payload["segments"]]})
    return json.dumps({"summary": "", "terms": [], "corrections": []})


def test_default_options_keep_every_saved_script_key():
    base = {"provider": "claude", "adaptation": "natural"}
    assert translation_options({**base, "reference_policy": "original_only",
                                "reference_file": "", "holdout_files": ["x.json"]}) == base


def test_reference_policy_keys_the_script_on_reference_content(tmp_path):
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps({"groups": [{"start": 0, "end": 1, "text": "hi",
                                           "state": "matched"}]}), encoding="utf-8")
    first = translation_options({"reference_policy": "reference_suggestions",
                                 "reference_file": str(ref)})
    moved = tmp_path / "moved.json"
    moved.write_text(ref.read_text(encoding="utf-8"), encoding="utf-8")
    assert translation_options({"reference_policy": "reference_suggestions",
                                "reference_file": str(moved)}) == first
    ref.write_text(json.dumps({"groups": [{"start": 0, "end": 1, "text": "hello",
                                           "state": "matched"}]}), encoding="utf-8")
    assert translation_options({"reference_policy": "reference_suggestions",
                                "reference_file": str(ref)}) != first
    # A reference without a policy that uses it is not an input at all.
    assert "reference_file" not in translation_options({"reference_file": str(ref)})


def test_no_new_jokes_is_resolved_explicitly():
    localized = translation_direction({"adaptation": "localized"}, "es")
    assert "invent no new jokes" in localized
    assert "adaptation_reference" not in localized
    with_ref = translation_direction({"adaptation": "localized",
                                      "reference_policy": "reference_suggestions",
                                      "reference_file": "r.json"}, "es")
    assert "invent no new jokes" in with_ref          # still holds for invention
    assert "never borrowed" in with_ref               # contradicting jokes are refused
    assert "facts, relationships, plot" in with_ref


def job_with(lines):
    job = DubJob(input_file="ep.mkv", source_lang="ja", target_lang="es",
                 target_locale="es-MX")
    for n, (start, end, text) in enumerate(lines):
        seg = Segment(index=n, start=start, end=end, text_src=text, speaker="A")
        seg.source.spans = [Span(start, end, SOURCE)]
        job.segments.append(seg)
    return job


def test_references_reach_only_matched_lines(monkeypatch):
    driver = RecordingDriver(reply_for)
    install_driver(monkeypatch, driver)
    job = job_with([(1, 3, "おはよう"), (5, 7, "またね"), (9, 11, "静かに")])
    job.translation_options = {"reference_policy": "reference_suggestions",
                               "reference_file": "abc"}
    references = {"language": "en", "groups": [
        {"start": 0.5, "end": 3.5, "text": "Morning sunshine", "state": "matched",
         "confidence": 0.8},
        {"start": 4.5, "end": 7.5, "text": "See you, alligator", "state": "uncertain"},
    ]}
    translate.run(job, PromptureTranslator("local/test"), references=references)
    sent = "\n".join(driver.prompts)
    assert "Morning sunshine" in sent
    assert "See you, alligator" not in sent      # uncertain spans are never injected
    # Without a policy that allows a reference, nothing is attached.
    driver2 = RecordingDriver(reply_for)
    install_driver(monkeypatch, driver2)
    job2 = job_with([(1, 3, "おはよう")])
    translate.run(job2, PromptureTranslator("local/test"), references=references)
    assert "Morning sunshine" not in "\n".join(driver2.prompts)


@pytest.mark.parametrize("path", ["translate", "shorten", "prepass"])
def test_guard_blocks_holdout_on_every_translator_path(monkeypatch, path):
    driver = RecordingDriver(reply_for)
    install_driver(monkeypatch, driver)
    translator = PromptureTranslator("local/test")
    guard = HoldoutGuard({"held-out adaptation": Fingerprints.of(
        [s["text"] for s in SPANISH], [SENTINEL])})
    guard_translator(translator, guard, "translation")
    leaked = SPANISH[2]["text"]
    with pytest.raises(HoldoutViolation) as caught:
        if path == "translate":
            translator.translate_batch([{"text": "こんにちは"}], "ja", "es",
                                       context=[{"text": leaked}])
        elif path == "shorten":
            translator.shorten(leaked, "es", 20)
        else:
            translator.analyze_script([{"id": "c1", "text": leaked}], "ja", "es")
    assert driver.prompts == []
    assert leaked not in str(caught.value)
    assert guard.blocked == 1


def test_guard_passes_clean_requests_and_counts_them(monkeypatch):
    driver = RecordingDriver(reply_for)
    install_driver(monkeypatch, driver)
    translator = PromptureTranslator("local/test")
    guard = HoldoutGuard({"held-out adaptation": Fingerprints.of([SENTINEL])})
    guard_translator(translator, guard)
    assert translator.translate_batch([{"text": "こんにちは"}], "ja", "es") == ["linea 1"]
    assert guard.checked == 1 and guard.blocked == 0


def test_fingerprints_are_accent_case_and_script_aware():
    prints = Fingerprints.of(["Él dijo: ¡NO vendrá mañana, lo juro!", "sí",
                              "今日は雨が降っています"])
    guard = HoldoutGuard({"x": prints})
    assert guard.hits("el dijo no vendra manana lo juro") == ["x"]
    assert guard.hits({"nested": ["今日は雨が降っています"]}) == ["x"]
    assert guard.hits("sí, claro") == []            # too short to fingerprint
    assert prints.too_short == 1
    assert tokens("ÁÉÍ óú") == ["aei", "ou"]
    # The pipeline's own output may be read back even if it matches.
    guard.allow_generated("El dijo no vendrá mañana, lo juro")
    assert guard.hits("contexto: El dijo no vendrá mañana, lo juro") == []


def test_voicebox_size_and_sampling_are_pinned_only_when_asked():
    from types import SimpleNamespace

    from doblarr.clients.translator import VoiceboxTranslator, build_translator

    calls = []

    def generate(prompt, system=None, **options):
        calls.append(options)
        return json.dumps({"translations": [{"segment_id": 1, "text": "hola"}]})

    client = SimpleNamespace(llm_generate=generate)
    assert VoiceboxTranslator(client).translate("hi", "en", "es") == "hola"
    assert calls[-1] == {}                      # existing configurations send nothing new
    pinned = build_translator("voicebox", "4B", voicebox_client=client,
                              llm_options={"max_tokens": 4096, "temperature": 0.3})
    pinned.translate("hi", "en", "es")
    assert calls[-1] == {"model_size": "4B", "max_tokens": 4096, "temperature": 0.3}
    assert pinned.model == "voicebox/4B"
    with pytest.raises(Exception, match="sizes"):
        VoiceboxTranslator(client, model_size="70B")
