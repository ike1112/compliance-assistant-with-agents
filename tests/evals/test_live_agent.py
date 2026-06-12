"""Unit tests for the deployed-agent conformance harness.

These stay offline: they validate subset loading, config refusal, and
deterministic report scoring from recorded sample responses. The live
Bedrock-agent invocation path is operator-run post-deploy.
"""
import pytest

from compliance_assistant.citations import render_citations
from tests.evals.harness import live_agent as LA
from tests.evals.harness.goldset import index_by_id, load_positives


def test_live_subset_is_fixed_and_deterministic():
    subset = LA.load_live_subset()
    assert subset["positive_ids"] == (
        "pos-001", "pos-004", "pos-008", "pos-012", "pos-015",
        "pos-022", "pos-030", "pos-038",
    )
    assert subset["negative_ids"] == ("neg-001", "neg-004")


def test_require_live_agent_config_refuses_when_ids_cannot_be_resolved():
    with pytest.raises(RuntimeError, match="deployed Bedrock agent ids"):
        LA.require_live_agent_config(
            env={"AWS_REGION": "us-east-1"},
            resolve_ids=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )


def test_build_report_scores_sample_responses():
    positive = next(p for p in load_positives() if p.id == "pos-001")
    by_passage = index_by_id()
    gold = by_passage[positive.gold_passage_ids[0]]
    trace = {
        "citations": [{
            "retrievedReferences": [{
                "content": {"text": gold.text},
                "location": {"s3Location": {"uri": f"s3://corpus/{gold.doc_id}.txt"}},
            }]
        }]
    }
    positive_answer = gold.text + "\n\n" + render_citations(trace)
    records = [
        {
            "kind": "positive",
            "item_id": "pos-001",
            "question": positive.question,
            "system_answer": positive_answer,
            "trace": trace,
            "retrieved_context": [{"chunk_id": f"{gold.doc_id}#1", "text": gold.text}],
            "judge_raw_response": (
                '{"faithfulness": 1.0, "hallucination": 0.0, "rationale": "grounded"}'
            ),
        },
        {
            "kind": "negative",
            "item_id": "neg-001",
            "question": "Out of corpus question",
            "system_answer": "Not found in knowledge base",
            "trace": {"citations": []},
            "retrieved_context": [],
        },
    ]

    report = LA.build_live_report(records)

    assert report["summary"]["positive_count"] == 1
    assert report["summary"]["negative_count"] == 1
    assert report["summary"]["pass"] is True
    assert report["summary"]["citation_correctness"] == 1.0
    assert report["summary"]["not_found_honesty"] == 1.0
    assert report["summary"]["requirement_coverage"] == 1.0
