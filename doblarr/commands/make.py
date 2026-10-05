"""Dub a film or episodes from nothing, every step in order.

    doblarr make FILE_OR_FOLDER... --to es-419 [--skip lookup,fix] [--set key=value]

The steps, each also a command of its own:

  doctor    every service and tool a run needs           (doblarr doctor)
  analyze   separate, transcribe, group voices, dub tracks (doblarr analyze)
  lookup    catalogue ids, published cast, characters      (doblarr lookup)
  voices    the voice groups, named or not                 (doblarr voices)
  dub       translate along the file's own dub, voice, mix (doblarr queue)
  report    PASS/WARN/FAIL on timing, casting, speech      (doblarr report)
  fix       re-voice the lines the report flags            (doblarr fix)

A step that has nothing to do is skipped (a file analysed before is not
analysed again; a title looked up once is not looked up again), so running
`make` again only does the work that is missing.
"""

from __future__ import annotations

from pathlib import Path

from .base import ApiError, Ctx, video_files, wait
from .doctor import checks as doctor_checks
from .episodes import analyze, summary, summary_text
from .jobs import check_job, fix_job, lines_to_fix, load_version, queue_job
from .research import lookup

STEPS = ("doctor", "analyze", "lookup", "voices", "dub", "report", "fix")


def steps(skip: str | None, only: str | None) -> list[str]:
    chosen = [s.strip() for s in (only or "").split(",") if s.strip()] or list(STEPS)
    skipped = {s.strip() for s in (skip or "").split(",") if s.strip()}
    unknown = (set(chosen) | skipped) - set(STEPS)
    if unknown:
        raise ApiError(f"unknown step(s) {', '.join(sorted(unknown))}; "
                       f"the steps are {', '.join(STEPS)}")
    return [s for s in STEPS if s in chosen and s not in skipped]


def heading(ctx: Ctx, text: str) -> None:
    ctx.say(f"\n== {text}")


def make_one(ctx: Ctx, file: str, plan: list[str], target: str, looked_up: set) -> dict:
    a = ctx.args
    row: dict = {"file": file, "steps": {}}
    name = Path(file).stem
    data: dict = {}
    if "analyze" in plan or "lookup" in plan or "voices" in plan:
        heading(ctx, f"{name}: analyze")
        data = analyze(ctx, file, to=target, source=a.source)
        info = summary(data)
        row["series"] = info["series"]
        dubs = [t for t in info["dub_tracks"] if t["lang"] == target.split("-")[0]]
        row["steps"]["analyze"] = {"lines": info["lines"], "groups": len(info["groups"]),
                                   "published_dub": [t["title"] for t in dubs
                                                     if t["state"] == "verified"]}
        ctx.say(f"{info['lines']} lines, {len(info['groups'])} voice groups; "
                + (f"published {target} dub found: "
                   + ", ".join(str(t['title']) for t in dubs if t["state"] == "verified")
                   if any(t["state"] == "verified" for t in dubs)
                   else f"no published {target} dub in the file"))
    if "lookup" in plan and row.get("series") and row["series"] not in looked_up:
        heading(ctx, f"{name}: lookup {row['series']}")
        try:
            found = lookup(ctx, row["series"])
            row["steps"]["lookup"] = {"sources": found.get("sources"),
                                      "created": len(found["created"]),
                                      "matched": len(found["matched"])}
            ctx.say(f"cast from {', '.join(found.get('sources') or []) or 'nowhere'}; "
                    f"{len(found['created'])} characters created, "
                    f"{len(found['matched'])} matched")
        except Exception as exc:  # noqa: BLE001 - research is help, never a blocker
            row["steps"]["lookup"] = {"error": str(exc)[:200]}
            ctx.say(f"lookup failed ({exc}); dubbing without it")
        looked_up.add(row["series"])
        data = analyze(ctx, file, to=target, source=a.source)  # names may have changed
    if "voices" in plan and data:
        heading(ctx, f"{name}: voices")
        info = summary(data)
        row["steps"]["voices"] = {"named": sum(1 for g in info["groups"] if g["name"]),
                                  "unnamed_lines": info["unnamed_lines"]}
        for line in summary_text(info, 0):
            ctx.say(line)
        if info["unnamed_lines"]:
            ctx.say(f"{info['unnamed_lines']} lines are in unnamed groups and borrow a voice; "
                    f"name them with `doblarr voices \"{file}\" --name SPEAKER_NN=Name`")
    job = None
    if "dub" in plan:
        heading(ctx, f"{name}: dub")
        job = queue_job(ctx, file, to=target, source=a.source, version=a.version,
                        title=f"Dub · {name} · {target}", settings=a.set)
        job = wait(ctx, job["id"])
        row["job"] = job["id"]
        row["steps"]["dub"] = {"status": job["status"], "output": job.get("output_file")}
        if job["status"] != "done":
            raise ApiError(f"the dub {job['status']}: {job.get('message') or ''}")
    elif a.job:
        from .base import find_job
        job = find_job(ctx.api, a.job)
    if job is not None and "fix" in plan:
        version, _ = load_version(job)
        flagged = lines_to_fix(version)
        if flagged:
            heading(ctx, f"{name}: fix {len(flagged)} line(s)")
            job = fix_job(ctx, job, rounds=a.rounds)
            row["job"] = job["id"]
            row["steps"]["fix"] = {"lines": len(flagged), "job": job["id"]}
    if job is not None and "report" in plan:
        heading(ctx, f"{name}: report")
        checks, failures, _version = check_job(ctx, job, 5, show=False)
        row["steps"]["report"] = {"failures": failures,
                                  "warnings": sum(c["level"] == "WARN" for c in checks)}
        row["output"] = job.get("output_file")
    return row


