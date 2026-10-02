"""Grouping quality reported per error kind, not as one score."""

import numpy as np

from doblarr import speaker_eval


def test_merges_and_missed_brief_characters_are_reported_apart():
    truth = ["Kaito"] * 6 + ["Mina"] * 6 + ["Guard"]
    perfect = ["A"] * 6 + ["B"] * 6 + ["C"]
    assert speaker_eval.evaluate(perfect, truth, [1.0] * 13)["bcubed"]["f1"] == 1.0
    absorbed = ["A"] * 6 + ["B"] * 7          # the guard's one line filed under Mina
    result = speaker_eval.evaluate(absorbed, truth, [1.0] * 13)
    assert result["missed_brief"] == [{"character": "Guard", "lines": 1}]
    mixed = ["A"] * 12 + ["C"]
    merged = speaker_eval.evaluate(mixed, truth, [1.0] * 13)["merges"]
    assert merged and merged[0]["share"] == 0.5
    assert speaker_eval.naming_precision(mixed, truth) < 0.6


def test_recognition_reports_precision_and_coverage_together():
    rng = np.random.default_rng(0)
    centres = {"Kaito": np.array([1.0, 0, 0]), "Mina": np.array([0, 1.0, 0])}
    vectors, truth = [], []
    for name, centre in centres.items():
        for _ in range(8):
            v = centre + rng.normal(0, 0.1, 3)
            vectors.append(v / np.linalg.norm(v))
            truth.append(name)
    found = speaker_eval.recognition(vectors, truth, [2.0] * 16, floor=0.3, margin=0.2)
    assert found["top1"] == 1.0 and found["precision"] == 1.0
    strict = speaker_eval.recognition(vectors, truth, [2.0] * 16, floor=0.99, margin=0.2)
    assert strict["coverage"] < found["coverage"]       # abstaining costs coverage
