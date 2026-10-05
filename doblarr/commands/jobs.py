"""Queue dubs, follow them, check them, and repair what the checks found.

    doblarr queue FILE --to es-419 [--version NAME] [--set key=value] [--wait]
    doblarr jobs [--watch JOB]
    doblarr report JOB                    # PASS/WARN/FAIL on timing, casting, speech
    doblarr fix JOB [--rounds 1]          # re-voice only the lines report flags
    doblarr line JOB INDEX [--text T | --retake | --voice V] [--clip out.wav]
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .base import ApiError, Ctx, find_job, load_version, pairs, value, wait

# -- queue / jobs ------------------------------------------------------------------


def queue_job(ctx: Ctx, file: str, *, to: str, source: str = "auto", kind: str = "full",
              version: str | None = None, title: str | None = None,
              settings: list[str] | None = None, force: bool = False) -> dict:
    overrides: dict = {"dub.dry_run": False}
    if version:
        overrides["dub.version_name"] = version
    for key, raw in pairs(settings, "--set"):
        overrides[key] = value(raw)
    title = title or f"{Path(file).stem} · {version or kind}"
    job = ctx.api.post("/api/jobs", {"title": title, "source": "manual", "source_lang": source,
                                     "target_lang": to, "path": file, "kind": kind,
                                     "force": force, "overrides": overrides})["job"]
    ctx.say(f"queued {job['id']}  {title}")
    return job


def cmd_queue(ctx: Ctx) -> int:
    a = ctx.args
    job = queue_job(ctx, a.file, to=a.to, source=a.source, kind=a.kind, version=a.version,
                    title=a.title, settings=a.set, force=a.force)
    if a.wait:
        job = wait(ctx, job["id"])
    ctx.result(job, f"{job['status']}: {job.get('message') or ''}" if a.wait else None)
    return 0 if job["status"] in ("done", "queued", "running") else 1


def cmd_jobs(ctx: Ctx) -> int:
    if ctx.args.watch:
        job = wait(ctx, ctx.args.watch)
        ctx.result(job, f"{job['status']}: {job.get('message') or ''}")
        return 0 if job["status"] == "done" else 1
    jobs = ctx.api.get("/api/jobs")["jobs"][:ctx.args.limit]
    ctx.result(jobs, [f"{j['id']}  {j['status']:9s} {j['stage'] or '':10s} "
                      f"{j['progress'] or 0:3d}%  {j['title']}" for j in jobs])
    return 0


# -- report ------------------------------------------------------------------------


def report(version: dict, counters: dict, names: dict[str, str]) -> tuple[list[dict], int]:
    """Objective checks of one saved dub: [{group, level, text}] and the failures."""
    checks: list[dict] = []
    failures = 0
    segments = {s["index"]: s for s in version["script"]["segments"]}
    total = len(segments) or 1
    stretched = int(counters.get("stretched_lines") or 0)
    over = int(counters.get("timing_flags") or 0)
    collisions = int((counters.get("conversation") or {}).get("collisions") or 0)
    codes = open_codes(version)

    def add(group: str, level: str, text: str) -> None:
        nonlocal failures
        failures += level == "FAIL"
        checks.append({"group": group, "level": level, "text": text})

    def check(group: str, amount: float, warn: float, fail: float, text: str) -> None:
        add(group, "FAIL" if amount >= fail else "WARN" if amount >= warn else "PASS", text)

    check("Timing", stretched / total, 0.35, 0.5,
          f"{stretched}/{total} lines sped up (max {counters.get('max_stretch', 1.0)}x)")
    check("Timing", over / total, 0.1, 0.2, f"{over}/{total} lines still longer than their slot")
    check("Timing", collisions / total, 0.06, 0.12,
          f"{collisions} lines run into the next speaker")
    rejected = sum(1 for v in ((counters.get("decisions") or {}).get("rewrite_check") or {})
                   .get("verdicts", []) if v.get("value") == "rejected" and v.get("applied"))
    add("Timing", "INFO", f"{int(counters.get('timing_repairs') or 0)} lines shortened, "
                          f"{rejected} shortenings rejected")

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
    check("Casting", len(split), 1, 1, "every named character has one voice" if not split else
          "characters heard in more than one voice: "
          + ", ".join(f"{w} ({n})" for w, n in split.items()))
    shared = {p: sorted(u) for p, u in users.items()
              if len([x for x in u if x in names.values()]) > 1}
    check("Casting", len(shared), 1, 1, "no voice is shared by two named characters"
          if not shared else "one voice for several characters: "
          + "; ".join(", ".join(u) for u in shared.values()))
    unnamed = {s["speaker"] for s in segments.values() if s["speaker"] not in names}
    lines_unnamed = sum(1 for s in segments.values() if s["speaker"] not in names)
    check("Casting", lines_unnamed / total, 0.15, 0.3,
          f"{lines_unnamed} lines in {len(unnamed)} unnamed voice groups")

    misread = codes.get("text_mismatch", 0)
    verified = sum(1 for c in version.get("cues") or []
                   if (c.get("verification") or {}).get("state") not in (None, "skipped"))
    if verified:
        check("Speech", misread / max(1, verified), 0.05, 0.12,
              f"{misread} of {verified} checked lines misread")
    else:
        add("Speech", "INFO", "words not checked (quality.asr is off)")
    if any("voice_similarity" in (t.get("checks") or {})
           for c in version.get("cues") or [] for t in c["audio"]["takes"]):
        drift = codes.get("voice_drift", 0)
        add("Speech", "WARN" if drift else "PASS", f"{drift} takes drifted from their voice")
    else:
        add("Speech", "INFO", "voices not checked (quality.voice_check is off)")
    other = {k: v for k, v in codes.items()
             if k not in {"timing_overflow", "text_mismatch", "voice_drift", "pace_jump"}
             and not k.startswith("decision_")}
    if other:
        ranked = sorted(other.items(), key=lambda kv: -kv[1])
        add("Speech", "INFO", "other open findings: " + ", ".join(f"{k} {v}" for k, v in ranked))
    return checks, failures


def open_codes(version: dict) -> Counter[str]:
    codes: Counter[str] = Counter()
    for cue in version.get("cues") or []:
        for finding in cue.get("findings") or []:
            if finding.get("disposition") in (None, "open"):
                codes[finding["code"]] += 1
    return codes


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


def names_for(ctx: Ctx, file: str) -> dict[str, str]:
    try:
        return ctx.api.get("/api/analysis", path=file).get("names") or {}
    except ApiError:
        return {}


def report_text(job: dict, checks: list[dict], worst: list[tuple[float, int]],
                segments: dict[int, dict]) -> list[str]:
    out = [f"{job['title']}  ({job['id']}, version {(job.get('version_id') or '')[:12]})"]
    group = None
    for row in checks:
        if row["group"] != group:
            group = row["group"]
            out.append(group)
        out.append(f"  {row['level']:4s}  {row['text']}")
    if worst:
        out.append("Longest overruns")
        for extra, index in worst:
            seg = segments.get(index, {})
            out.append(f"  +{extra:4.2f}s  line {index:4d} {seg.get('speaker', '')}  "
                       f"{seg.get('text', '')[:70]}")
    return out


def check_job(ctx: Ctx, job: dict, worst: int = 10,
              show: bool = True) -> tuple[list[dict], int, dict]:
    """Run the checks on a finished job; `show` prints them as this command's result,
    otherwise they are printed for a person only (a step inside `make`)."""
    version, counters = load_version(job)
    checks, failures = report(version, counters, names_for(ctx, job["input_file"]))
    segments = {s["index"]: s for s in version["script"]["segments"]}
    longest = sorted(overruns(version), reverse=True)[:worst]
    if not show:
        for line in report_text(job, checks, longest, segments):
            ctx.say(line)
        return checks, failures, version
    ctx.result({"job": job["id"], "version": job.get("version_id"), "output": job.get(
                    "output_file"), "checks": checks, "failures": failures,
                "overruns": [{"line": i, "seconds": round(s, 2)} for s, i in longest]},
               report_text(job, checks, longest, segments))
    return checks, failures, version


def cmd_report(ctx: Ctx) -> int:
    _checks, failures, _version = check_job(ctx, find_job(ctx.api, ctx.args.job),
                                            ctx.args.worst)
    return 1 if failures else 0


# -- fix: re-voice the lines the checks flagged --------------------------------------


def lines_to_fix(version: dict, min_overrun: float = 1.0) -> dict[int, list[str]]:
    """Each flagged line and why: misread words, a drifted voice, or a take far
    past its slot. A new sample fixes these more often than not; a line that is
    long because of its words is the timing repair's job, not a retake's."""
    reasons: dict[int, list[str]] = defaultdict(list)
    for cue in version.get("cues") or []:
        for finding in cue.get("findings") or []:
            if finding.get("disposition") not in (None, "open"):
                continue
            code = finding["code"]
            if code in ("text_mismatch", "voice_drift", "extra_sound") \
                    and code not in reasons[cue["index"]]:
                reasons[cue["index"]].append(code)
    for extra, index in overruns(version):
        if extra >= min_overrun:
            reasons[index].append(f"{extra:.1f}s over")
    return {i: r for i, r in sorted(reasons.items()) if r}


def revoice(ctx: Ctx, job: dict, edits: list[dict]) -> dict:
    """Queue a re-render of a finished job with these line edits."""
    answer = ctx.api.post(f"/api/jobs/{job['id']}/review", {"edits": edits})
    return answer["job"]


def fix_job(ctx: Ctx, job: dict, rounds: int = 1, min_overrun: float = 1.0,
            dry_run: bool = False) -> dict:
    """Re-voice the flagged lines, re-check, and repeat up to `rounds` times."""
    for round_number in range(1, max(1, rounds) + 1):
        version, _counters = load_version(job)
        flagged = lines_to_fix(version, min_overrun)
        if not flagged:
            ctx.say("nothing left to fix")
            return job
        cues = {c["index"]: c.get("cue_id") for c in version.get("cues") or []}
        ctx.say(f"round {round_number}: re-voicing {len(flagged)} line(s): " + ", ".join(
            f"{i} ({'/'.join(r)})" for i, r in list(flagged.items())[:12])
            + (" ..." if len(flagged) > 12 else ""))
        if dry_run:
            return job
        job = revoice(ctx, job, [{"index": i, "cue": cues.get(i), "regenerate": True}
                                 for i in flagged])
        ctx.say(f"queued {job['id']}")
        job = wait(ctx, job["id"])
        if job["status"] != "done":
            raise ApiError(f"the re-render {job['id']} {job['status']}: {job.get('message')}")
    return job


def cmd_fix(ctx: Ctx) -> int:
    a = ctx.args
    job = fix_job(ctx, find_job(ctx.api, a.job), a.rounds, a.min_overrun, a.dry_run)
    if a.dry_run:
        return 0
    _checks, failures, _version = check_job(ctx, job, 5)
    return 1 if failures else 0


# -- line: one line, looked at or changed ------------------------------------------


def line_info(version: dict, index: int) -> dict:
    seg = next((s for s in version["script"]["segments"] if s["index"] == index), None)
    cue = next((c for c in version.get("cues") or [] if c["index"] == index), None)
    if seg is None or cue is None:
        raise ApiError(f"no line {index} in this dub")
    provenance: dict = next((p for p in version.get("line_provenance") or []
                       if p["index"] == index), {})
    renders = {r["role"]: r for r in cue["audio"].get("renders") or []}
    timed = renders.get("phrased") or renders.get("fitted")
    selected = cue["audio"].get("selection") or {}
    take: dict = next((t for t in cue["audio"].get("takes") or []
                 if t["take_id"] == selected.get("take_id")), {})
    verification = cue.get("verification") or {}
    return {
        "index": index, "speaker": seg["speaker"], "start": seg["start"], "end": seg["end"],
        "slot": round(seg["end"] - seg["start"], 2), "source": provenance.get("source", ""),
        "text": seg["text"], "spoken": provenance.get("tts_text", ""),
        "heard": verification.get("heard", ""), "verification": verification.get("state"),
        "timed_seconds": round(timed["duration"], 2) if timed and timed.get("duration") else None,
        "takes": len(cue["audio"].get("takes") or []), "take": selected.get("take_id"),
        "voice": take.get("profile"), "voice_similarity": (take.get("checks") or {}).get(
            "voice_similarity"),
        "findings": sorted({f["code"] for f in cue.get("findings") or []
                            if f.get("disposition") in (None, "open")}),
    }


def cmd_line(ctx: Ctx) -> int:
    a = ctx.args
    job = find_job(ctx.api, a.job)
    version, _counters = load_version(job)
    info = line_info(version, a.index)
    if a.clip:
        ctx.api.download(f"/api/jobs/{job['id']}/clips/{a.index}", Path(a.clip))
        ctx.say(f"saved line {a.index}'s take to {a.clip}")
    edit: dict = {}
    if a.text:
        edit.update(text=a.text, regenerate=True)
    if a.voice:
        edit.update(voice=a.voice, regenerate=True)
    if a.delivery:
        edit.update(delivery=a.delivery, regenerate=True)
    if a.retake:
        edit["regenerate"] = True
    if not edit:
        ctx.result(info, [f"line {info['index']}  {info['speaker']}  "
                          f"{info['start']:.2f}-{info['end']:.2f}s (slot {info['slot']}s, "
                          f"timed {info['timed_seconds']}s)",
                          f"  source:  {info['source']}",
                          f"  text:    {info['text']}",
                          f"  heard:   {info['heard']}  [{info['verification']}]",
                          f"  voice:   {info['voice']}  similarity {info['voice_similarity']}"
                          f"  ({info['takes']} takes)",
                          f"  open:    {', '.join(info['findings']) or '-'}"])
        return 0
    new = revoice(ctx, job, [{"index": a.index, "cue": next(
        (c.get("cue_id") for c in version["cues"] if c["index"] == a.index), None), **edit}])
    ctx.say(f"queued {new['id']} to re-render line {a.index}")
    if a.wait:
        new = wait(ctx, new["id"])
        if new["status"] == "done":
            fresh, _ = load_version(new)
            info = line_info(fresh, a.index)
    ctx.result({"job": new["id"], "status": new["status"], "line": info},
               f"{new['status']}: line {a.index} now says {info['text']!r}"
               + (f", heard {info['heard']!r}" if a.wait else ""))
    return 0 if new["status"] in ("done", "queued", "running") else 1


def add_parsers(sub, common) -> None:
    q = sub.add_parser("queue", parents=[common], help="queue a dub on the running server")
    q.add_argument("file")
    q.add_argument("--to", required=True, help="target locale, e.g. es-419")
    q.add_argument("--from", dest="source", default="auto")
    q.add_argument("--kind", choices=["full", "tease", "audition", "analyze"], default="full")
    q.add_argument("--version", default=None, help="name for the saved version")
    q.add_argument("--title", default=None)
    q.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="setting for this job only, e.g. quality.asr=all (repeatable)")
    q.add_argument("--force", action="store_true")
    q.add_argument("--wait", action="store_true", help="follow the job until it ends")

    j = sub.add_parser("jobs", parents=[common], help="list jobs, or follow one")
    j.add_argument("--watch", default=None, metavar="JOB_ID")
    j.add_argument("--limit", type=int, default=15)

    r = sub.add_parser("report", parents=[common],
                       help="objective checks of a finished dub (PASS/WARN/FAIL)")
    r.add_argument("job", help="job id (a prefix is enough)")
    r.add_argument("--worst", type=int, default=10, help="list the N longest overruns")

    f = sub.add_parser("fix", parents=[common],
                       help="re-voice the lines report flags (misread, drifted, rambling)")
    f.add_argument("job")
    f.add_argument("--rounds", type=int, default=1, help="repeat while lines stay flagged")
    f.add_argument("--min-overrun", type=float, default=1.0,
                   help="re-voice a take this many seconds past its slot")
    f.add_argument("--dry-run", action="store_true", help="only list the lines")

    ln = sub.add_parser("line", parents=[common], help="show one line, or change and re-voice it")
    ln.add_argument("job")
    ln.add_argument("index", type=int)
    ln.add_argument("--text", default=None, help="new words for the line")
    ln.add_argument("--voice", default=None, help="voice profile id for the line")
    ln.add_argument("--delivery", default=None, help="how to say it (engines that take it)")
    ln.add_argument("--retake", action="store_true", help="re-voice with the same words")
    ln.add_argument("--clip", default=None, metavar="FILE", help="save the line's take")
    ln.add_argument("--wait", action="store_true")


COMMANDS = {"queue": cmd_queue, "jobs": cmd_jobs, "report": cmd_report, "fix": cmd_fix,
            "line": cmd_line}

