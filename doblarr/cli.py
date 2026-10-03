"""Doblarr command-line interface.

    doblarr check                         # ping the voicebox service
    doblarr dub MOVIE --to es --from ko [--subs FILE] [--dry-run]
    doblarr cast series                   # series ids and titles
    doblarr cast search SERIES_ID [--query TITLE]
    doblarr cast link SERIES_ID URL [--season N]
    doblarr cast show SERIES_ID [--season N] [--episode N]
    doblarr cast import SERIES_ID [--roles MAIN,SUPPORTING | --names A,B]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .clients.speech import SpeechError, build_speech_client
from .config import Config
from .logging_setup import setup_logging
from .models import DubJob
from .pipeline import run_job


def _cmd_check(args: argparse.Namespace, config: Config) -> int:
    speech = build_speech_client(config)
    try:
        health = speech.health()
    except SpeechError as exc:
        print(f"{speech.service} NOT reachable: {exc}")
        return 1
    print(f"{speech.service} OK at {speech.base_url}: {health}")
    return 0


def _cmd_serve(args: argparse.Namespace, config: Config) -> int:
    import uvicorn

    from .server import create_app

    host = args.host or config.get("web", {}).get("host", "127.0.0.1")
    port = args.port or config.get("web", {}).get("port", 6363)
    print(f"Doblarr serving on http://{host}:{port}  (UI + /api/library)")
    # log_config=None: logging_setup already configured uvicorn's loggers.
    uvicorn.run(create_app(config), host=host, port=int(port), log_config=None)
    return 0


def _cmd_dub(args: argparse.Namespace, config: Config) -> int:
    src = Path(args.input)
    if not src.exists():
        print(f"input not found: {src}")
        return 1
    job = DubJob(
        input_file=src,
        source_lang=args.source,
        target_lang=args.to,
        subtitle_file=Path(args.subs) if args.subs else None,
        kind=args.kind,
    )
    # --dry-run forces a plan; otherwise dub.dry_run from config decides.
    dry_run = args.dry_run if args.dry_run is not None else config["dub"].get("dry_run", True)
    from .artifacts import media_work, read_json
    from .knowledge import snapshot
    from .knowledge.packs import ensure_starter_pack
    from .languages import resolve_target_locale
    from .store import Database
    from .telemetry import write_json

    db = Database(config.db_path)
    try:
        ensure_starter_pack(db, config.get("knowledge", {}))
        job.target_locale = resolve_target_locale(config.as_dict(), job.target_lang)
        pin_file = media_work(config.work_dir, job) / job.target_locale / "knowledge.json"
        job.knowledge_snapshot = read_json(pin_file) if pin_file.is_file() else snapshot(db)
        write_json(pin_file, job.knowledge_snapshot)
        run_job(job, config, dry_run=dry_run, db=db)
    finally:
        db.close()
    return 0


def _cmd_cast(args: argparse.Namespace, config: Config) -> int:
    from . import published_cast
    from .store import Database
    from .studio import records

    db = Database(config.db_path)
    try:
        if args.action == "series":
            for series in records.list_latest(db, "series"):
                if series.get("linked_to"):
                    continue
                linked = len(published_cast.links(db, series["id"]))
                print(f"{series['id']}  {published_cast.series_title(db, series['id']) or '?'}"
                      + (f"  [{linked} cast link(s)]" if linked else ""))
            return 0
        if args.action == "search":
            query = args.query or published_cast.series_title(db, args.series)
            if not query:
                print("no title known for this series; pass --query")
                return 1
            print(f"searching AniList for {query!r} (sends the title to anilist.co)")
            kind = "movie" if args.series.startswith("movie:") else "show"
            for hit in published_cast.search(query, kind=kind):
                episodes = hit["episodes"] and f"{hit['episodes']} eps"
                facts = ", ".join(str(f) for f in (hit["format"], hit["year"], episodes) if f)
                print(f"  {hit['url']}  {hit['title']} ({facts})")
            return 0
        if args.action == "link":
            cast = published_cast.link(db, args.series, args.url, season=args.season)
            print(f"linked {cast['title']}: {len(cast['characters'])} characters"
                  + ("" if cast["complete"] else " (more exist; raise the limit)"))
            return 0
        if args.action == "show":
            cast = published_cast.get(db, args.series, season=args.season)
            if cast is None:
                print("no published cast linked; run `doblarr cast search` then `link`")
                return 1
            print(f"{cast['title']} <{cast['url']}>")
            for c in published_cast.candidates(cast, episode=args.episode):
                voices = ", ".join(v["name"] for v in c["voice_actors"]) or "-"
                print(f"  {c['name']:<24} {c['role']:<11} {c.get('gender') or '-':<7} "
                      f"voice: {voices}  ({c['why']})")
            return 0
        if args.action == "import":
            names = [n.strip() for n in args.names.split(",")] if args.names else None
            roles = [r.strip() for r in args.roles.split(",")]
            done = published_cast.import_characters(db, args.series, season=args.season,
                                                    roles=roles, names=names)
            print(f"created {len(done['created'])}: {', '.join(done['created']) or '-'}")
            print(f"matched {len(done['matched'])}: {', '.join(done['matched']) or '-'}")
            for item in done["ambiguous"]:
                print(f"skipped {item['name']}: the name also fits {', '.join(item['also'])}")
            return 0
    except (KeyError, ValueError, RuntimeError) as exc:
        print(f"cast: {exc}")
        return 1
    finally:
        db.close()
    return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="doblarr", description="AI dubbing for your library")
    p.add_argument("--version", action="version", version=f"doblarr {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-c", "--config", default=None, help="path to config.yaml")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="check the speech service is reachable")

    s = sub.add_parser("serve", help="run the web UI + API server")
    s.add_argument("--host", default=None)
    s.add_argument("--port", default=None, type=int)

    d = sub.add_parser("dub", help="dub a video into a target language")
    d.add_argument("input", help="path to the video file")
    d.add_argument("--to", required=True, help="target language code, e.g. es")
    d.add_argument("--from", dest="source", default="auto",
                   help="source language code, e.g. ko (default: auto)")
    d.add_argument("--subs", default=None, help="subtitle file for text + timing")
    d.add_argument("--kind", choices=["full", "tease", "audition", "analyze"], default="full",
                   help="full video, opening teaser, representative audio audition, or "
                        "a line-by-line analysis without dubbing")
    d.add_argument("--dry-run", action="store_true", default=None,
                   help="print the plan without running heavy stages "
                        "(overrides dub.dry_run in config)")

    c = sub.add_parser("cast", help="link a series to its published cast (AniList)")
    actions = c.add_subparsers(dest="action", required=True)
    actions.add_parser("series", help="list series ids and titles")
    cs = actions.add_parser("search", help="find catalogue entries for a series")
    cs.add_argument("series")
    cs.add_argument("--query", default=None, help="title to search (default: the series title)")
    cl = actions.add_parser("link", help="link a series (or one season) to an entry")
    cl.add_argument("series")
    cl.add_argument("url", help="an AniList title URL from `cast search`")
    cl.add_argument("--season", type=int, default=None)
    cw = actions.add_parser("show", help="show the linked cast, optionally for one episode")
    cw.add_argument("series")
    cw.add_argument("--season", type=int, default=None)
    cw.add_argument("--episode", type=int, default=None)
    ci = actions.add_parser("import", help="create series characters from the linked cast")
    ci.add_argument("series")
    ci.add_argument("--season", type=int, default=None)
    ci.add_argument("--roles", default="MAIN", help="comma list of MAIN, SUPPORTING, BACKGROUND")
    ci.add_argument("--names", default=None, help="comma list of names (overrides --roles)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.load(args.config)
    setup_logging(config, verbose=args.verbose, uvicorn=args.command == "serve")
    if args.command == "check":
        return _cmd_check(args, config)
    if args.command == "serve":
        return _cmd_serve(args, config)
    if args.command == "dub":
        return _cmd_dub(args, config)
    if args.command == "cast":
        return _cmd_cast(args, config)
    return 2


if __name__ == "__main__":
    sys.exit(main())
