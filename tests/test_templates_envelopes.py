"""Templates as data, fitted envelopes, renders, retrieval filters and the judge."""

import math

import numpy as np
import pytest

from doblarr import envelopes, features, judge, retrieval, templates
from doblarr.store import Database

RATE = 24000


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "t.db")
    yield database
    database.close()


def tone(path, parts, rate=RATE, channels=1):
    """(seconds, amplitude) parts of a 220 Hz tone, written as 16-bit PCM."""
    chunks = []
    for seconds, amplitude in parts:
        t = np.arange(int(seconds * rate)) / rate
        chunks.append(amplitude * np.sin(2 * np.pi * 220 * t))
    samples = np.concatenate(chunks)[:, None].repeat(channels, axis=1)
    envelopes.write_wav(path, samples, rate)
    return path


def test_the_builtin_catalogue_validates_and_installs_once(db):
    assert templates.ensure_builtins(db) > 0
    assert templates.ensure_builtins(db) == 0
    rows = templates.listing(db)
    ids = {r["id"] for r in rows}
    assert {"voice/preserve", "background/preserve", "preset/natural-dialogue"} <= ids
    assert all(r["version"] == 1 for r in rows)


@pytest.mark.parametrize("bad, message", [
    ({"filter": "volume=6dB"}, "Extra inputs"),
    ({"anchors": [{"at": 0.0, "db": float("inf")}, {"at": 1.0, "db": 0}]}, "finite"),
    ({"anchors": [{"at": 0.7, "db": 1}, {"at": 0.2, "db": 0}]}, "increasing"),
    ({"anchors": [{"at": 0.0, "db": 1}]}, "at least two"),
    ({"anchors": [{"at": 0.0, "db": 20}, {"at": 1.0, "db": 0}]}, "less than or equal"),
    ({"family": "bed"}, "voice template cannot"),
    ({"params": {"strength": {"default": 1, "min": 0, "max": 3}}}, "0..1.5"),
])
def test_invalid_templates_are_refused(bad, message):
    good = {"id": "voice/my-swell", "kind": "voice", "family": "curve", "title": "Swell",
            "anchors": [{"at": 0.0, "db": -1.0}, {"at": 1.0, "db": 2.0}]}
    with pytest.raises(ValueError, match=message):
        templates.validate({**good, **bad})


def test_edits_are_versions_and_old_versions_stay_pinned(db):
    templates.ensure_builtins(db)
    mine = {"id": "voice/my-swell", "kind": "voice", "family": "curve", "title": "Swell",
            "anchors": [{"at": 0.0, "db": -1.0}, {"at": 1.0, "db": 2.0}],
            "params": {"strength": {"default": 1, "min": 0, "max": 1.5}}}
    first = templates.save(db, mine, base_version=0)
    second = templates.save(db, {**mine, "anchors": [{"at": 0.0, "db": -2.0},
                                                     {"at": 1.0, "db": 3.0}]},
                            base_version=first["version"])
    assert second["version"] == 2
    assert templates.get(db, "voice/my-swell", 1)["anchors"][0]["db"] == -1.0
    retired = templates.retire(db, "voice/my-swell", base_version=2)
    assert retired["retired"] and "voice/my-swell" not in {
        r["id"] for r in templates.listing(db)}
    assert templates.get(db, "voice/my-swell", 2)["anchors"][1]["db"] == 3.0
    copy = templates.duplicate(db, "voice/late-emphasis", "voice/late-emphasis-soft")
    assert copy["provenance"]["source"].startswith("duplicated from voice/late-emphasis")


def test_bundles_import_whole_or_not_at_all_and_twice_adds_nothing(db, tmp_path):
    templates.ensure_builtins(db)
    bundle = templates.export(db, ["voice/late-emphasis", "preset/natural-dialogue"])
    assert "path" not in str(bundle)
    other = Database(tmp_path / "o.db")
    templates.ensure_builtins(other)
    renamed = {**bundle, "templates": [{**bundle["templates"][0], "id": "voice/imported-late"}]}
    assert templates.import_bundle(other, renamed)["added"] == ["voice/imported-late"]
    assert templates.import_bundle(other, renamed)["unchanged"] == ["voice/imported-late"]
    broken = {**bundle, "templates": [{**bundle["templates"][0], "id": "voice/x-new"},
                                      {"id": "voice/bad", "kind": "voice"}]}
    with pytest.raises(ValueError):
        templates.import_bundle(other, broken)
    assert templates.get(other, "voice/x-new") is None
    other.close()


