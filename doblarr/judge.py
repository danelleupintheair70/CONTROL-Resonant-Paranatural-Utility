"""The recommendation packet and the judge that chooses from it.

The packet is everything relevant about one line, bounded: scoped narrative
context, the character's profile preferences, the original line's and the
fitted take's measurements, identity and alignment uncertainty, background
activity, the candidates (each described by the same fields) and the hard
limits and user locks. What did not fit is listed, not silently dropped.

Judges are interchangeable adapters with one contract — pick a candidate id,
optionally adjust strength within its bounds, cite evidence, say whether a
person should review, or abstain:

- ``retrieval`` — the retrieval ranking alone (doblarr.retrieval). It is a rule,
  and its records say so; it is never reported as a model decision.
- ``kev/<model>``, ``laya/<model>``, ``typesafe/<model>`` — Prompture typed
  decision drivers through the existing Oracle pattern (doblarr.decisions): a
  ``choice`` question whose options are the candidate ids. The raw confidence
  is stored as a raw score, not a calibrated probability.
- ``llm:<prompture model>`` — a structured JSON answer from a language model
  (doblarr.llm), validated against the schema and the candidate list.

Deterministic checks run before and after any model: a locked line is not
asked about; the answer must name a candidate in the packet; strength is
clamped to the template's declared range; nothing can request a new voice, a
speech generation, or evidence the packet did not contain. Provider failure,
an invalid answer, insufficient evidence or an exhausted budget fall back to the
recorded conservative choice (preserve, or retrieval when configured), and
the record says which fallback happened and why.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import retrieval
from .artifacts import digest

log = logging.getLogger("doblarr.judge")

PACKET = "recommendation-packet/1"
POLICY = "judge-policy/1"
PACKET_CHARS = 6000
INSTRUCTIONS = (
    "You choose how one dubbed line's loudness should move inside the line. You are given "
    "measurements of the original actor's line and of the generated take, scene context and "
    "a short list of candidate envelope templates, each with the same fields. Pick exactly "
    "one candidate id from the list, or abstain if the evidence does not support any. "
    "Prefer the preserve candidate when the take already moves like the original or when "
    "the evidence is weak or contradictory. An envelope only shapes volume: never try to "
    "fix wrong acting, wrong words or a wrong voice with it. Cite the evidence fields you "
    "relied on by name. Set needs_review when something conflicts. Return JSON only.")


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: str = Field(default="", max_length=80)     # a candidate template id or ""
    strength: float | None = Field(default=None, ge=0, le=1.5)
    abstain: bool = False
    needs_review: bool = False
    evidence: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(default="", max_length=400)


def _features_summary(found: dict | None) -> dict:
    if not found:
        return {"quality": "missing"}
    peaks = [p.get("position") for p in found.get("peaks") or []][:4]
    return {"quality": found.get("quality"), "duration": found.get("duration"),
            "active_seconds": found.get("active_seconds"), "range_db": found.get("range_db"),
            "pauses": len(found.get("pauses") or []), "peak_positions": peaks,
            "curve": [round(v, 1) for v in (found.get("curve") or [])][::2]}


def build_packet(*, line: dict, source: dict | None, take: dict | None, ranked: dict,
                 narrative: list[dict] | None = None, profile: dict | None = None,
                 identity: dict | None = None, alignment: dict | None = None,
                 background: dict | None = None, limits: dict | None = None,
                 lock: dict | None = None) -> dict:
    """One bounded packet. Every candidate carries the same comparison fields."""
    omitted = []
    candidates = []
    for c in ranked.get("candidates") or []:
        candidates.append({"id": c["template"]["id"], "version": c["template"]["version"],
                           "family": c["family"], "title": c["title"],
                           "score": c["score"], "components": c["components"],
                           "support": c["support"][:3], "conflicts": c["conflicts"][:2],
                           "proposed_strength": (c.get("params") or {}).get("strength"),
                           "shape": c["shape"][::4]})
    context = list(narrative or [])
    packet: dict = {
        "packet": PACKET,
        "line": {k: line.get(k) for k in ("cue", "text", "translated", "speaker_name", "mode",
                                          "band", "ending", "traits", "screen", "scene")},
        "original": _features_summary(source), "take": _features_summary(take),
        "identity": identity or {}, "alignment": alignment or {},
        "background": background or {}, "character": {
            "favored": [p.get("template") for p in ((profile or {}).get("templates") or {})
                        .get("favored") or []],
            "discouraged": [p.get("template") for p in ((profile or {}).get("templates")
                                                         or {}).get("discouraged") or []],
            "envelope_strength": ((profile or {}).get("dynamics") or {}).get(
                "envelope_strength"),
            "direction": ((profile or {}).get("delivery") or {}).get("direction")},
        "context": context, "candidates": candidates,
        "warnings": ranked.get("warnings") or [], "limits": limits or {},
        "lock": lock or None,
    }
    while len(json.dumps(packet, ensure_ascii=False, default=str)) > PACKET_CHARS and \
            packet["context"]:
        packet["context"] = packet["context"][:-1]
        omitted.append("context")
    if omitted:
        packet["omitted"] = {"context_claims": omitted.count("context")}
    packet["fingerprint"] = digest({k: v for k, v in packet.items() if k != "fingerprint"})[:16]
    return packet


def cited(evidence: str, packet: dict) -> bool:
    """Whether a cited piece of evidence is in the packet: a field path
    (``candidates[0].score``, ``take.range_db``) whose root is a packet field, or
    text quoted from it. Anything else is evidence the packet never offered."""
    import re

    root = re.match(r"\s*([A-Za-z_]+)", evidence or "")
    if root and root.group(1) in packet:
        return True
    quote = " ".join(str(evidence).split()).casefold().strip(" .")
    if len(quote) < 12:
        return False
    text = " ".join(json.dumps(packet, ensure_ascii=False, default=str).split()).casefold()
    return quote in text


def validate(choice: Choice, packet: dict) -> tuple[dict | None, str]:
    """A model's answer, checked against the packet; (decision, problem)."""
    ids = {c["id"]: c for c in packet["candidates"]}
    if choice.abstain:
        return {"abstain": True}, ""
    if choice.candidate not in ids:
        return None, f"answer names {choice.candidate!r}, not a candidate in the packet"
    unknown = [e for e in choice.evidence if not cited(e, packet)]
    if unknown:
        return None, f"answer cites evidence the packet does not contain: {unknown[0]}"
    return {"candidate": choice.candidate, "strength": choice.strength,
            "needs_review": choice.needs_review, "evidence": choice.evidence,
            "reason": choice.reason}, ""


