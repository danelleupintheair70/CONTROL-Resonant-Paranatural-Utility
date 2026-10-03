"""Character-trait bake-off: are the characteristics right, and how fast.

Each case is one person in one frame, with a hand-checked reference answer per
question (labels.json, a list of accepted answers per question). Two methods
answer the same typed questions:

- direct: the vision model answers every question from the image in one call.
- describe -> decide: the vision model writes a plain description of the
  person, then a typed-decision model (Kev, Laya) answers every question from
  that text alone.

Stages run separately so only one model holds the GPU at a time, and `score`
can be rerun after the labels are corrected without asking any model again:

  vision  --model ollama/qwen3-vl:8b      (direct answers + descriptions)
  decide  --model kev/kev-4b              (answers from every saved description)
  score                                   (accuracy and time against labels.json)

Engineering comparison on one episode's frames, not a dubbing-quality result.
"""

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, create_model

QUESTIONS: dict[str, tuple[str, dict[str, str]]] = {
    "gender": ("What is the person's apparent gender?", {
        "male": "looks male", "female": "looks female",
        "unclear": "cannot be told from what is visible"}),
    "age": ("What is the person's apparent age range?", {
        "child": "a child, roughly under 13", "teen": "a teenager, roughly 13 to 19",
        "young_adult": "a young adult, roughly 20 to 35",
        "middle_aged": "middle-aged, roughly 35 to 60", "elderly": "old, roughly over 60"}),
    "hair_color": ("What colour is the person's hair?", {
        "black": "black", "dark_brown": "dark brown", "light_brown": "light brown",
        "blonde": "blonde or yellow", "white_silver": "white, silver or gray",
        "red": "red or orange", "other": "another colour", "not_visible": "hair not visible"}),
    "hair_length": ("How long is the person's hair?", {
        "short": "short, above the ears or cropped", "medium": "medium, around the jaw or neck",
        "long": "long, past the shoulders", "not_visible": "hair not visible"}),
    "expression": ("What is the person's facial expression?", {
        "calm_neutral": "calm or neutral", "smiling": "smiling or content",
        "surprised_scared": "surprised, startled or scared", "sad": "sad or upset",
        "angry": "angry", "stern_sullen": "stern, sullen or glaring",
        "asleep_unconscious": "eyes closed, asleep or unconscious",
        "not_visible": "the face is not visible or too small"}),
    "clothing": ("What kind of clothing is the person wearing?", {
        "traditional_japanese": "kimono, yukata or other traditional Japanese clothes",
        "western": "shirt, jacket, trousers or other western clothes",
        "armor_uniform": "armor or a uniform", "unclear": "clothing not visible enough to tell"}),
    "eyes_visible": ("Are the person's eyes visible and open?", {
        "yes": "at least one open eye is visible",
        "no": "eyes hidden by hair, closed, turned away or too small"}),
}

DIRECT_INSTRUCTIONS = """\
You are reading one still from an animated episode for a dubbing knowledge
base. Answer each question about the target person only, from what is visible
in the image. Never guess names. Pick the closest option for each question."""

DESCRIBE_INSTRUCTIONS = """\
You are reading one still from an animated episode for a dubbing knowledge
base. Describe the target person only, from what is visible in the image:
apparent gender, apparent age, hair colour and length, facial expression,
whether the eyes are visible and open, and clothing. Plain sentences, no
names, no backstory. Say so when something cannot be seen."""

Traits = create_model("Traits", **{
    qid: (Literal[tuple(options)], Field(description=text))
    for qid, (text, options) in QUESTIONS.items()})


class Description(BaseModel):
    description: str


def slug(model: str) -> str:
    return model.replace("/", "_").replace(":", "_")


def timed(fn):
    started = time.perf_counter()
    try:
        return fn(), None, round(time.perf_counter() - started, 2)
    except Exception as exc:  # noqa: BLE001 - recorded as a failed call
        took = round(time.perf_counter() - started, 2)
        return None, f"{type(exc).__name__}: {str(exc)[:300]}", took