def test_half_linear_gain_is_about_minus_six_db_not_half_loudness():
    assert templates.db_from_linear(0.5) == pytest.approx(-6.0206, abs=1e-3)


def _take(path):
    return features.measure_file(path)


def test_a_curve_is_laid_over_the_takes_own_speech(tmp_path):
    # 0.5 s of silence, then 1.5 s of steady speech.
    take = _take(tone(tmp_path / "t.wav", [(0.5, 0.0), (1.5, 0.3)]))
    late = templates.validate({"id": "voice/late", "kind": "voice", "family": "curve",
                               "title": "Late", "interpolation": "linear",
                               "smoothing_ms": 0, "silence": "follow",
                               "anchors": [{"at": 0.0, "db": -2.0}, {"at": 1.0, "db": 2.0}]})
    fitted = envelopes.fit(late.model_dump(), {"strength": 1.0}, take, 2.0,
                           credit_existing=False)
    curve = fitted["curve"]
    assert fitted["outcome"] == "applied"
    assert curve[10] == 0.0                     # silence before speech: no change
    assert curve[int(0.55 / envelopes.HOP)] == pytest.approx(-2.0, abs=0.4)
    assert curve[int(1.95 / envelopes.HOP)] == pytest.approx(2.0, abs=0.4)
    preserve = envelopes.fit({"family": "preserve"}, {}, take, 2.0)
    assert set(preserve["curve"]) == {0.0} and preserve["outcome"] == "preserved"


def test_bounds_smoothing_and_existing_emphasis_are_respected(tmp_path):
    take = _take(tone(tmp_path / "t.wav", [(0.6, 0.1), (0.6, 0.2), (0.6, 0.4)]))
    late = next(t for t in templates.builtins() if t["id"] == "voice/late-emphasis")
    late = templates.validate(late).model_dump()
    strong = envelopes.fit(late, {"strength": 1.5}, take, 1.8, max_db=1.0,
                           credit_existing=False)
    assert max(abs(c) for c in strong["curve"]) <= 1.0
    assert strong["max_step_db"] < envelopes.MAX_STEP_DB
    credited = envelopes.fit(late, {"strength": 1.0}, take, 1.8)
    assert credited["preserved"] > 0.3          # the take already rises
    assert credited["applied"] < 1.0


def test_a_render_moves_the_level_where_the_curve_says_and_keeps_the_format(tmp_path):
    source = tone(tmp_path / "in.wav", [(2.0, 0.3)], channels=2)
    take = _take(source)
    rise = templates.validate({"id": "voice/rise", "kind": "voice", "family": "curve",
                               "title": "Rise", "interpolation": "linear", "smoothing_ms": 0,
                               "anchors": [{"at": 0.0, "db": -4.0}, {"at": 1.0, "db": 4.0}]})
    fitted = envelopes.fit(rise.model_dump(), {"strength": 1.0}, take, 2.0,
                           credit_existing=False)
    out = tmp_path / "out.wav"
    stats = envelopes.render(source, out, 0.0, fitted["curve"], peak_ceiling=0.99)
    samples, rate = envelopes.read_wav(out)
    assert rate == RATE and samples.shape == envelopes.read_wav(source)[0].shape

    def db(a, b):
        part = samples[int(a * rate):int(b * rate), 0]
        return 20 * math.log10(float(np.sqrt(np.mean(part ** 2))))

    assert db(1.8, 1.95) - db(0.05, 0.2) == pytest.approx(7.0, abs=1.2)
    assert stats["peak"] <= 0.99
    again = tmp_path / "again.wav"
    envelopes.render(source, again, 0.0, fitted["curve"], peak_ceiling=0.99)
    assert again.read_bytes() == out.read_bytes()     # same input, same bytes


def test_a_render_never_crosses_the_ceiling_and_keeps_the_shape(tmp_path):
    source = tone(tmp_path / "loud.wav", [(1.0, 0.8)])
    curve = [0.0] * 50 + [6.0] * 50
    stats = envelopes.render(source, tmp_path / "o.wav", 3.0, curve, peak_ceiling=0.89)
    assert stats["peak"] <= 0.8901 and stats["held_db"] > 0