class Judge:
    """Base adapter: subclasses implement `_ask(packet) -> Choice`."""

    engine = "retrieval"
    is_model = False

    def __init__(self, budget: int = 400):
        self.budget = budget
        self.calls = 0
        self.failures: list[str] = []

    def decide(self, packet: dict, ranked: dict, *, fallback: str = "retrieval") -> dict:
        """The decision record for one line (never raises for a model problem)."""
        if packet.get("lock"):
            return self._record(packet, "manual", {"candidate": packet["lock"]["template"],
                                                   "strength": packet["lock"].get("strength")},
                                "locked by hand: not asked")
        if not packet["candidates"]:
            return self._record(packet, "fallback", None, "no eligible candidate")
        if not self.is_model:
            choice = retrieval.retrieval_choice(ranked)
            return self._record(packet, "rule", {"candidate": choice["template"]["id"],
                                                 "strength": (choice.get("params") or {})
                                                 .get("strength")},
                                choice["reason"])
        if self.calls >= self.budget:
            return self._fallback(packet, ranked, fallback, "judge budget exhausted")
        try:
            self.calls += 1
            answer = self._ask(packet)
        except Exception as exc:  # noqa: BLE001 - any model problem: recorded fallback
            self.failures.append(str(exc)[:200])
            return self._fallback(packet, ranked, fallback, f"{self.engine} failed: {exc}")
        decision, problem = validate(answer, packet)
        if decision is None:
            self.failures.append(problem)
            return self._fallback(packet, ranked, fallback, f"invalid answer: {problem}")
        if decision.get("abstain"):
            return self._fallback(packet, ranked, "preserve",
                                  f"{self.engine} abstained: {answer.reason or 'no reason'}",
                                  state="abstained")
        return self._record(packet, "model", decision, decision.get("reason") or "",
                            raw=answer.model_dump())

    def _fallback(self, packet, ranked, fallback, reason, state="fallback") -> dict:
        decided: dict | None
        if fallback == "retrieval":
            choice = retrieval.retrieval_choice(ranked)
            decided = {"candidate": choice["template"]["id"],
                       "strength": (choice.get("params") or {}).get("strength")}
        else:
            preserve = next((c for c in packet["candidates"] if c["family"] == "preserve"),
                            None)
            decided = {"candidate": preserve["id"], "strength": None} if preserve else None
        return self._record(packet, state, decided, reason, fallback=fallback)

    def _record(self, packet, state, decided, reason, *, raw=None, fallback=None) -> dict:
        source = {"model": "model", "rule": "rule", "manual": "manual"}.get(state, "fallback")
        return {"policy": POLICY, "engine": self.engine, "state": state, "source": source,
                "decision": decided, "reason": reason, "packet": packet["fingerprint"],
                "raw": raw, "fallback": fallback,
                "raw_score_is_calibrated": False}

    def _ask(self, packet: dict) -> Choice:  # pragma: no cover - overridden
        raise NotImplementedError