def stage_vision(model: str, labels: dict, root: Path, out: Path, think: bool | None) -> None:
    from doblarr.llm import Client

    client = Client(model, timeout=300, think=think)
    rows = []
    for case in labels["cases"]:
        image = [str(root / case["image"])]
        payload = {"target_person": case["target"]}
        direct, d_err, d_s = timed(lambda payload=payload, image=image: client.ask(
            Traits, DIRECT_INSTRUCTIONS, payload, max_tokens=600, images=image).model_dump())
        desc, s_err, s_s = timed(lambda payload=payload, image=image: client.ask(
            Description, DESCRIBE_INSTRUCTIONS, payload, max_tokens=600, images=image).description)
        print(f"  {case['id']}: direct {d_s}s{' FAIL' if d_err else ''}, "
              f"describe {s_s}s{' FAIL' if s_err else ''}", flush=True)
        rows.append({"id": case["id"], "direct": direct, "direct_error": d_err,
                     "direct_seconds": d_s, "description": desc,
                     "describe_error": s_err, "describe_seconds": s_s})
    path = out / f"vision__{slug(model)}.json"
    path.write_text(json.dumps({"model": model, "rows": rows}, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def stage_decide(model: str, out: Path, device: str | None) -> None:
    from doblarr.decisions import Oracle, choice

    questions = {qid: choice(text, options) for qid, (text, options) in QUESTIONS.items()}
    for vision_file in sorted(out.glob("vision__*.json")):
        source = json.loads(vision_file.read_text(encoding="utf-8"))
        oracle = Oracle({"model": model, "enabled": True}, device=device)
        rows = []
        print(f"  descriptions from {source['model']}", flush=True)
        for row in source["rows"]:
            if not row["description"]:
                rows.append({"id": row["id"], "answers": None, "seconds": 0})
                continue
            answers, err, secs = timed(lambda oracle=oracle, row=row: oracle.ask(
                "character_traits", {"person": row["description"]}, questions))
            rows.append({"id": row["id"], "answers": answers, "seconds": secs,
                         "error": err or (None if answers else oracle.reason)})
        name = f"decide__{slug(model)}__from__{vision_file.stem.removeprefix('vision__')}.json"
        (out / name).write_text(json.dumps(
            {"model": model, "vision_model": source["model"], "rows": rows},
            indent=2, ensure_ascii=False), encoding="utf-8")


def score_method(label: str, picks: dict, seconds: dict, labels: dict,
                 confidence: dict | None = None) -> dict:
    """Accuracy of {case: {question: answer}} against the accepted answers."""
    per_q = {qid: [0, 0] for qid in QUESTIONS}
    sure = [0, 0]
    misses = []
    for case in labels["cases"]:
        got = picks.get(case["id"]) or {}
        for qid, accepted in case["answers"].items():
            per_q[qid][1] += 1
            ok = got.get(qid) in accepted
            per_q[qid][0] += ok
            if confidence and confidence.get(case["id"], {}).get(qid, 0) >= 0.8:
                sure[0] += ok
                sure[1] += 1
            if not ok:
                misses.append(f"{case['id']}.{qid}: {got.get(qid) or 'no answer'} "
                              f"(expected {'/'.join(accepted)})")
    right = sum(v[0] for v in per_q.values())
    total = sum(v[1] for v in per_q.values())
    out = {"method": label, "accuracy": round(right / total, 3), "correct": f"{right}/{total}",
           "seconds_per_character":
               round(statistics.mean(seconds.values()), 2) if seconds else None,
           "per_question": {q: f"{r}/{t}" for q, (r, t) in per_q.items()},
           "misses": misses}
    if confidence:
        out["confident_answers_correct"] = f"{sure[0]}/{sure[1]} at confidence >= 0.8"
    return out


def stage_score(labels: dict, out: Path) -> list[dict]:
    board = []
    vision = {f.stem.removeprefix("vision__"): json.loads(f.read_text(encoding="utf-8"))
              for f in sorted(out.glob("vision__*.json"))}
    for data in vision.values():
        rows = {r["id"]: r for r in data["rows"]}
        board.append(score_method(
            f"direct: {data['model']}", {k: r["direct"] for k, r in rows.items()},
            {k: r["direct_seconds"] for k, r in rows.items()}, labels))
    for f in sorted(out.glob("decide__*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        source = vision[f.stem.split("__from__")[1]]
        describe_s = {r["id"]: r["describe_seconds"] for r in source["rows"]}
        picks, conf, secs = {}, {}, {}
        for r in data["rows"]:
            answers = r["answers"] or {}
            picks[r["id"]] = {q: a.get("choice") for q, a in answers.items()}
            conf[r["id"]] = {q: a.get("confidence", 0) for q, a in answers.items()}
            secs[r["id"]] = round(describe_s.get(r["id"], 0) + r["seconds"], 2)
        board.append(score_method(
            f"describe -> decide: {data['vision_model']} -> {data['model']}",
            picks, secs, labels, conf))
    board.sort(key=lambda b: -b["accuracy"])
    (out / "scores.json").write_text(json.dumps(board, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    write_report(board, out / "report.md")
    return board


def write_report(board: list[dict], path: Path) -> None:
    lines = ["# Character-trait bake-off", "",
             "Scored against labels.json (hand-checked reference answers).", "",
             "| method | correct | accuracy | s per character | confident & correct |",
             "|---|---|---|---|---|"]
    for b in board:
        lines.append(f"| {b['method']} | {b['correct']} | {b['accuracy'] * 100:.0f}% | "
                     f"{b['seconds_per_character']} | {b.get('confident_answers_correct', '—')} |")
    lines += ["", "## Per question", "",
              "| method | " + " | ".join(QUESTIONS) + " |",
              "|---|" + "---|" * len(QUESTIONS)]
    for b in board:
        cells = " | ".join(b["per_question"][q] for q in QUESTIONS)
        lines.append(f"| {b['method']} | {cells} |")
    for b in board:
        lines += ["", f"## Misses: {b['method']}", ""] + [f"- {m}" for m in b["misses"]]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["vision", "decide", "score"])
    parser.add_argument("--labels", type=Path, required=True,
                        help="labels.json; image paths are relative to its folder")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--think", choices=["default", "off", "on"], default="off")
    parser.add_argument("--device", default=None, help="Laya device, e.g. cpu or cuda")
    args = parser.parse_args()

    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    if args.stage == "vision":
        think = {"default": None, "off": False, "on": True}[args.think]
        for model in args.model:
            print(f"== {model}", flush=True)
            stage_vision(model, labels, args.labels.parent, args.out, think)
    elif args.stage == "decide":
        for model in args.model:
            print(f"== {model}", flush=True)
            stage_decide(model, args.out, args.device)
    board = stage_score(labels, args.out)
    for b in board:
        print(f"{b['accuracy'] * 100:5.1f}%  {b['seconds_per_character']}s  {b['method']}")


if __name__ == "__main__":
    main()
