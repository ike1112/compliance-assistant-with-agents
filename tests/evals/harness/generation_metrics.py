"""Generation metrics.

citation-correctness is DETERMINISTIC and structurally depends on
compliance_assistant.citations.render_citations (the mutation-leg pure
module): the recorded answer's "## Sources" block must equal
render_citations(recorded_trace) exactly AND a rendered reference must
overlap a gold passage — so a tampered Sources block or a wrong citation
fails, and mutating render_citations breaks this metric.

faithfulness / hallucination come from the recorded raw judge response,
parsed per the committed rubric, and are cross-checked by a deterministic
groundedness lower-bound (anti-forgery).
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


def sources_block(answer: str) -> str:
    i = answer.find("## Sources")
    return answer[i:].strip() if i != -1 else ""


def prose(answer: str) -> str:
    i = answer.find("## Sources")
    return (answer[:i] if i != -1 else answer).strip()


def _tok(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def citation_correct(fx: dict, gold_texts: list[str]) -> bool:
    expected = render_citations(fx["trace"])
    block = sources_block(fx["system_answer"])
    if not block or block != expected.strip():
        return False
    if expected.strip() == render_citations({}).strip():
        return False  # "no grounded sources" is not a correct citation
    ctx = " ".join(c["text"] for c in fx["retrieved_context"])
    # At least one cited snippet must overlap a gold passage AND the
    # retrieved context (the answer cites a right, retrieved source).
    for gt in gold_texts:
        if gt in ctx and any(
            w in expected for w in gt.split()[:8] if len(w) > 4
        ):
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


def score_positive(fx: dict, gold_texts: list[str]) -> dict:
    f, h = parse_judge(fx["judge_raw_response"])
    ctx = " ".join(c["text"] for c in fx["retrieved_context"])
    g = groundedness(fx["system_answer"], ctx)
    forged = f >= _FAITHFUL_FORGERY_GATE and g < _GROUNDED_ITEM_FLOOR
    return {
        "faithfulness": f,
        "hallucination": h,
        "groundedness": g,
        "citation_correct": citation_correct(fx, gold_texts),
        "forged": forged,
    }


def aggregate_generation(scored: list[dict]) -> dict:
    n = len(scored)
    if n == 0:
        return {"faithfulness": 0.0, "hallucination": 1.0,
                "citation_correctness": 0.0, "any_forged": True}
    return {
        "faithfulness": sum(s["faithfulness"] for s in scored) / n,
        "hallucination": sum(s["hallucination"] for s in scored) / n,
        "citation_correctness": sum(
            1 for s in scored if s["citation_correct"]) / n,
        "any_forged": any(s["forged"] for s in scored),
    }
