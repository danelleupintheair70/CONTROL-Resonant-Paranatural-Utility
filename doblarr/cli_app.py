"""CLI commands that drive a running Doblarr server through its API.

    doblarr voices FILE                         # voice groups, names, sample lines
    doblarr voices FILE --lines [--group SPEAKER_01]
    doblarr voices FILE --name SPEAKER_01=Mina --move 12,14=Kaito
    doblarr queue FILE --to es-419 [--version NAME] [--set key=value ...] [--wait]
    doblarr jobs [--watch JOB_ID]
    doblarr report JOB_ID [--worst 15]          # objective checks of a finished dub
    doblarr dubref FILE [--track 5] [--compare JOB_ID]   # what the published dub says

They share the server's queue, database and speech service, so a dub queued
here shows up in the web UI and the other way round. `report` is the check a
person would otherwise do by ear: it measures what can be measured (lines
sped up or still too long, collisions, a character heard in two voices,
misread words, voices that drifted) and says PASS, WARN or FAIL for each.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path

from .config import Config


class ApiError(RuntimeError):
    pass


class Api:
    def __init__(self, config: Config, base: str | None = None):
        web = config.get("web", {}) or {}
        host = web.get("host", "127.0.0.1")
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        self.base = (base or f"http://{host}:{web.get('port', 6363)}").rstrip("/")

    def _call(self, method: str, route: str, body=None, query=None):
        url = self.base + route + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise ApiError(f"{method} {route}: {exc.code} {detail}") from None
        except urllib.error.URLError as exc:
            raise ApiError(f"Doblarr server not reachable at {self.base} ({exc.reason}); "
                           "start it with `doblarr serve`") from None

    def get(self, route, **query):
        return self._call("GET", route, query=query or None)

    def post(self, route, body):
        return self._call("POST", route, body)

    def put(self, route, body):
        return self._call("PUT", route, body)


def _job(api: Api, job_id: str) -> dict:
    jobs = api.get("/api/jobs")["jobs"]
    found = [j for j in jobs if j["id"] == job_id or j["id"].startswith(job_id)]
    if not found:
        raise ApiError(f"no job {job_id}")
    return found[0]


# -- voices -------------------------------------------------------------------------


def _pairs(values: list[str], what: str) -> list[tuple[str, str]]:
    out = []
    for value in values or []:
        if "=" not in value:
            raise ApiError(f"{what} must look like LEFT=RIGHT, got {value!r}")
        left, right = value.split("=", 1)
        out.append((left.strip(), right.strip()))
    return out


def cmd_voices(args, api: Api) -> int:
    data = api.get("/api/analysis", path=args.file)
    lines = data.get("lines") or []
    if not lines:
        print("no analysis for this file yet; queue one with "
              "`doblarr queue FILE --kind analyze --wait`")
        return 1
    names = dict(data.get("names") or {})
    changed = False
    if args.name:
        for label, name in _pairs(args.name, "--name"):
            if name in ("", "-"):
                names.pop(label, None)
            else:
                names[label] = name
        api.put("/api/analysis/names", {"path": args.file, "names": names})
        changed = True
    by_index = {line["index"]: line for line in lines}
    for spec, character in _pairs(args.move, "--move"):
        indexes = [int(x) for x in spec.replace(" ", "").split(",") if x]
        missing = [i for i in indexes if i not in by_index]
        if missing:
            raise ApiError(f"no line(s) {missing} in this episode")
        cues = [by_index[i]["cue"] for i in indexes]
        moved = api.put("/api/analysis/lines",
                        {"path": args.file, "cues": cues, "character": character})
        print(f"moved {len(cues)} line(s) to {character or 'a new voice'} -> {moved['speaker']}")
        changed = True
    if changed:
        data = api.get("/api/analysis", path=args.file)
        lines = data.get("lines") or []
        names = dict(data.get("names") or {})
    groups: dict[str, list[dict]] = defaultdict(list)
    for line in lines:
        groups[line["speaker"]].append(line)
    if args.lines:
        for line in lines:
            if args.group and line["speaker"] != args.group:
                continue
            who = names.get(line["speaker"]) or "?"
            pitch = f"{line['pitch_hz']:.0f}Hz" if line.get("pitch_hz") else "   -"
            print(f"{line['index']:4d} {line['start']:7.1f} {line['speaker']} {who[:12]:12s} "
                  f"{pitch:>6s}  {line['text'][:70]}  | {(line.get('original_text') or '')[:30]}")
        return 0
    order = sorted(groups, key=lambda k: -len(groups[k]))
    for label in order:
        rows = groups[label]
        pitches = [r["pitch_hz"] for r in rows if r.get("pitch_hz")]
        pitch = f"{statistics.median(pitches):.0f} Hz" if pitches else "-"
        print(f"{label}  {names.get(label) or '(unnamed)':14s} {len(rows):3d} lines  "
              f"median pitch {pitch}")
        for r in rows[:args.samples]:
            print(f"      {r['index']:4d}  {r['text'][:80]}")
    return 0


# -- queue / jobs -------------------------------------------------------------------


def _value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _wait(api: Api, job_id: str, quiet: bool = False) -> dict:
    last = None
    while True:
        job = _job(api, job_id)
        state = (job["status"], job["stage"], job["progress"], (job.get("message") or "")[:100])
        if state != last and not quiet:
            print(f"{time.strftime('%H:%M:%S')}  {job['status']:9s} {job['stage'] or '':12s} "
                  f"{job['progress'] or 0:3d}%  {state[3]}", flush=True)
            last = state
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(15)


def cmd_queue(args, api: Api) -> int:
    overrides = {"dub.dry_run": False}
    if args.version:
        overrides["dub.version_name"] = args.version
    for key, value in _pairs(args.set, "--set"):
        overrides[key] = _value(value)
    title = args.title or f"{Path(args.file).stem} · {args.version or args.kind}"
    job = api.post("/api/jobs", {"title": title, "source": "manual", "source_lang": args.source,
                                 "target_lang": args.to, "path": args.file, "kind": args.kind,
                                 "force": args.force, "overrides": overrides})["job"]
    print(f"queued {job['id']}  {title}")
    if not args.wait:
        return 0
    job = _wait(api, job["id"])
    print(f"{job['status']}: {job.get('message') or ''}")
    return 0 if job["status"] == "done" else 1


def cmd_jobs(args, api: Api) -> int:
    if args.watch:
        job = _wait(api, args.watch)
        return 0 if job["status"] == "done" else 1
    for job in api.get("/api/jobs")["jobs"][:args.limit]:
        print(f"{job['id']}  {job['status']:9s} {job['stage'] or '':10s} "
              f"{job['progress'] or 0:3d}%  {job['title']}")
    return 0


# -- report -------------------------------------------------------------------------


def _verdict(level: str, text: str) -> str:
    return f"  {level:4s}  {text}"


def report(version: dict, counters: dict, names: dict[str, str]) -> tuple[list[str], int]:
    """Objective checks of one saved dub; returns printable lines and failures."""
    out, failures = [], 0
    segments = {s["index"]: s for s in version["script"]["segments"]}
    total = len(segments) or 1
    stretched = int(counters.get("stretched_lines") or 0)
    over = int(counters.get("timing_flags") or 0)
    collisions = int((counters.get("conversation") or {}).get("collisions") or 0)
    open_codes: Counter[str] = Counter()
    for cue in version.get("cues") or []:
        for finding in cue.get("findings") or []:
            if finding.get("disposition") in (None, "open"):
                open_codes[finding["code"]] += 1

    def check(value, warn, fail, text):
        nonlocal failures
        level = "FAIL" if value >= fail else "WARN" if value >= warn else "PASS"
        failures += level == "FAIL"
        out.append(_verdict(level, text))

    out.append("Timing")
    check(stretched / total, 0.35, 0.5, f"{stretched}/{total} lines sped up "
          f"(max {counters.get('max_stretch', 1.0)}x)")
    check(over / total, 0.1, 0.2, f"{over}/{total} lines still longer than their slot")
    check(collisions / total, 0.06, 0.12, f"{collisions} lines run into the next speaker")
    rejected = sum(1 for v in ((counters.get("decisions") or {}).get("rewrite_check") or {})
                   .get("verdicts", []) if v.get("value") == "rejected" and v.get("applied"))
    repairs = int(counters.get("timing_repairs") or 0)
    out.append(_verdict("INFO", f"{repairs} lines shortened, {rejected} shortenings rejected"))

    out.append("Casting")
    profiles: dict[str, set] = defaultdict(set)
    users: dict[str, set] = defaultdict(set)
    for voice in version.get("voices") or []:
        seg = segments.get(voice["index"])
        if seg is None:
            continue
        who = names.get(seg["speaker"]) or seg["speaker"]
        profiles[who].add(voice["profile"])
        users[voice["profile"]].add(who)
    split = {who: len(p) for who, p in profiles.items() if len(p) > 1 and who in names.values()}
    check(len(split), 1, 1, "every named character has one voice" if not split else
          "characters heard in more than one voice: "
          + ", ".join(f"{w} ({n})" for w, n in split.items()))
    shared = {p: sorted(u) for p, u in users.items()
              if len([x for x in u if x in names.values()]) > 1}
    check(len(shared), 1, 1, "no voice is shared by two named characters" if not shared else
          "one voice for several characters: "
          + "; ".join(", ".join(u) for u in shared.values()))
    unnamed = sorted({s["speaker"] for s in segments.values() if s["speaker"] not in names})
    lines_unnamed = sum(1 for s in segments.values() if s["speaker"] not in names)
    check(lines_unnamed / total, 0.15, 0.3,
          f"{lines_unnamed} lines in {len(unnamed)} unnamed voice groups")

    out.append("Speech")
    misread = open_codes.get("text_mismatch", 0) + open_codes.get("verification_mismatch", 0)
    verified = sum(1 for c in version.get("cues") or []
                   if (c.get("verification") or {}).get("state") not in (None, "skipped"))
    if verified:
        check(misread / max(1, verified), 0.05, 0.12,
              f"{misread} of {verified} checked lines misread")
    else:
        out.append(_verdict("INFO", "words not checked (quality.asr is off)"))
    drift = open_codes.get("voice_drift", 0)
    out.append(_verdict("WARN" if drift else "PASS", f"{drift} takes drifted from their voice")
               if any("voice_similarity" in (t.get("checks") or {})
                      for c in version.get("cues") or [] for t in c["audio"]["takes"])
               else _verdict("INFO", "voices not checked (quality.voice_check is off)"))
    other = {k: v for k, v in open_codes.items()
             if k not in {"timing_overflow", "text_mismatch", "voice_drift", "pace_jump"}
             and not k.startswith("decision_")}
    if other:
        ranked = sorted(other.items(), key=lambda kv: -kv[1])
        out.append(_verdict("INFO", "other open findings: "
                            + ", ".join(f"{k} {v}" for k, v in ranked)))
    return out, failures


def overruns(version: dict) -> list[tuple[float, int]]:
    """(seconds past the slot, line) measured on the timed audio that was mixed."""
    segments = {s["index"]: s for s in version["script"]["segments"]}
    out = []
    for cue in version.get("cues") or []:
        seg = segments.get(cue["index"])
        renders = {r["role"]: r for r in (cue.get("audio") or {}).get("renders") or []}
        timed = renders.get("phrased") or renders.get("fitted")
        if seg is None or not timed or not timed.get("duration"):
            continue
        extra = timed["duration"] - (seg["end"] - seg["start"])
        if extra > 0.05:
            out.append((extra, cue["index"]))
    return out


def cmd_report(args, api: Api) -> int:
    job = _job(api, args.job)
    if job["status"] != "done" or not job.get("version_file"):
        print(f"job {job['id']} is {job['status']}; nothing to report yet")
        return 1
    version = json.loads(Path(job["version_file"]).read_text(encoding="utf-8"))
    counters = json.loads(Path(job["report_file"]).read_text(encoding="utf-8")).get("counters", {})
    try:
        names = api.get("/api/analysis", path=job["input_file"]).get("names") or {}
    except ApiError:
        names = {}
    lines, failures = report(version, counters, names)
    print(f"{job['title']}  ({job['id']}, version {job.get('version_id', '')[:12]})")
    print("\n".join(lines))
    if args.worst:
        segments = {s["index"]: s for s in version["script"]["segments"]}
        worst = overruns(version)
        print("Longest overruns")
        for extra, index in sorted(worst, reverse=True)[:args.worst]:
            seg = segments.get(index, {})
            print(f"  +{extra:4.2f}s  line {index:4d} {seg.get('speaker', '')}  "
                  f"{seg.get('text', '')[:70]}")
    return 1 if failures else 0


# -- published dub reference ---------------------------------------------------------


def _episode_files(config: Config, video: str, locale: str):
    stem = Path(video).stem
    media = Path(config.work_dir) / "media"
    scripts = sorted(media.glob(f"*/{locale}/{stem}.script.json"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    if not scripts:
        raise ApiError(f"no {locale} script for {stem}; analyse or dub the episode first")
    script = scripts[0]
    folder = script.parent.parent
    evidence = {}
    speakers = folder / f"{stem}.speakers.json"
    if speakers.is_file():
        data = json.loads(speakers.read_text(encoding="utf-8"))
        evidence = {t["stream"]: t for t in data.get("track_evidence") or []}
    return script, folder, stem, evidence


def cmd_dubref(args, config: Config) -> int:
    from . import dub_reference

    script, folder, stem, evidence = _episode_files(config, args.file, args.locale)
    tracks = {s: e for s, e in evidence.items() if e.get("lang") == args.locale.split("-")[0]}
    stream = args.track if args.track is not None else next(
        (s for s, e in tracks.items() if "latin" in (e.get("title") or "").casefold()), None)
    if stream is None:
        stream = next(iter(tracks), None)
    if stream is None:
        raise ApiError("no dub track in this language was found next to the episode; "
                       "pass --track N")
    audio = folder / f"{stem}.audio{stream}.16k.wav"
    if not audio.is_file():
        raise ApiError(f"{audio.name} is not extracted yet; regroup the episode's voices "
                       "with its dub tracks first")
    found = evidence.get(stream) or {}
    if found and found.get("state") != "verified":
        raise ApiError(f"track {stream} is not verified as aligned ({found.get('state')})")
    out = dub_reference.sidecar(script, stream)
    if out.is_file() and not args.refresh:
        ref = json.loads(out.read_text(encoding="utf-8"))
    else:
        print(f"transcribing track {stream} ({found.get('title', '?')}) with "
              f"{args.model} ...", flush=True)
        ref = dub_reference.build(script, audio, stream, args.locale.split("-")[0],
                                  float(found.get("offset") or 0.0),
                                  float(found.get("rate") or 1.0), args.model, args.device)
    lines = ref["lines"]
    heard = [ln for ln in lines if ln["text"]]
    target = dub_reference.reference_file(script, stream)
    target.write_text(json.dumps(dub_reference.reference(ref), ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print(f"{found.get('title', 'track ' + str(stream))}: {len(heard)}/{len(lines)} lines "
          f"heard -> {out.name}")
    print(f"to translate along it: --set translate.reference_policy=follow_edition "
          f"--set \"translate.reference_file={target}\"")
    ours = {}
    if args.compare:
        job = _job(Api(config), args.compare)
        version = json.loads(Path(job["version_file"]).read_text(encoding="utf-8"))
        ours = {s["index"]: s for s in version["script"]["segments"]}
        cues = {c["index"]: c for c in version.get("cues") or []}
    print("Names and terms the dub repeats: " + ", ".join(
        f"{w} {n}" for w, n in dub_reference.frequent_names(lines)[:40]))
    if ours:
        longer = shorter = 0
        for ln in heard:
            seg = ours.get(ln["index"])
            renders = {r["role"]: r for r in (cues.get(ln["index"], {}).get("audio") or {})
                       .get("renders") or []}
            timed = (renders.get("fitted") or {}).get("duration")
            if seg and timed and ln["seconds"]:
                longer += timed > ln["seconds"] * 1.25
                shorter += timed < ln["seconds"] * 0.8
        print(f"Against our dub: {longer} lines run 25% longer than the published one, "
              f"{shorter} 20% shorter")
    if args.lines:
        for ln in lines:
            seg = ours.get(ln["index"])
            print(f"{ln['index']:4d}  dub: {ln['text'][:90]}")
            if seg:
                print(f"      us:  {seg['text'][:90]}")
    return 0


# -- wiring -------------------------------------------------------------------------


def add_parsers(sub) -> None:
    v = sub.add_parser("voices", help="voice groups of an analysed episode; name and move lines")
    v.add_argument("file", help="the episode's video file, as the library knows it")
    v.add_argument("--lines", action="store_true", help="every line with its group")
    v.add_argument("--group", default=None, help="with --lines: only this group")
    v.add_argument("--samples", type=int, default=3, help="sample lines per group")
    v.add_argument("--name", action="append", default=[], metavar="SPEAKER_NN=NAME",
                   help="name a group (repeatable); NAME '-' clears it")
    v.add_argument("--move", action="append", default=[], metavar="I,J=NAME",
                   help="move lines (by index) to a character's group (repeatable)")

    q = sub.add_parser("queue", help="queue a dub on the running server")
    q.add_argument("file")
    q.add_argument("--to", required=True, help="target locale, e.g. es-419")
    q.add_argument("--from", dest="source", default="auto")
    q.add_argument("--kind", choices=["full", "tease", "audition", "analyze"], default="full")
    q.add_argument("--version", default=None, help="name for the saved version")
    q.add_argument("--title", default=None)
    q.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="config override for this job, e.g. quality.asr=suspicious")
    q.add_argument("--force", action="store_true")
    q.add_argument("--wait", action="store_true", help="follow the job until it ends")

    j = sub.add_parser("jobs", help="list jobs, or follow one")
    j.add_argument("--watch", default=None, metavar="JOB_ID")
    j.add_argument("--limit", type=int, default=15)

    r = sub.add_parser("report", help="objective checks of a finished dub (PASS/WARN/FAIL)")
    r.add_argument("job", help="job id (a prefix is enough)")
    r.add_argument("--worst", type=int, default=10, help="list the N longest overruns")

    d = sub.add_parser("dubref", help="transcribe an episode's published dub track and "
                                      "line it up with our script")
    d.add_argument("file")
    d.add_argument("--locale", default="es-419")
    d.add_argument("--track", type=int, default=None, help="stream index (default: Latino)")
    d.add_argument("--model", default="large-v3")
    d.add_argument("--device", default="cuda")
    d.add_argument("--refresh", action="store_true", help="transcribe again")
    d.add_argument("--compare", default=None, metavar="JOB_ID",
                   help="put a finished dub's lines next to the published ones")
    d.add_argument("--lines", action="store_true", help="print every line")


COMMANDS: dict[str, Callable[..., int]] = {
    "voices": cmd_voices, "queue": cmd_queue, "jobs": cmd_jobs, "report": cmd_report,
    "dubref": cmd_dubref}
LOCAL = {"dubref"}


def run(args: argparse.Namespace, config: Config) -> int:
    try:
        if args.command in LOCAL:
            return COMMANDS[args.command](args, config)
        return COMMANDS[args.command](args, Api(config))
    except ApiError as exc:
        print(exc, file=sys.stderr)
        return 1