def cmd_make(ctx: Ctx) -> int:
    a = ctx.args
    plan = steps(a.skip, a.only)
    target = a.to
    files = video_files(a.files)
    if not files:
        raise ApiError("no video files given")
    if "doctor" in plan:
        heading(ctx, "doctor")
        rows = doctor_checks(ctx)
        for r in rows:
            ctx.say(f"  {r['level']:4s}  {r['check']:<14} {r['text']}")
        if any(r["level"] == "FAIL" for r in rows) and not a.anyway:
            raise ApiError("doctor found a problem that would stop the run; fix it, or "
                           "pass --anyway")
    results: list[dict] = []
    looked_up: set[str] = set()
    for file in files:
        try:
            results.append(make_one(ctx, file, plan, target, looked_up))
        except ApiError as exc:
            results.append({"file": file, "error": str(exc)})
            ctx.say(f"{Path(file).stem}: {exc}")
            if not a.keep_going:
                break
    summary_rows = []
    for r in results:
        report = r.get("steps", {}).get("report") or {}
        state = ("error: " + r["error"]) if r.get("error") else (
            f"{report.get('failures', 0)} fail, {report.get('warnings', 0)} warn"
            if report else "done")
        summary_rows.append(f"  {Path(r['file']).stem}: {state}"
                            + (f"\n    {r['output']}" if r.get("output") else ""))
    ctx.result(results, ["", "== summary", *summary_rows])
    return 1 if any(r.get("error") or (r.get("steps", {}).get("report") or {}).get("failures")
                    for r in results) else 0


def add_parsers(sub, common) -> None:
    m = sub.add_parser("make", parents=[common],
                       help="dub files from nothing: doctor, analyze, lookup, voices, dub, "
                            "fix, report")
    m.add_argument("files", nargs="+", help="video files, or folders of them (a season)")
    m.add_argument("--to", required=True, help="target locale, e.g. es-419")
    m.add_argument("--from", dest="source", default="auto")
    m.add_argument("--version", default=None, help="name for the saved versions")
    m.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="setting for these dubs only (repeatable)")
    m.add_argument("--skip", default=None, help=f"steps to skip, e.g. lookup,fix "
                                                f"({', '.join(STEPS)})")
    m.add_argument("--only", default=None, help="run only these steps")
    m.add_argument("--job", default=None, help="without the dub step: fix and report this job")
    m.add_argument("--rounds", type=int, default=1, help="fix rounds")
    m.add_argument("--anyway", action="store_true", help="continue past a doctor FAIL")
    m.add_argument("--keep-going", action="store_true",
                   help="with several files, go on after one fails")


COMMANDS = {"make": cmd_make}