def _ranked(source_curve, take_curve, tags=None, examples=None, query=None, profile=None,
            extra=None):
    catalogue = [{**templates.validate(t).model_dump(), "version": 1}
                 for t in templates.builtins() if t["kind"] == "voice"] + (extra or [])
    source = {"quality": "ok", "curve": source_curve, "duration": 2.0,
              "range_db": max(source_curve) - min(source_curve), "pauses": []}
    take = {"quality": "ok", "curve": take_curve, "duration": 2.0, "active_seconds": 1.8,
            "range_db": max(take_curve) - min(take_curve), "pauses": [], "peaks": []}
    return retrieval.rank({"band": "calm", **(tags or {})}, source, take, catalogue,
                          examples=examples, query=query, profile=profile)


RISING = [i / 31 * 8 - 4 for i in range(32)]
FLAT = [0.0] * 32


def test_contraindicated_templates_are_filtered_before_any_score():
    ranked = _ranked(RISING, FLAT, tags={"ending": "interrupted"})
    excluded = {e["template"]: e["reason"] for e in ranked["excluded"]}
    assert "contraindicated" in excluded["voice/late-emphasis"]
    assert all(c["template"]["id"] != "voice/late-emphasis" for c in ranked["candidates"])
    assert any(c["family"] == "preserve" for c in ranked["candidates"])


def test_a_rising_original_over_a_flat_take_ranks_a_rise_above_preserve():
    ranked = _ranked(RISING, FLAT)
    top = ranked["candidates"][0]
    assert top["template"]["id"] in ("voice/gradual-rise", "voice/late-emphasis")
    assert top["components"]["source_shape"] > 0.6
    assert top["params"]["strength"] > 0
    # When the take already moves like the original, preserve wins.
    same = _ranked(RISING, RISING)
    assert same["candidates"][0]["family"] == "preserve"


def test_curve_similarity_ignores_who_speaks():
    one = _ranked(RISING, FLAT, tags={"speaker_name": "Kaito"})
    two = _ranked(RISING, FLAT, tags={"speaker_name": "Mina"})
    assert [c["score"] for c in one["candidates"]] == [c["score"] for c in two["candidates"]]


def test_held_out_later_and_foreign_examples_never_vote():
    example = {"template": "voice/early-emphasis", "source_curve": RISING, "id": "ex1",
               "revision_id": "rev-a", "cue": "c9", "target_lang": "es", "order": [1, 2]}
    query = {"cue": "c1", "revision_id": "rev-b", "target_lang": "es", "order": [1, 5],
             "held_out": []}
    assert _ranked(RISING, FLAT, examples=[example], query=query)["examples_considered"] == 1
    for bad in ({"holdout": True}, {"order": [1, 9]}, {"target_lang": "fr"},
                {"revision_id": "rev-b", "cue": "c1"}):
        assert _ranked(RISING, FLAT, examples=[{**example, **bad}],
                       query=query)["examples_considered"] == 0
    held = {**query, "held_out": ["rev-a"]}
    assert _ranked(RISING, FLAT, examples=[example], query=held)["examples_considered"] == 0


def test_a_near_tie_keeps_the_take_as_generated():
    choice = retrieval.retrieval_choice({"candidates": [
        {"family": "curve", "score": 0.61, "margin": 0.01, "template": {"id": "voice/a"}},
        {"family": "curve", "score": 0.60, "margin": 0.1, "template": {"id": "voice/b"}},
        {"family": "preserve", "score": 0.5, "margin": None,
         "template": {"id": "voice/preserve"}}]})
    assert choice["template"]["id"] == "voice/preserve"


def test_a_user_added_curve_is_retrieved_fitted_and_rendered_like_a_builtin(db, tmp_path):
    templates.ensure_builtins(db)
    mine = templates.save(db, {"id": "voice/late-jump", "kind": "voice", "family": "curve",
                               "title": "Late jump", "interpolation": "linear",
                               "anchors": [{"at": 0.0, "db": -3.0}, {"at": 0.6, "db": -3.0},
                                           {"at": 1.0, "db": 4.0}],
                               "params": {"strength": {"default": 1, "min": 0, "max": 1.5}}},
                          base_version=0)
    shape = [-3.0 if i / 31 <= 0.6 else -3.0 + (i / 31 - 0.6) / 0.4 * 7 for i in range(32)]
    ranked = _ranked(shape, FLAT, extra=[mine])
    assert ranked["candidates"][0]["template"]["id"] == "voice/late-jump"
    assert ranked["candidates"][0]["template"]["version"] == 1
    source = tone(tmp_path / "s.wav", [(2.0, 0.3)])
    fitted = envelopes.fit(templates.get(db, "voice/late-jump", 1), {"strength": 1.0},
                           _take(source), 2.0, credit_existing=False)
    stats = envelopes.render(source, tmp_path / "o.wav", 0.0, fitted["curve"])
    assert fitted["outcome"] == "applied" and stats["peak"] <= 0.89


