"""Clean A/B/C writing experiments: isolation on every request path, then blind judging."""

import json
import threading

import pytest

from doblarr.errors import JobCancelled
from doblarr.store import Database
from doblarr.studio import evaluation, records
from doblarr.studio.experiments import (
    ExperimentError,
    ExperimentIn,
    freeze_definition,
    run_condition,
)
from doblarr.studio.holdout import tokens
from tests.studio_fixtures import (
    DEFINITION,
    ENGLISH,
    JAPANESE,
    SENTINEL,
    SESSION,
    SPANISH,
    RecordingDriver,
    add_reference,
    echo_answer,
    install_driver,
    scene,
    translator,
)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "doblarr.db")
    yield database
    database.close()


def define(db, ja, en, es, aligned, **extra):
    body = ExperimentIn(**{**DEFINITION, "meaning": ja["id"], "adaptation": en["id"],
                           "evaluation": [es["id"]], "alignment": aligned["id"],
                           "sentinels": [SENTINEL], **extra})
    return freeze_definition(db, SESSION, body)


def contains(prompts, text):
    needle = " ".join(tokens(text))
    return any(needle in " ".join(tokens(p)) for p in prompts)


def test_each_condition_reads_only_its_allowlist(db, tmp_path, monkeypatch):
    ja, en, es, aligned = scene(db, tmp_path)
    experiment = define(db, ja, en, es, aligned)
    requests = {}
    for condition in ("A", "B", "C"):
        driver = RecordingDriver(echo_answer())
        install_driver(monkeypatch, driver)
        variant = run_condition(db, tmp_path, experiment, condition, 1, translator())
        assert variant["status"] == "complete", variant.get("error")
        assert variant["frozen"] is True
        requests[condition] = driver.prompts
    everything = [p for ps in requests.values() for p in ps]
    # The held-out adaptation never reaches any condition, sentinel or not.
    assert not contains(everything, SENTINEL)
    for line in SPANISH:
        assert not contains(everything, line["text"])
    # A: Japanese yes, English no.
    assert contains(requests["A"], JAPANESE[0]["text"])
    assert not any(contains(requests["A"], e["text"]) for e in ENGLISH)
    # B: English yes, Japanese no (timing slots only).
    assert contains(requests["B"], ENGLISH[0]["text"])
    assert not any(contains(requests["B"], j["text"]) for j in JAPANESE)
    # C: both, but only the aligned English — the unmatched added line stays out.
    assert contains(requests["C"], JAPANESE[0]["text"])
    assert contains(requests["C"], ENGLISH[2]["text"])
    assert not contains(requests["C"], ENGLISH[4]["text"])
    # Shared context is identical across conditions.
    digests = {records.get(db, "variant", f"{experiment['id']}-{c}-r1")["manifest"]
               ["shared_context"]["digest"] for c in "ABC"}
    assert len(digests) == 1


def test_the_manifest_lists_what_was_excluded_without_its_content(db, tmp_path, monkeypatch):
    ja, en, es, aligned = scene(db, tmp_path)
    experiment = define(db, ja, en, es, aligned)
    install_driver(monkeypatch, RecordingDriver(echo_answer()))
    variant = run_condition(db, tmp_path, experiment, "A", 1, translator())
    manifest = variant["manifest"]
    reasons = {row["label"]: row["reason"] for row in manifest["excluded"]}
    assert "evaluation-only" in reasons["Official Latin American dub"]
    assert "original only" in reasons["English dub"]
    dumped = json.dumps(manifest, ensure_ascii=False)
    assert SENTINEL not in dumped and "campanita dorada" not in dumped
    assert manifest["guard"]["labels"]["held-out adaptation"]["fingerprinted"] == 3
    assert any("training" in note for note in manifest["limitations"])


def test_retry_after_an_invalid_reply_is_scanned_too(db, tmp_path, monkeypatch):
    ja, en, es, aligned = scene(db, tmp_path)
    experiment = define(db, ja, en, es, aligned)
    good = echo_answer()
    driver = RecordingDriver(lambda prompt, n: "not json" if n == 1 else good(prompt, n))
    install_driver(monkeypatch, driver)
    variant = run_condition(db, tmp_path, experiment, "C", 1, translator())
    assert variant["status"] == "complete"
    assert len(driver.prompts) >= 3   # invalid first reply, retry, second excerpt
    audit = variant["guard_audit"]
    assert len(audit) == len(driver.prompts)
    assert not any(row["blocked"] for row in audit)
    assert not contains(driver.prompts, SENTINEL)