class DecisionJudge(Judge):
    """A Prompture typed-decision driver (Kev, Laya, TypeSafe) via the Oracle."""

    is_model = True

    def __init__(self, model: str, budget: int = 400, oracle=None):
        super().__init__(budget)
        from .decisions import Oracle

        self.engine = model
        self.oracle = oracle or Oracle({"model": model, "enabled": True})

    def _ask(self, packet: dict) -> Choice:
        criteria = {c["id"]: f"{c['title']}: " + "; ".join(c["support"][:2] or [c["family"]])
                    for c in packet["candidates"]}
        criteria["abstain"] = "none of these fits the evidence"
        state = {k: packet[k] for k in ("line", "original", "take", "context", "warnings")}
        answers = self.oracle.ask("envelope", state, {"pick": {
            "type": "choice", "instructions": INSTRUCTIONS, "criteria": criteria}})
        if answers is None:
            raise RuntimeError(self.oracle.reason or "decision model unavailable")
        picked = answers["pick"]
        if picked.get("choice") == "abstain":
            return Choice(abstain=True, reason="the decision model chose abstain")
        return Choice(candidate=str(picked.get("choice") or ""),
                      reason=f"raw confidence {picked.get('confidence', 0):.2f} (uncalibrated)",
                      evidence=["candidates"])


class LLMJudge(Judge):
    """A structured JSON answer from a language model through Prompture."""

    is_model = True

    def __init__(self, client, budget: int = 400):
        super().__init__(budget)
        self.client = client
        self.engine = f"llm:{client.model}"

    def _ask(self, packet: dict) -> Choice:
        payload = {k: v for k, v in packet.items() if k != "fingerprint"}
        return self.client.ask(Choice, INSTRUCTIONS, payload, max_tokens=800)


def build(spec: str, *, budget: int = 400, endpoint: str | None = None,
          request_budget=None, guard=None) -> Judge:
    """A judge from its configured name (``adaptive.judge``)."""
    spec = (spec or "retrieval").strip()
    if spec in ("retrieval", "off", ""):
        return Judge(budget)
    if spec.startswith("llm:"):
        from . import llm

        return LLMJudge(llm.Client(spec[4:], endpoint=endpoint, budget=request_budget,
                                   budget_kind="judge", guard=guard), budget)
    if spec.split("/", 1)[0] in ("kev", "laya", "typesafe"):
        return DecisionJudge(spec, budget)
    raise ValueError(f"unknown judge {spec!r}: use retrieval, kev/<model>, laya/<model>, "
                     "typesafe/<model> or llm:<prompture model>")


Mode = Literal["off", "suggest", "apply"]
