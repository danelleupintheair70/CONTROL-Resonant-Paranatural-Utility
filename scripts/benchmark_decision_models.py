"""Decision-model follow-up to the vision bake-off.

Takes the descriptions a vision model already wrote (a results.json from
benchmark_vision_models.py) and asks a Prompture typed-decision model (Kev,
Laya) to classify them into fixed categories through the production Oracle
(doblarr.decisions). The vision model's own enum answers are withheld from the
state, so agreement means the decision model reached the same bucket from the
words alone. Agreement is with another model, not with ground truth: a person
judges who is right from report.md. Engineering comparison on one episode.
"""

import argparse
import json
import statistics
import time
from pathlib import Path

from doblarr.decisions import Oracle, choice, noul

AGE_CRITERIA = {
    "child": "a young child, roughly under 12",
    "teen": "an adolescent, roughly 13 to 19",
    "young_adult": "a young adult, roughly 20 to 30",
    "adult": "a grown adult, roughly 30 to 60",
    "elderly": "an old person, roughly over 60",
    "uncertain": "the description gives no basis to tell the age",
}
SCORE_WEIGHT = {"type": "score",
                "instructions": "How heavy and deep should this character's voice be?",
                "criteria": ["Light and high", "Medium", "Deep and heavy"]}
TEXT_LANG = {"japanese": "Japanese (kanji, kana)", "chinese": "Chinese",
             "english": "English or other Latin script", "none": "no visible text"}

AGE_Q = choice("What is the apparent age of the character described?", AGE_CRITERIA)
ELDERLY_Q = noul("Is the character described elderly?")


def character_questions() -> dict:
    return {"age": AGE_Q, "elderly": ELDERLY_Q, "voice_weight": SCORE_WEIGHT}


def scene_cases(scenes: list[dict]) -> list[dict]:
    cases = []
    for call in scenes:
        if not call.get("ok"):
            continue
        out = call["output"]
        for i, person in enumerate(out.get("characters") or []):
            cases.append({
                "id": f"{call['image']}#{i}", "kind": "sighting",
                "state": {"description": person.get("description", ""),
                          "distinguishing_features": person.get("distinguishing_features", ""),
                          "setting": out.get("setting", "")},
                "questions": character_questions(),
                "reference": {"age": person.get("apparent_age")},
            })
        texts = out.get("visible_text") or []
        cases.append({
            "id": f"{call['image']}#text", "kind": "text_language",
            "state": {"summary": out.get("summary", ""),
                      "visible_text": [t.get("text", "") for t in texts]},
            "questions": {"language": choice(
                "Which writing system is the visible text in?", TEXT_LANG)},
            "reference": {"language": (texts[0].get("language", "").lower() if texts
                                       else "none")},
        })
    return cases


def appearance_cases(appearances: list[dict]) -> list[dict]:
    cases = []
    for call in appearances:
        if not call.get("ok"):
            continue
        out = call["output"]
        state = {k: out.get(k, "") for k in
                 ("build", "hair", "distinguishing_features", "demeanor", "vocal_impression")}
        cases.append({"id": call["image"], "kind": "appearance", "state": state,
                      "questions": character_questions(),
                      "reference": {"age": out.get("apparent_age")}})
    return cases


def run(model: str, cases: list[dict], device: str | None) -> dict:
    oracle = Oracle({"model": model, "enabled": True}, device=device)
    rows = []
    for case in cases:
        started = time.perf_counter()
        answers = oracle.ask("vision_followup", case["state"], case["questions"])
        rows.append({**{k: case[k] for k in ("id", "kind", "state", "reference")},
                     "seconds": round(time.perf_counter() - started, 3),
                     "answers": answers})
        if answers is None:
            print(f"  {case['id']}: unavailable ({oracle.reason})", flush=True)
            break
        print(f"  {case['id']}: {_brief(answers)}", flush=True)
    return {"model": model, "rows": rows, "summary": summarize(rows),
            "unavailable": oracle.reason if oracle.state == "unavailable" else ""}


def _brief(answers: dict) -> str:
    parts = []
    for qid, a in answers.items():
        value = a.get("choice", a.get("yes", a.get("value")))
        if isinstance(value, float):
            value = f"{value:.2f}"
        parts.append(f"{qid}={value} ({a['confidence']:.2f})")
    return ", ".join(parts)


def summarize(rows: list[dict]) -> dict:
    answered = [r for r in rows if r["answers"]]
    out = {"cases": len(rows), "answered": len(answered)}
    if answered:
        out["mean_seconds"] = round(statistics.mean(r["seconds"] for r in answered[1:] or answered), 3)
        out["first_call_seconds"] = answered[0]["seconds"]
    for qid in ("age", "language"):
        pairs = [(r["answers"][qid]["choice"], r["reference"][qid]) for r in answered
                 if qid in r["answers"] and r["reference"].get(qid)]
        if pairs:
            same = sum(_same(got, ref) for got, ref in pairs)
            out[f"{qid}_agreement"] = f"{same}/{len(pairs)}"
    return out


def _same(got: str, ref: str) -> bool:
    return got == ref or (got != "none" and got in ref)


def write_report(result: dict, source: str, path: Path) -> None:
    s = result["summary"]
    lines = [f"# Decision follow-up: {result['model']}", "",
             f"descriptions from `{source}`", "",
             "Reference = the vision model's own enum answer (withheld from the state). "
             "Agreement is between models, not with ground truth.", "",
             "```json", json.dumps(s, indent=2), "```", ""]
    if result["unavailable"]:
        lines += [f"**Unavailable:** {result['unavailable']}", ""]
    lines += ["| case | reference | decision answers | s |", "|---|---|---|---|"]
    for r in result["rows"]:
        ref = ", ".join(f"{k}={v}" for k, v in r["reference"].items())
        got = _brief(r["answers"]) if r["answers"] else "—"
        lines.append(f"| {r['id']} | {ref} | {got} | {r['seconds']} |")
    lines += ["", "## States", ""]
    for r in result["rows"]:
        lines += [f"**{r['id']}**: " + json.dumps(r["state"], ensure_ascii=False), ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptions", type=Path, required=True,
                        help="results.json from benchmark_vision_models.py")
    parser.add_argument("--model", action="append", required=True,
                        help="decision model, e.g. kev/kev-4b or laya/router (repeatable)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default=None, help="Laya device, e.g. cpu or cuda")
    args = parser.parse_args()

    source = json.loads(args.descriptions.read_text(encoding="utf-8"))
    cases = scene_cases(source["scenes"]) + appearance_cases(source["appearances"])
    print(f"{len(cases)} cases from {source['model']}")
    board = []
    for model in args.model:
        print(f"== {model}")
        result = run(model, cases, args.device)
        slug = model.replace("/", "_").replace(":", "_")
        out_dir = args.out / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        write_report(result, str(args.descriptions), out_dir / "report.md")
        board.append({"model": model, **result["summary"]})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "leaderboard.json").write_text(json.dumps(board, indent=2), encoding="utf-8")
    print(json.dumps(board, indent=2))


if __name__ == "__main__":
    main()