def test_a_contaminated_reference_is_blocked_before_it_is_sent(db, tmp_path, monkeypatch):
    # The "English transcript" accidentally carries a line of the official Spanish.
    polluted = [dict(u) for u in ENGLISH]
    polluted[0]["text"] = SPANISH[1]["text"]
    ja = add_reference(db, tmp_path, "Japanese original", "ja", ["meaning"], JAPANESE,
                       "original_transcript")
    en = add_reference(db, tmp_path, "English dub (bad)", "en", ["adaptation"], polluted,
                       "dub_transcript")
    es = add_reference(db, tmp_path, "Official Latin American dub", "es-MX", ["evaluation"],
                       SPANISH, "dub_transcript")
    from doblarr.studio import alignment

    body = alignment.align(JAPANESE, polluted, alignment.TimeMap(
        [alignment.MapSegment(0, 1000, -2.0, 1.0, 0.9)]))
    aligned = records.put(db, "alignment", "al-bad", {**body, "reference": en["id"]},
                          scope=SESSION)
    experiment = define(db, ja, en, es, aligned)
    driver = RecordingDriver(echo_answer())
    install_driver(monkeypatch, driver)
    variant = run_condition(db, tmp_path, experiment, "C", 1, translator())
    assert variant["status"] == "blocked"
    assert "held-out adaptation" in variant["error"]
    assert driver.prompts == []            # nothing left the process
    assert variant["frozen"] is False       # a blocked run is not a clean result
    assert "Tardaste" not in json.dumps(variant, ensure_ascii=False)


def test_shared_context_cannot_smuggle_dialogue_or_the_answer(db, tmp_path, monkeypatch):
    ja, en, es, aligned = scene(db, tmp_path)
    bad = {**DEFINITION["shared"],
           "scene_notes": {"x1": "Kaito says: " + ENGLISH[0]["text"]}}
    experiment = define(db, ja, en, es, aligned, shared=bad)
    driver = RecordingDriver(echo_answer())
    install_driver(monkeypatch, driver)
    with pytest.raises(ExperimentError, match="English dialogue"):
        run_condition(db, tmp_path, experiment, "A", 1, translator())
    assert driver.prompts == []


def test_repair_path_is_guarded_and_may_read_its_own_output(db, tmp_path, monkeypatch):
    ja, en, es, aligned = scene(db, tmp_path)
    experiment = define(db, ja, en, es, aligned)
    # The model happens to write the official line (too long for the slot). Its own
    # output may be read back by the shortening repair; that is not a leak.
    long_official = SPANISH[1]["text"] + " " + SPANISH[1]["text"]
    driver = RecordingDriver(echo_answer(
        lambda slot: long_official if slot == "ja-3" else "Hola."))
    install_driver(monkeypatch, driver)
    variant = run_condition(db, tmp_path, experiment, "A", 1, translator())
    assert variant["status"] == "complete"
    repaired = [line for unit in variant["outputs"].values() for line in unit["lines"]
                if line.get("repair")]
    assert repaired and repaired[0]["text"] == "Corto."
    assert any('"line"' in p for p in driver.prompts)   # the repair request was sent


