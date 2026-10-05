"""doblarr report — objective checks of a saved dub."""

from doblarr import cli_app


def _version(voices, speakers, findings=None):
    segments = [{"index": i, "speaker": s, "text": "hola"} for i, s in enumerate(speakers)]
    cues = [{"index": i, "findings": (findings or {}).get(i, []), "verification": {},
             "audio": {"takes": []}} for i in range(len(speakers))]
    return {"script": {"segments": segments}, "cues": cues,
            "voices": [{"index": i, "profile": p} for i, p in enumerate(voices)]}


def test_a_character_in_two_voices_fails():
    version = _version(["v1", "v2", "v3"], ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"])
    names = {"SPEAKER_00": "Mina", "SPEAKER_01": "Mina", "SPEAKER_02": "Kaito"}
    lines, failures = cli_app.report(version, {}, names)
    assert failures == 1
    assert any("FAIL" in line and "Mina (2)" in line for line in lines)


def test_timing_thresholds_and_open_findings_only():
    version = _version(["v1"] * 4, ["SPEAKER_00"] * 4, findings={
        0: [{"code": "timing_overflow", "disposition": "open"}],
        1: [{"code": "timing_overflow", "disposition": "obsolete"}]})
    counters = {"stretched_lines": 1, "timing_flags": 1, "conversation": {"collisions": 0}}
    lines, failures = cli_app.report(version, counters, {"SPEAKER_00": "Ren"})
    assert failures == 1                     # 1 of 4 lines still over is a FAIL
    assert any(line.strip().startswith("PASS") and "collisions" not in line
               for line in lines)


def test_pairs_parse_and_reject():
    assert cli_app._pairs(["SPEAKER_01=Mina", "3,4=Kaito Sora"], "x") == [
        ("SPEAKER_01", "Mina"), ("3,4", "Kaito Sora")]
    try:
        cli_app._pairs(["oops"], "--name")
    except cli_app.ApiError:
        pass
    else:
        raise AssertionError("expected ApiError")