def _packet():
    ranked = _ranked(RISING, FLAT)
    return judge.build_packet(line={"cue": "c1", "text": "Wait!"}, source={"quality": "ok"},
                              take={"quality": "ok"}, ranked=ranked,
                              narrative=[{"kind": "summary", "statement": "x" * 900}] * 20), \
        ranked


class FakeClient:
    model = "fake/judge"

    def __init__(self, answer):
        self.answer = answer

    def ask(self, schema, system, payload, max_tokens=800):
        if isinstance(self.answer, Exception):
            raise self.answer
        return schema.model_validate(self.answer(payload))

    def describe(self):
        return {}


def test_the_packet_is_bounded_and_says_what_it_dropped():
    packet, _ = _packet()
    assert packet["omitted"]["context_claims"] > 0
    fields = {tuple(sorted(c)) for c in packet["candidates"]}
    assert len(fields) == 1                     # every candidate, the same fields


def test_a_valid_model_choice_is_a_model_decision_and_everything_else_a_fallback():
    packet, ranked = _packet()
    pick = packet["candidates"][0]["id"]
    good = judge.LLMJudge(FakeClient(lambda p: {"candidate": pick, "evidence": ["original"],
                                                "reason": "rises like the original"}))
    decided = good.decide(packet, ranked)
    assert decided["source"] == "model" and decided["decision"]["candidate"] == pick
    assert decided["raw_score_is_calibrated"] is False
    invented = judge.LLMJudge(FakeClient(lambda p: {"candidate": "voice/new-voice"}))
    bad = invented.decide(packet, ranked)
    assert bad["source"] == "fallback" and "not a candidate" in bad["reason"]
    leaky = judge.LLMJudge(FakeClient(lambda p: {"candidate": pick,
                                                 "evidence": ["holdout_transcript"]}))
    assert leaky.decide(packet, ranked)["source"] == "fallback"
    down = judge.LLMJudge(FakeClient(RuntimeError("connection refused")))
    outage = down.decide(packet, ranked)
    assert outage["state"] == "fallback" and outage["fallback"] == "retrieval"
    shy = judge.LLMJudge(FakeClient(lambda p: {"abstain": True, "reason": "unclear"}))
    abstained = shy.decide(packet, ranked)
    assert abstained["state"] == "abstained"
    assert abstained["decision"]["candidate"] == "voice/preserve"
    spent = judge.LLMJudge(FakeClient(lambda p: {"candidate": pick}), budget=0)
    assert "budget" in spent.decide(packet, ranked)["reason"]


def test_a_locked_line_is_never_sent_to_a_model():
    packet, ranked = _packet()
    packet["lock"] = {"template": "voice/trailing-finish", "strength": 0.5}
    asked = []
    locked = judge.LLMJudge(FakeClient(lambda p: asked.append(p) or {}))
    decided = locked.decide(packet, ranked)
    assert decided["source"] == "manual" and asked == []


def test_retrieval_alone_is_recorded_as_a_rule_never_as_a_model():
    packet, ranked = _packet()
    decided = judge.Judge().decide(packet, ranked)
    assert decided["source"] == "rule" and decided["engine"] == "retrieval"


def test_a_typed_decision_driver_answers_through_the_oracle():
    from doblarr.decisions import Oracle

    packet, ranked = _packet()
    pick = packet["candidates"][1]["id"]

    class Driver:
        def decide(self, state, questions):
            from types import SimpleNamespace
            return SimpleNamespace(answers={"pick": SimpleNamespace(
                type="choice", choice=pick, confidence=0.71)})

    oracle = Oracle({"model": "kev/kev-latest", "enabled": True}, factory=lambda m: Driver())
    decided = judge.DecisionJudge("kev/kev-latest", oracle=oracle).decide(packet, ranked)
    assert decided["source"] == "model" and decided["decision"]["candidate"] == pick
    assert "uncalibrated" in decided["reason"]
    with pytest.raises(ValueError):
        judge.build("gpt-magic")
