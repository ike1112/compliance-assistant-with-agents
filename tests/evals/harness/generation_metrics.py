"""Generation metrics.

The gate's binding generation criterion is DETERMINISTIC: recomputed
lexical groundedness of the answer against the recomputed retrieved
context, plus a deterministic citation-correctness check that
structurally depends on compliance_assistant.citations.render_citations
(the mutation-leg pure module). The recorded LLM judge
faithfulness/hallucination are corroborating EVIDENCE only — offline
cannot attest that an LLM produced them, so they may not, by themselves,
pass the gate (see docs/evals.md "residual trust"). A high judge score
with low deterministic groundedness is treated as forged → FAIL.
"""
from __future__ import annotations

import json
import re

from compliance_assistant.citations import render_citations

_SENT_RE = re.compile(r"[^.!?]+[.!?]")
_WORD_RE = re.compile(r"[a-z0-9]+")
_GROUNDED_JACCARD = 0.30
_GROUNDED_ITEM_FLOOR = 0.40
_FAITHFUL_FORGERY_GATE = 0.95
_NO_SOURCES = render_citations({})  # the deterministic placeholder block


def sources_block(answer: str) -> str:
    i = answer.find("## Sources")
    return answer[i:].strip() if i != -1 else ""


def prose(answer: str) -> str:
    i = answer.find("## Sources")
    return (answer[:i] if i != -1 else answer).strip()


def _tok(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _trace_has_refs(trace) -> bool:
    if not isinstance(trace, dict):
        return False
    for c in trace.get("citations") or []:
        if isinstance(c, dict) and (c.get("retrievedReferences") or []):
            return True
    return False


def citation_correct(fx: dict, gold_passages: list) -> bool:
    """Deterministic. gold_passages: list of goldset.Passage for the
    positive. A silent render failure on a trace that HAS references is
    raised loudly (never scored as a quiet 0.0)."""
    expected = render_citations(fx["trace"]).strip()
    if _trace_has_refs(fx["trace"]) and expected == _NO_SOURCES.strip():
        raise AssertionError(
            "render_citations returned the no-sources placeholder for a "
            "trace that has references — refusing to score a silent 0.0")
    block = sources_block(fx["system_answer"])
    if not block or block != expected:
        return False
    if expected == _NO_SOURCES.strip():
        return False
    ctx = " ".join(c["text"] for c in fx["retrieved_context"])
    # At least one cited source doc must be a gold passage's doc AND that
    # gold passage's exact text must be in the (recomputed-bound) context.
    for p in gold_passages:
        if f"s3://corpus/{p.doc_id}.txt" in expected and p.text in ctx:
            return True
    return False


def groundedness(answer: str, context_text: str) -> float:
    sents = [s.strip() for s in _SENT_RE.findall(prose(answer)) if s.strip()]
    if not sents:
        return 1.0 if prose(answer) == "" else 0.0
    ctx = _tok(context_text)
    grounded = 0
    for s in sents:
        st = _tok(s)
        if not st:
            continue
        if len(st & ctx) / len(st) >= _GROUNDED_JACCARD:
            grounded += 1
    return grounded / len(sents)


def parse_judge(raw: str) -> tuple[float, float]:
    matches = re.findall(r"\{[^{}]*\}", raw, re.DOTALL)
    if not matches:
        raise AssertionError("judge_raw_response has no JSON object")
    obj = json.loads(matches[-1])
    f = float(obj["faithfulness"])
    h = float(obj["hallucination"])
    assert 0.0 <= f <= 1.0 and 0.0 <= h <= 1.0, "judge score out of [0,1]"
    return f, h


def score_positive(fx: dict, gold_passages: list) -> dict:
    f, h = parse_judge(fx["judge_raw_response"])
    ctx = " ".join(c["text"] for c in fx["retrieved_context"])
    g = groundedness(fx["system_answer"], ctx)
    forged = f >= _FAITHFUL_FORGERY_GATE and g < _GROUNDED_ITEM_FLOOR
    return {
        "faithfulness": f,           # corroborating evidence only
        "hallucination": h,          # corroborating evidence only
        "groundedness": g,           # DETERMINISTIC binding signal
        "citation_correct": citation_correct(fx, gold_passages),
        "forged": forged,
    }


def aggregate_generation(scored: list[dict]) -> dict:
    n = len(scored)
    if n == 0:
        return {"faithfulness": 0.0, "hallucination": 1.0,
                "groundedness": 0.0, "citation_correctness": 0.0,
                "any_forged": True}
    return {
        "faithfulness": sum(s["faithfulness"] for s in scored) / n,
        "hallucination": sum(s["hallucination"] for s in scored) / n,
        "groundedness": sum(s["groundedness"] for s in scored) / n,
        "citation_correctness": sum(
            1 for s in scored if s["citation_correct"]) / n,
        "any_forged": any(s["forged"] for s in scored),
    }