def test_cancel_then_resume_reuses_only_matching_checkpoints(db, tmp_path, monkeypatch):
    ja, en, es, aligned = scene(db, tmp_path)
    experiment = define(db, ja, en, es, aligned)
    cancel = threading.Event()
    driver = RecordingDriver(echo_answer())
    install_driver(monkeypatch, driver)
    with pytest.raises(JobCancelled):
        run_condition(db, tmp_path, experiment, "A", 1, translator(), cancel=cancel,
                      progress=lambda done, total, detail: cancel.set())
    first = len(driver.prompts)
    assert first == 1
    assert records.get(db, "variant", f"{experiment['id']}-A-r1")["status"] == "cancelled"
    # A checkpoint from different inputs (e.g. another policy) must not be reused.
    ns = tmp_path / "studio" / "experiments" / experiment["id"] / "A-r1"
    stale = json.loads((ns / "x1.json").read_text(encoding="utf-8"))
    driver2 = RecordingDriver(echo_answer())
    install_driver(monkeypatch, driver2)
    variant = run_condition(db, tmp_path, experiment, "A", 1, translator())
    assert variant["status"] == "complete"
    assert variant["usage"]["checkpoints_reused"] == 1
    assert len(driver2.prompts) == 1          # only the second excerpt was written
    # Now poison the checkpoint of a fresh repeat and confirm it is regenerated.
    ns2 = tmp_path / "studio" / "experiments" / experiment["id"] / "A-r2"
    ns2.mkdir(parents=True)
    (ns2 / "x1.json").write_text(json.dumps({**stale, "inputs": "someone-else"}),
                                 encoding="utf-8")
    driver3 = RecordingDriver(echo_answer())
    install_driver(monkeypatch, driver3)
    again = run_condition(db, tmp_path, experiment, "A", 2, translator())
    assert again["usage"]["checkpoints_reused"] == 0
    assert len(driver3.prompts) == 2


def test_memory_candidates_matching_the_holdout_are_dropped(db, tmp_path, monkeypatch):
    from doblarr.knowledge import memory

    ja, en, es, aligned = scene(db, tmp_path)
    memory.save(db, memory.MemoryEntry(
        source_lang="ja", target_locale="es-MX", source_text=JAPANESE[0]["text"],
        target_text=SPANISH[0]["text"], duration=2.5))
    memory.save(db, memory.MemoryEntry(
        source_lang="ja", target_locale="es-MX", source_text=JAPANESE[0]["text"],
        target_text="Ya regresé, ¿me extrañaron?", duration=2.5))
    experiment = define(db, ja, en, es, aligned, name="with-memory", memory="suggestions")
    driver = RecordingDriver(echo_answer())
    install_driver(monkeypatch, driver)
    variant = run_condition(db, tmp_path, experiment, "A", 1, translator())
    assert variant["memory_rejected"] == 1
    assert not contains(driver.prompts, SENTINEL)
    assert contains(driver.prompts, "Ya regresé, ¿me extrañaron?")


def test_budget_is_finite(db, tmp_path, monkeypatch):
    ja, en, es, aligned = scene(db, tmp_path)
    experiment = define(db, ja, en, es, aligned, name="tight", max_requests=1)
    install_driver(monkeypatch, RecordingDriver(echo_answer()))
    variant = run_condition(db, tmp_path, experiment, "A", 1, translator())
    assert variant["status"] == "failed"
    assert "budget" in variant["error"]
    assert variant["usage"]["budget"]["refused"] >= 1


