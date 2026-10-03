"""Vision-model bake-off for the appearance/scene-reading stage.

Sends the same still frames and face crops to each candidate model through the
production path (doblarr.llm.Client -> Prompture -> provider), with the two
schemas that stage would use. Records JSON validity and latency per call; a
person judges description quality from the generated report.md. These are
engineering comparisons on one episode's frames, not dubbing-quality results.
"""

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from doblarr.llm import Client, InvalidReply, ModelUnavailable

AGES = ("child", "teen", "young_adult", "adult", "elderly", "uncertain")

SCENE_INSTRUCTIONS = """\
You are reading one still frame from an animated episode for a dubbing
knowledge base. Describe only what is visible in the image. Never invent
names, events, or backstory. If no person is visible, return an empty
characters list. Transcribe any visible text exactly, with its language.
Be specific about apparent age, clothing and distinguishing features."""

APPEARANCE_INSTRUCTIONS = """\
You are reading one face crop of an animated character for a dubbing
voice-casting knowledge base. Describe only what is visible in the image.
The goal is a vocal target: apparent age and presence matter most.
Never invent identity or backstory."""


class CharacterSighting(BaseModel):
    description: str = Field(description="who/what is visible: position, clothing, features")
    apparent_age: Literal[*AGES] = "uncertain"
    distinguishing_features: str = ""


class VisibleText(BaseModel):
    text: str
    language: str


class SceneReading(BaseModel):
    characters: list[CharacterSighting] = Field(default_factory=list)
    setting: str = ""
    mood: str = ""
    visible_text: list[VisibleText] = Field(default_factory=list)
    summary: str = Field(description="one sentence: what this frame shows")


class AppearanceReading(BaseModel):
    apparent_age: Literal[*AGES] = "uncertain"
    build: str = ""
    hair: str = ""
    distinguishing_features: str = ""
    demeanor: str = ""
    vocal_impression: str = Field(
        description="the voice that would fit this face: pitch, weight, texture")
    confidence: Literal["low", "medium", "high"] = "low"


def read_image(client: Client, schema, instructions: str, image: Path,
               max_tokens: int) -> dict:
    started = time.perf_counter()
    try:
        reply = client.ask(schema, instructions, {"task": "describe this image"},
                           max_tokens=max_tokens, images=[str(image)])
        return {"image": image.name, "ok": True,
                "seconds": round(time.perf_counter() - started, 2),
                "output": reply.model_dump()}
    except (InvalidReply, ModelUnavailable) as exc:
        return {"image": image.name, "ok": False,
                "seconds": round(time.perf_counter() - started, 2),
                "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def run_model(model: str, scenes: list[Path], faces: list[Path], out_dir: Path,
              max_tokens: int, think: bool | None) -> dict:
    client = Client(model, timeout=300, think=think)
    results = {"model": model, "scenes": [], "appearances": []}
    for frame in scenes:
        print(f"  scene {frame.name} ...", flush=True)
        results["scenes"].append(
            read_image(client, SceneReading, SCENE_INSTRUCTIONS, frame, max_tokens))
    for crop in faces:
        print(f"  face  {crop.name} ...", flush=True)
        results["appearances"].append(
            read_image(client, AppearanceReading, APPEARANCE_INSTRUCTIONS, crop, max_tokens))
    results["driver"] = client.describe()

    calls = results["scenes"] + results["appearances"]
    ok = [c for c in calls if c["ok"]]
    results["summary"] = {
        "calls": len(calls),
        "valid": len(ok),
        "validity": round(len(ok) / len(calls), 3) if calls else 0,
        "mean_seconds": round(statistics.mean(c["seconds"] for c in calls), 2) if calls else 0,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(results, out_dir / "report.md")
    return results


def write_report(results: dict, path: Path) -> None:
    lines = [f"# Vision bake-off: {results['model']}", ""]
    s = results["summary"]
    lines.append(f"valid {s['valid']}/{s['calls']} "
                 f"({s['validity'] * 100:.0f}%) · mean {s['mean_seconds']}s per call")
    for section, key in (("Scene readings", "scenes"), ("Appearance readings", "appearances")):
        lines += ["", f"## {section}", ""]
        for call in results[key]:
            lines.append(f"### {call['image']} ({call['seconds']}s)")
            if call["ok"]:
                lines.append("```json")
                lines.append(json.dumps(call["output"], indent=2, ensure_ascii=False))
                lines.append("```")
            else:
                lines.append(f"FAILED: {call['error']}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True,
                        help="Prompture model string, e.g. ollama/qwen3-vl:8b (repeatable)")
    parser.add_argument("--scenes-dir", type=Path, required=True)
    parser.add_argument("--faces-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True,
                        help="base output dir; one subfolder per model")
    parser.add_argument("--scenes", type=int, default=0, help="cap scene frames (0 = all)")
    parser.add_argument("--faces", type=int, default=0, help="cap face crops (0 = all)")
    parser.add_argument("--max-tokens", type=int, default=1536)
    parser.add_argument("--think", choices=["default", "off", "on"], default="off",
                        help="'off' matches how the appearance stage would read a still")
    args = parser.parse_args()
    think = {"default": None, "off": False, "on": True}[args.think]

    scenes = sorted(args.scenes_dir.glob("*.jpg"))[: args.scenes or None]
    faces = sorted(args.faces_dir.glob("*.jpg"))[: args.faces or None]
    print(f"{len(scenes)} scene frames, {len(faces)} face crops")

    board = []
    for model in args.model:
        slug = model.replace("/", "_").replace(":", "_")
        print(f"== {model} ==", flush=True)
        board.append(run_model(model, scenes, faces, args.out / slug, args.max_tokens,
                               think)["summary"] | {"model": model})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "leaderboard.json").write_text(
        json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(board, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
