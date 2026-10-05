"""Read and change settings from the terminal.

    doblarr settings                       # the sections
    doblarr settings get translate         # every value in a section
    doblarr settings get translate.model   # one value, with its choices and default
    doblarr settings set translate.provider=prompture translate.model=ollama/gemma3:12b

A value is checked against the settings schema before anything is saved, so a
typo in a key or a choice is refused instead of written. With the server
running the change goes through it, so the web UI and the next job see it at
once; without it, config.yaml is updated directly.
"""

from __future__ import annotations

import copy
import difflib
import typing
from typing import Any

from pydantic import BaseModel, ValidationError

from ..config import Config, _deep_merge
from ..config_schema import ConfigModel
from .base import ApiError, Ctx, pairs, value


def flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(data, dict) or not data:
        return {prefix: data} if prefix else {}
    out: dict[str, Any] = {}
    for key, item in data.items():
        out.update(flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    return out


def _model(annotation: Any) -> type[BaseModel] | None:
    return annotation if isinstance(annotation, type) and issubclass(annotation,
                                                                     BaseModel) else None


def field_for(key: str) -> tuple[Any, Any] | None:
    """The (annotation, default) a dotted key has in the schema, or None.

    A key inside a free-form map (a glossary, per-line edits) is that map's.
    """
    model: type[BaseModel] = ConfigModel
    parts = key.split(".")
    for position, part in enumerate(parts):
        field = model.model_fields.get(part)
        if field is None:
            return None
        nested = _model(field.annotation)
        if nested is None:
            if position == len(parts) - 1:
                return field.annotation, field.default
            origin = typing.get_origin(field.annotation) or field.annotation
            return (field.annotation, None) if origin is dict else None
        if position == len(parts) - 1:
            return field.annotation, None
        model = nested
    return None


def known_keys() -> list[str]:
    keys: list[str] = []

    def walk(model: type[BaseModel], prefix: str) -> None:
        for name, field in model.model_fields.items():
            nested = _model(field.annotation)
            if nested is not None:
                walk(nested, f"{prefix}{name}.")
            else:
                keys.append(f"{prefix}{name}")
    walk(ConfigModel, "")
    return keys


def choices(annotation: Any) -> list[Any]:
    """The values a Literal setting allows (inside Optional too)."""
    if typing.get_origin(annotation) is typing.Literal:
        return list(typing.get_args(annotation))
    found: list[Any] = []
    for arg in typing.get_args(annotation):
        found += choices(arg)
    return found


def nest(dotted: dict[str, Any]) -> dict:
    out: dict = {}
    for key, item in dotted.items():
        node = out
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = item
    return out


def check(config: Config, changes: dict[str, Any]) -> None:
    """Refuse unknown keys and values the schema rejects, naming each one."""
    problems = []
    for key in changes:
        if field_for(key) is None:
            close = difflib.get_close_matches(key, known_keys(), n=3, cutoff=0.6)
            problems.append(f"unknown setting {key}"
                            + (f" (did you mean {', '.join(close)}?)" if close else ""))
    if problems:
        raise ApiError("; ".join(problems))
    merged = _deep_merge(copy.deepcopy(config.as_dict()), nest(changes))
    try:
        ConfigModel.model_validate(merged)
    except ValidationError as exc:
        raise ApiError("; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                                 for e in exc.errors())) from None


def apply(ctx: Ctx, changes: dict[str, Any]) -> str:
    """Save checked changes, through the server when it runs."""
    check(ctx.config, changes)
    if ctx.api.alive():
        saved = ctx.api.post("/api/config", nest(changes))
        return str(saved.get("saved_to", "config.yaml"))
    ctx.config.apply_and_save(nest(changes))
    return str(ctx.config.path)


def cmd_settings(ctx: Ctx) -> int:
    a = ctx.args
    data = ctx.config.as_dict(redact_secrets=True)
    if a.action is None:
        sections = sorted(ConfigModel.model_fields)
        ctx.result(sections, "sections: " + ", ".join(sections)
                   + "\n`doblarr settings get SECTION` lists one")
        return 0
    if a.action == "get":
        flat = flatten(data)
        wanted = a.keys or [""]
        rows: dict[str, Any] = {}
        for key in wanted:
            rows.update({k: v for k, v in flat.items()
                         if not key or k == key or k.startswith(key + ".")})
        if len(wanted) == 1 and wanted[0] in rows and len(rows) == 1:
            annotation, default = field_for(wanted[0]) or (None, None)
            allowed = choices(annotation)
            ctx.result({"key": wanted[0], "value": rows[wanted[0]], "default": default,
                        "choices": allowed},
                       [f"{wanted[0]} = {rows[wanted[0]]!r}",
                        f"  default {default!r}" + (f"; one of {', '.join(map(str, allowed))}"
                                                    if allowed else "")])
            return 0
        if not rows:
            raise ApiError(f"no setting matches {', '.join(wanted)}")
        ctx.result(rows, [f"{k} = {v!r}" for k, v in sorted(rows.items())])
        return 0
    changes = {key: value(raw) for key, raw in pairs(a.keys, "settings set")}
    if not changes:
        raise ApiError("nothing to set; use KEY=VALUE")
    where = apply(ctx, changes)
    ctx.result({"saved_to": where, "changes": changes},
               [f"{k} = {v!r}" for k, v in changes.items()] + [f"saved to {where}"])
    return 0


def add_parsers(sub, common) -> None:
    s = sub.add_parser("settings", parents=[common], help="read or change settings")
    s.add_argument("action", nargs="?", choices=["get", "set"])
    s.add_argument("keys", nargs="*", help="get: KEY or SECTION; set: KEY=VALUE ...")


COMMANDS = {"settings": cmd_settings}