def test_blind_judging_reveal_and_assisted_revisions(db, tmp_path, monkeypatch):
    ja, en, es, aligned = scene(db, tmp_path)
    experiment = define(db, ja, en, es, aligned)
    for condition in "ABC":
        install_driver(monkeypatch, RecordingDriver(echo_answer()))
        run_condition(db, tmp_path, experiment, condition, 1, translator())
    session = evaluation.create(db, experiment)
    assert sorted(session["labels"]) == ["1", "2", "3"]      # never the condition letters
    blind = evaluation.view(db, session)
    assert blind["mapping"] is None
    assert "A" not in json.dumps(blind["labels"])
    unit = blind["units"][0]["unit_id"]
    label_c = next(k for k, v in session["labels"].items() if v.endswith("-C-r1"))
    label_a = next(k for k, v in session["labels"].items() if v.endswith("-A-r1"))
    for n, u in enumerate(blind["units"][:3]):
        session = evaluation.judge(db, session, evaluation.JudgmentIn(
            unit_id=u["unit_id"], dimension="listening_preference",
            choice=label_c if n < 2 else "same"), session["revision"])
    with pytest.raises(evaluation.EvaluationError):
        evaluation.holdout_lines(db, session, experiment, {})
    session = evaluation.revise(db, session, evaluation.RevisionIn(
        label=label_a, unit_id=unit, slot_id="ja-1", text="Ya llegué.",
        editing_seconds=12), session["revision"])
    assert session["revisions"][-1]["assisted"] is False
    session = evaluation.reveal(db, session, "holdout", "tester", session["revision"])
    shown = evaluation.holdout_lines(db, session, experiment, {})
    assert shown[es["id"]]["units"] == {}
    session = evaluation.revise(db, session, evaluation.RevisionIn(
        label=label_c, unit_id=unit, slot_id="ja-1", text="Ya volví."), session["revision"])
    assert session["revisions"][-1]["assisted"] is True
    session = evaluation.judge(db, session, evaluation.JudgmentIn(
        unit_id=unit, dimension="timing", choice="uncertain"), session["revision"])
    assert session["judgments"][-1]["after_holdout_reveal"] is True
    summary = evaluation.summarize(db, session)
    assert summary["conditions"]["C"]["preferred"]["listening_preference"] == 2
    assert summary["conditions"]["C"]["assisted_revisions"] == 1
    assert summary["conditions"]["A"]["corrections"] == 1
    assert summary["gate"]["state"] == "passed for this pilot"
    assert summary["clean_judgments"] == 3
    # The frozen variants were never changed by any of this.
    for variant_id in session["labels"].values():
        assert records.get(db, "variant", variant_id)["revision"] == \
            session["variant_revisions"][variant_id]
    # A stale evaluation write is a conflict, not a silent overwrite.
    with pytest.raises(records.StudioConflict):
        evaluation.judge(db, session, evaluation.JudgmentIn(
            unit_id=unit, dimension="timing", choice="same"), session["revision"] - 1)


def test_evaluation_only_reference_cannot_be_used_for_writing(db, tmp_path):
    from doblarr.studio.sources import ReferenceIn

    with pytest.raises(ValueError, match="evaluation-only"):
        ReferenceIn(label="x", language="es", roles=["evaluation", "adaptation"],
                    text={"kind": "dub_transcript"})
    ja, en, es, aligned = scene(db, tmp_path)
    with pytest.raises(ExperimentError, match="adaptation role"):
        freeze_definition(db, SESSION, ExperimentIn(
            **{**DEFINITION, "name": "bad", "meaning": ja["id"], "adaptation": es["id"],
               "alignment": aligned["id"]}))


def test_a_holdout_without_text_is_reported_not_treated_as_checked(db, tmp_path, monkeypatch):
    ja, en, _es, aligned = scene(db, tmp_path)
    empty = records.put(db, "reference", "ref-empty", {
        "label": "Official dub (not transcribed)", "language": "es", "roles": ["evaluation"],
        "text": {"kind": "dub_transcript"}}, scope=SESSION)
    experiment = freeze_definition(db, SESSION, ExperimentIn(
        **{**DEFINITION, "name": "untranscribed", "meaning": ja["id"], "adaptation": en["id"],
           "evaluation": [empty["id"]], "alignment": aligned["id"]}))
    install_driver(monkeypatch, RecordingDriver(echo_answer()))
    variant = run_condition(db, tmp_path, experiment, "A", 1, translator())
    assert variant["status"] == "complete"
    assert "no text yet" in variant["manifest"]["warnings"][0]


def test_a_service_failure_keeps_finished_excerpts_for_the_retry(db, tmp_path, monkeypatch):
    ja, en, es, aligned = scene(db, tmp_path)
    experiment = define(db, ja, en, es, aligned, name="flaky")
    good = echo_answer()

    def flaky(prompt, n):
        if n == 2:
            raise ConnectionError("model server went away")
        return good(prompt, n)

    driver = RecordingDriver(flaky)
    install_driver(monkeypatch, driver)
    failed = run_condition(db, tmp_path, experiment, "C", 1, translator())
    assert failed["status"] == "failed" and "went away" in failed["error"]
    assert failed["frozen"] is False and len(failed["outputs"]) >= 1   # first excerpt kept
    install_driver(monkeypatch, RecordingDriver(echo_answer()))
    retried = run_condition(db, tmp_path, experiment, "C", 1, translator())
    assert retried["status"] == "complete" and retried["usage"]["checkpoints_reused"] == 1
