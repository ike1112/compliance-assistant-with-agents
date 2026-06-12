"""Post-deploy conformance checks against the deployed Bedrock agent.

This path complements the offline BM25 gate. It reuses a fixed gold-set
subset, invokes the deployed agent with trace enabled, records raw
answers plus citations/retrieved context, and scores the same decision
metrics that transfer cleanly to the live system.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from compliance_assistant.agent_ids import resolve_agent_ids
from compliance_assistant.citations import render_citations
from tests.evals.harness import fixtures_io as FX
from tests.evals.harness import generation_metrics as GM
from tests.evals.harness import recorder
from tests.evals.harness import task_metrics as TM
from tests.evals.harness.goldset import (
    index_by_id,
    load_negatives,
    load_positives,
)

LIVE_SUBSET = Path(__file__).resolve().parents[1] / "live_conformance_subset.json"
DEFAULT_REPORT_PATH = Path(__file__).resolve().parents[1] / "live_report.json"
_PASS_BARS = {
    "groundedness": 0.95,
    "citation_correctness": 0.95,
    "faithfulness": 0.95,
    "not_found_honesty": 1.0,
    "requirement_coverage": 0.90,
}


def load_live_subset() -> dict[str, tuple[str, ...]]:
    raw = json.loads(LIVE_SUBSET.read_text(encoding="utf-8"))
    positives = tuple(raw["positive_ids"])
    negatives = tuple(raw["negative_ids"])
    pos_ids = {p.id for p in load_positives()}
    neg_ids = {n.id for n in load_negatives()}
    assert positives and negatives, "live conformance subset must include both kinds"
    assert len(set(positives)) == len(positives), "duplicate positive live ids"
    assert len(set(negatives)) == len(negatives), "duplicate negative live ids"
    for item_id in positives:
        assert item_id in pos_ids, f"unknown positive live id {item_id}"
    for item_id in negatives:
        assert item_id in neg_ids, f"unknown negative live id {item_id}"
    return {"positive_ids": positives, "negative_ids": negatives}


def require_live_agent_config(*, env: dict[str, str] | None = None,
                              resolve_ids=resolve_agent_ids) -> dict[str, str]:
    env = env or os.environ
    region = (
        env.get("AWS_REGION")
        or env.get("AWS_REGION_NAME")
        or env.get("AWS_DEFAULT_REGION")
    )
    if not region:
        raise RuntimeError(
            "AWS region is required for live conformance "
            "(set AWS_REGION, AWS_REGION_NAME, or AWS_DEFAULT_REGION)."
        )
    try:
        agent_id, alias_id = resolve_ids()
    except Exception as exc:
        raise RuntimeError(
            "Live conformance requires deployed Bedrock agent ids "
            "from SSM or deliberate env fallback."
        ) from exc
    return {"region": region, "agent_id": agent_id, "alias_id": alias_id}


def _retrieved_context(trace: dict) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for citation in trace.get("citations", []) or []:
        for ref in citation.get("retrievedReferences", []) or []:
            content = ((ref.get("content") or {}).get("text") or "").strip()
            uri = (((ref.get("location") or {}).get("s3Location") or {}).get("uri")
                   or "unknown-source")
            key = (uri, content)
            if key in seen:
                continue
            seen.add(key)
            out.append({"chunk_id": uri, "text": content})
    return out


def invoke_live_item(question: str, *, session_id: str | None = None,
                     client=None, config: dict[str, str] | None = None) -> dict:
    if client is None:
        import boto3

        client = boto3.client(
            "bedrock-agent-runtime",
            region_name=(config or require_live_agent_config())["region"],
        )
    config = config or require_live_agent_config()
    session_id = session_id or f"live-conformance-{uuid.uuid4()}"
    response = client.invoke_agent(
        agentId=config["agent_id"],
        agentAliasId=config["alias_id"],
        enableTrace=True,
        sessionId=session_id,
        inputText=question,
        streamingConfigurations={
            "applyGuardrailInterval": 20,
            "streamFinalResponse": False,
        },
    )
    answer = ""
    citations: list[dict] = []
    for event in response.get("completion"):
        if "chunk" in event:
            chunk = event["chunk"]
            answer += chunk["bytes"].decode()
            attr = chunk.get("attribution") or {}
            if attr.get("citations"):
                citations = attr["citations"]
        if "trace" in event and not citations:
            trace = (event["trace"] or {}).get("trace") or {}
            if trace.get("citation"):
                citations = [trace["citation"]]
    trace = {"citations": citations}
    return {
        "session_id": session_id,
        "system_answer": answer.strip() + "\n\n" + render_citations(trace),
        "trace": trace,
        "retrieved_context": _retrieved_context(trace),
    }


def build_live_report(records: list[dict]) -> dict:
    subset = load_live_subset()
    positives = {p.id: p for p in load_positives()}
    expected_by_id = {p.id: p.expected_requirements for p in positives.values()}
    by_passage = index_by_id()

    positive_records = [r for r in records if r["kind"] == "positive"]
    negative_records = [r for r in records if r["kind"] == "negative"]
    positive_by_id = {r["item_id"]: r for r in positive_records}

    scored = []
    for record in positive_records:
        gold = positives[record["item_id"]]
        passages = [by_passage[pid] for pid in gold.gold_passage_ids]
        scored.append({"item_id": record["item_id"], **GM.score_positive(record, passages)})
    generation = GM.aggregate_generation(scored)
    coverage_ids = [
        item_id for item_id in subset["positive_ids"] if item_id in positive_by_id
    ]
    summary = {
        "positive_count": len(positive_records),
        "negative_count": len(negative_records),
        "groundedness": generation["groundedness"],
        "citation_correctness": generation["citation_correctness"],
        "faithfulness": generation["faithfulness"],
        "hallucination": generation["hallucination"],
        "any_forged": generation["any_forged"],
        "not_found_honesty": TM.not_found_honesty(negative_records),
        "requirement_coverage": TM.requirement_coverage(
            positive_by_id, coverage_ids, expected_by_id
        ) if coverage_ids else 0.0,
    }
    summary["pass"] = (
        not summary["any_forged"]
        and summary["groundedness"] >= _PASS_BARS["groundedness"]
        and summary["citation_correctness"] >= _PASS_BARS["citation_correctness"]
        and summary["faithfulness"] >= _PASS_BARS["faithfulness"]
        and summary["not_found_honesty"] == _PASS_BARS["not_found_honesty"]
        and summary["requirement_coverage"] >= _PASS_BARS["requirement_coverage"]
    )
    return {"summary": summary, "records": records, "scored_positives": scored}


def run_live_conformance(*, client=None) -> dict:
    config = require_live_agent_config()
    subset = load_live_subset()
    positives = {p.id: p for p in load_positives()}
    negatives = {n.id: n for n in load_negatives()}
    records = []

    for item_id in subset["positive_ids"]:
        item = positives[item_id]
        record = invoke_live_item(item.question, client=client, config=config)
        _, judge_raw = recorder._judge(  # noqa: SLF001 - shared harness contract
            item.question,
            "\n".join(c["text"] for c in record["retrieved_context"]),
            GM.prose(record["system_answer"]),
        )
        records.append({
            "kind": "positive",
            "item_id": item_id,
            "question": item.question,
            **record,
            "judge_raw_response": judge_raw,
        })

    for item_id in subset["negative_ids"]:
        item = negatives[item_id]
        record = invoke_live_item(item.question, client=client, config=config)
        records.append({
            "kind": "negative",
            "item_id": item_id,
            "question": item.question,
            **record,
        })

    return build_live_report(records)


def main() -> None:
    report = run_live_conformance()
    DEFAULT_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(DEFAULT_REPORT_PATH)


if __name__ == "__main__":  # pragma: no cover
    main()
