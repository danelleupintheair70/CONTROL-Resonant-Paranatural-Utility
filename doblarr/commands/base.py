"""What every command shares: the server API, job lookups and output.

Commands that change a dub talk to the running server (`doblarr serve`), so a
job queued from a terminal is the same job the web UI shows. Commands that
only read research or settings work without it.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config

FINISHED = ("done", "failed", "cancelled")


class ApiError(RuntimeError):
    """A command could not do what was asked; the message says why."""


class Api:
    def __init__(self, config: Config, base: str | None = None):
        web = config.get("web", {}) or {}
        host = web.get("host", "127.0.0.1")
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        self.base = (base or f"http://{host}:{web.get('port', 6363)}").rstrip("/")

    def _open(self, method: str, route: str, body=None, query=None, timeout: float = 120):
        url = self.base + route + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise ApiError(f"{method} {route}: {exc.code} {detail}") from None
        except urllib.error.URLError as exc:
            raise ApiError(f"Doblarr server not reachable at {self.base} ({exc.reason}); "
                           "start it with `doblarr serve`") from None

    def _call(self, method: str, route: str, body=None, query=None):
        with self._open(method, route, body, query) as resp:
            return json.load(resp)

    def get(self, route: str, **query):
        return self._call("GET", route, query=query or None)

    def post(self, route: str, body):
        return self._call("POST", route, body)

    def put(self, route: str, body):
        return self._call("PUT", route, body)

    def delete(self, route: str):
        return self._call("DELETE", route)

    def download(self, route: str, dest: Path) -> Path:
        with self._open("GET", route) as resp:
            dest.write_bytes(resp.read())
        return dest

    def alive(self) -> bool:
        try:
            self.get("/api/status")
        except ApiError:
            return False
        return True


@dataclass
class Ctx:
    """One command's inputs: its arguments, the configuration and the API."""

    args: Any
    config: Config
    api_client: Api | None = None
    printed: list = field(default_factory=list)

    @property
    def api(self) -> Api:
        if self.api_client is None:
            self.api_client = Api(self.config)
        return self.api_client

    @property
    def json(self) -> bool:
        return bool(getattr(self.args, "json", False))

    def say(self, text: str = "") -> None:
        """A line for a person; silent under --json, where only the result prints."""
        if not self.json:
            print(text, flush=True)

    def result(self, data: Any, text: str | list[str] | None = None) -> None:
        """The command's answer: JSON under --json, otherwise the text."""
        if self.json:
            print(json.dumps(data, ensure_ascii=False, indent=1, default=str))
        elif text is not None:
            print(text if isinstance(text, str) else "\n".join(text), flush=True)


def pairs(values: list[str] | None, what: str) -> list[tuple[str, str]]:
    out = []
    for value in values or []:
        if "=" not in value:
            raise ApiError(f"{what} must look like LEFT=RIGHT, got {value!r}")
        left, right = value.split("=", 1)
        out.append((left.strip(), right.strip()))
    return out


def value(text: str) -> Any:
    """A command-line value as YAML would read it: numbers, true/false, lists."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        lowered = text.strip().lower()
        if lowered in ("true", "yes", "on"):
            return True
        if lowered in ("false", "no", "off"):
            return False
        if lowered in ("null", "none"):
            return None
        return text


def find_job(api: Api, job_id: str) -> dict:
    jobs = api.get("/api/jobs")["jobs"]
    found = [j for j in jobs if j["id"] == job_id or j["id"].startswith(job_id)]
    if not found:
        raise ApiError(f"no job {job_id}")
    return found[0]


def wait(ctx: Ctx, job_id: str, every: float = 15) -> dict:
    """Follow a job until it ends, printing each change of stage."""
    last = None
    while True:
        job = find_job(ctx.api, job_id)
        state = (job["status"], job["stage"], job["progress"], (job.get("message") or "")[:100])
        if state != last:
            ctx.say(f"{time.strftime('%H:%M:%S')}  {job['status']:9s} {job['stage'] or '':12s} "
                    f"{job['progress'] or 0:3d}%  {state[3]}")
            last = state
        if job["status"] in FINISHED:
            return job
        time.sleep(every)


def load_version(job: dict) -> tuple[dict, dict]:
    """A finished job's saved version and its run counters."""
    if job["status"] != "done" or not job.get("version_file"):
        raise ApiError(f"job {job['id']} is {job['status']}; it has no finished dub yet")
    version = json.loads(Path(job["version_file"]).read_text(encoding="utf-8"))
    report = Path(job["report_file"]) if job.get("report_file") else None
    counters = (json.loads(report.read_text(encoding="utf-8")).get("counters", {})
                if report and report.is_file() else {})
    return version, counters


def default_target(config: Config) -> str:
    dub = config.get("dub", {}) or {}
    targets = (config.get("general", {}) or {}).get("target_languages") or ["es"]
    return str(dub.get("target_locale") or targets[0])


def video_files(paths: list[str]) -> list[str]:
    """Files as given; a folder stands for the videos inside it, in order."""
    out: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            out.extend(str(p) for p in sorted(path.iterdir())
                       if p.suffix.lower() in (".mkv", ".mp4", ".m4v", ".avi", ".mov"))
        else:
            out.append(raw)
    return out
