"""Deterministic citation-correctness (on render_citations) + judge
parsing + the anti-forgery groundedness cross-check.
"""
import pytest

from compliance_assistant.citations import render_citations
from tests.evals.harness import generation_metrics as G


def _fx(answer, refs, judge):
    trace = {"citations": [{"retrievedReferences": [
        {"content": {"text": t},
         "location": {"s3Location": {"uri": u}}} for u, t in refs]}]}
    return {
        "system_answer": answer,
        "trace": trace,
        "retrieved_context": [{"chunk_id": "d#1", "text": t} for _, t in refs],
        "judge_raw_response": judge,
    }


def test_parse_judge_takes_last_json():
    assert G.parse_judge('noise {"x":1} {"faithfulness":0.9,'
                          '"hallucination":0.1}') == (0.9, 0.1)


def test_parse_judge_rejects_out_of_range():
    with pytest.raises(AssertionError):
        G.parse_judge('{"faithfulness":1.4,"hallucination":0}')


def test_citation_correct_true_when_block_matches_and_overlaps_gold():
    gold = "PCI DSS v4.0 Requirement 3.5.1 stored pan unreadable"
    refs = [("s3://corpus/req-03.txt", gold)]
    block = render_citations(_fx("", refs, "")["trace"])
    fx = _fx("Answer text.\n\n" + block, refs, '{"faithfulness":1,"hallucination":0}')
    assert G.citation_correct(fx, [gold]) is True


def test_citation_incorrect_when_block_tampered():
    gold = "stored pan must be unreadable everywhere"
    refs = [("s3://corpus/req-03.txt", gold)]
    fx = _fx("Answer.\n\n## Sources\n\n1. `s3://evil` — fake", refs,
             '{"faithfulness":1,"hallucination":0}')
    assert G.citation_correct(fx, [gold]) is False


def test_citation_incorrect_when_no_sources_block():
    gold = "xय"
    fx = _fx("Answer with no sources", [("s3://x", "y")], "{}")
    assert G.citation_correct(fx, [gold]) is False


def test_groundedness_high_when_answer_in_context():
    ctx = "the audit log retention period is twelve months minimum"
    assert G.groundedness("Audit log retention period is twelve months.",
                          ctx) == 1.0


def test_groundedness_low_when_answer_unrelated():
    assert G.groundedness("Bananas are yellow fruit grown in tropics.",
                          "PCI DSS encryption key management rotation") < 0.4


def test_score_positive_flags_forgery():
    # judge claims perfect faithfulness but answer is ungrounded -> forged
    refs = [("s3://x", "key management rotation cryptography")]
    fx = _fx("Completely unrelated banana statement here today.",
             refs, '{"faithfulness":1.0,"hallucination":0.0}')
    s = G.score_positive(fx, ["key management rotation cryptography"])
    assert s["forged"] is True


def test_aggregate_generation_means():
    scored = [
        {"faithfulness": 1.0, "hallucination": 0.0,
         "citation_correct": True, "forged": False},
        {"faithfulness": 0.9, "hallucination": 0.1,
         "citation_correct": False, "forged": False},
    ]
    agg = G.aggregate_generation(scored)
    assert agg["faithfulness"] == pytest.approx(0.95)
    assert agg["hallucination"] == pytest.approx(0.05)
    assert agg["citation_correctness"] == 0.5
    assert agg["any_forged"] is False
