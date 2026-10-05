"""The doblarr subcommands: checks, step planning, settings and the make flow."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from doblarr.commands import base, jobs, make, research, settings
from doblarr.config import Config


def _version(voices, speakers, findings=None, renders=None):
    segments = [{"index": i, "speaker": s, "text": "hola", "start": float(i * 3),
                 "end": float(i * 3 + 1)} for i, s in enumerate(speakers)]
    cues = [{"index": i, "cue_id": f"c{i}", "findings": (findings or {}).get(i, []),
             "verification": {}, "audio": {"takes": [], "renders": (renders or {}).get(i, [])}}
            for i in range(len(speakers))]
    return {"script": {"segments": segments}, "cues": cues,
            "voices": [{"index": i, "profile": p} for i, p in enumerate(voices)]}


def _open(code):
    return {"code": code, "disposition": "open"}


def test_a_character_in_two_voices_fails():
    version = _version(["v1", "v2", "v3"], ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"])
    names = {"SPEAKER_00": "Mina", "SPEAKER_01": "Mina", "SPEAKER_02": "Kaito"}
    checks, failures = jobs.report(version, {}, names)
    assert failures == 1
    assert any(c["level"] == "FAIL" and "Mina (2)" in c["text"] for c in checks)


def test_timing_thresholds_count_open_findings_only():
    version = _version(["v1"] * 4, ["SPEAKER_00"] * 4)
    counters = {"stretched_lines": 1, "timing_flags": 1, "conversation": {"collisions": 0}}
    checks, failures = jobs.report(version, counters, {"SPEAKER_00": "Ren"})
    assert failures == 1                     # 1 of 4 lines still over is a FAIL
    assert {c["group"] for c in checks} == {"Timing", "Casting", "Speech"}


def test_fix_picks_misread_drifted_and_rambling_lines_only():
    version = _version(["v"] * 4, ["S"] * 4, findings={
        0: [_open("text_mismatch")],
        1: [{"code": "voice_drift", "disposition": "obsolete"}],
        2: [_open("timing_overflow")]},
        renders={3: [{"role": "fitted", "duration": 2.6}],     # slot is 1 s: 1.6 s over
                 2: [{"role": "fitted", "duration": 1.3}]})
    assert jobs.lines_to_fix(version) == {0: ["text_mismatch"], 3: ["1.6s over"]}


def test_pairs_and_values():
    assert base.pairs(["SPEAKER_01=Mina", "3,4=Kaito Sora"], "x") == [
        ("SPEAKER_01", "Mina"), ("3,4", "Kaito Sora")]
    with pytest.raises(base.ApiError):
        base.pairs(["oops"], "--name")
    assert [base.value(v) for v in ("2", "true", "off", "es-419", "[1, 2]")] == [
        2, True, False, "es-419", [1, 2]]


def test_steps_skip_only_and_typos():
    assert make.steps(None, None) == list(make.STEPS)
    assert make.steps("lookup,fix", None) == ["doctor", "analyze", "voices", "dub", "report"]
    assert make.steps(None, "report,fix") == ["report", "fix"]
    with pytest.raises(base.ApiError, match="lokup"):
        make.steps("lokup", None)


def test_settings_know_their_keys_and_refuse_typos():
    annotation, default = settings.field_for("translate.published_dub")
    assert default == "follow" and settings.choices(annotation) == ["follow", "suggest", "off"]
    assert settings.field_for("translate.glossary.Kaito") is not None    # inside a map
    assert settings.field_for("translate.publishd_dub") is None
    config = Config.load("does-not-exist.yaml")
    with pytest.raises(base.ApiError, match="did you mean translate.published_dub"):
        settings.check(config, {"translate.publishd_dub": "off"})
    with pytest.raises(base.ApiError, match="published_dub"):
        settings.check(config, {"translate.published_dub": "sometimes"})
    settings.check(config, {"translate.published_dub": "off"})
    assert settings.nest({"a.b": 1, "a.c": 2}) == {"a": {"b": 1, "c": 2}}


def test_settings_set_writes_the_file_when_no_server_runs(tmp_path, capsys):
    path = tmp_path / "config.yaml"
    path.write_text("translate:\n  provider: claude\n", encoding="utf-8")
    config = Config.load(path)
    args = SimpleNamespace(action="set", keys=["translate.provider=prompture"], json=True)
    ctx = base.Ctx(args, config, api_client=SimpleNamespace(alive=lambda: False))
    assert settings.cmd_settings(ctx) == 0
    assert Config.load(path)["translate"]["provider"] == "prompture"
    assert json.loads(capsys.readouterr().out)["changes"] == {"translate.provider": "prompture"}


def test_catalogue_pages_come_from_wikidata_ids():
    assert research.catalogue_urls({"anilist": "21", "imdb": "tt1", "mal": "7"}) == [
        ("anilist", "https://anilist.co/anime/21"), ("mal", "https://myanimelist.net/anime/7")]


def test_a_folder_stands_for_its_videos(tmp_path):
    for name in ("Harbor Lights - 02.mkv", "Harbor Lights - 01.mkv", "notes.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert [Path(p).name for p in base.video_files([str(tmp_path)])] == [
        "Harbor Lights - 01.mkv", "Harbor Lights - 02.mkv"]


class FakeServer:
    """Just enough of the API for `make`: one analysis, one dub, one review."""

    def __init__(self, tmp_path, flagged=False):
        self.tmp = tmp_path
        self.posted = []
        self.flagged = flagged
        self.analysed = False
        self.jobs = {}

    def alive(self):
        return True

    def _done(self, job_id, version):
        vfile = self.tmp / f"{job_id}.json"
        vfile.write_text(json.dumps(version), encoding="utf-8")
        rfile = self.tmp / f"{job_id}.report.json"
        rfile.write_text(json.dumps({"counters": {}}), encoding="utf-8")
        self.jobs[job_id] = {"id": job_id, "status": "done", "stage": "mux", "progress": 100,
                             "message": "", "title": "t", "input_file": "ep.mkv",
                             "version_file": str(vfile), "report_file": str(rfile),
                             "version_id": "v" + job_id, "output_file": f"{job_id}.mkv"}

    def get(self, route, **query):
        if route == "/api/analysis":
            if not self.analysed:
                return {}
            return {"lines": [{"index": 0, "speaker": "SPEAKER_00", "text": "hola",
                               "start": 0.0}],
                    "names": {"SPEAKER_00": "Mina"},
                    "identity": {"series_id": "show:tvdb:1"},
                    "track_evidence": [{"stream": 5, "lang": "es", "title": "Latino",
                                        "state": "verified"}]}
        if route == "/api/jobs":
            return {"jobs": list(self.jobs.values())}
        raise AssertionError(route)

    def post(self, route, body):
        self.posted.append((route, body))
        job_id = f"j{len(self.posted)}"
        if route == "/api/jobs" and body["kind"] == "analyze":
            self.analysed = True
            self._done(job_id, _version(["v"], ["SPEAKER_00"]))
        elif route == "/api/jobs":
            findings = {0: [_open("text_mismatch")]} if self.flagged else {}
            self._done(job_id, _version(["v"], ["SPEAKER_00"], findings=findings))
        elif route.endswith("/review"):
            self._done(job_id, _version(["v"], ["SPEAKER_00"]))
        else:
            raise AssertionError(route)
        return {"job": self.jobs[job_id]}


def _make_args(**over):
    values = dict(files=["ep.mkv"], to="es-419", source="auto", version=None, set=[],
                  skip="doctor,lookup", only=None, job=None, rounds=1, anyway=False,
                  keep_going=False, json=True)
    values.update(over)
    return SimpleNamespace(**values)


def test_make_analyses_dubs_fixes_and_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    server = FakeServer(tmp_path, flagged=True)
    ctx = base.Ctx(_make_args(), Config.load("does-not-exist.yaml"), api_client=server)
    assert make.cmd_make(ctx) == 0
    kinds = [b.get("kind", "review") for _r, b in server.posted]
    assert kinds == ["analyze", "full", "review"]          # the flagged line was re-voiced
    assert server.posted[-1][1]["edits"] == [{"index": 0, "cue": "c0", "regenerate": True}]
    result = json.loads(capsys.readouterr().out)          # --json prints one document
    assert result[0]["steps"]["analyze"]["published_dub"] == ["Latino"]
    assert result[0]["steps"]["report"]["failures"] == 0


def test_make_runs_nothing_it_was_told_to_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    server = FakeServer(tmp_path)
    ctx = base.Ctx(_make_args(skip="doctor,lookup,dub,fix,report"),
                   Config.load("does-not-exist.yaml"), api_client=server)
    assert make.cmd_make(ctx) == 0
    assert [b["kind"] for _r, b in server.posted] == ["analyze"]
