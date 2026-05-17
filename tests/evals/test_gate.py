"""The Phase-3 quality gate: deterministic, offline, recomputed.

Every metric is recomputed from raw fixtures + the frozen corpus; nothing
trusts a precomputed score. Offline is enforced (sockets blocked);
determinism is enforced (recompute twice -> identical). Hash-binding is
asserted. The bars are the PRD CHECK thresholds, applied to the winning
deployable config.
"""
import json
import socket

import pytest

from tests.evals.harness import fixtures_io as FX
from tests.evals.harness import report as R
from tests.evals.harness.goldset import load_negatives, load_positives

pytestmark = pytest.mark.gate


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("gate attempted network I/O (must be offline)")
    monkeypatch.setattr(socket, "socket", _blocked)


def test_gold_cardinality_check():
    assert len(load_positives()) >= 30
    assert len(load_negatives()) >= 8


def test_gate_bars_on_winner_config():
    rep = R.build_report()
    assert rep["winner"] is not None, "no deployable winner -> gate FAIL"
    wkey = FX.config_key(
        rep["winner"]["chunkingStrategy"],
        rep["winner"]["chunkMaxTokens"],
        rep["winner"]["chunkOverlapPercent"])
    win = next(c for c in rep["configs"] if c["config_key"] == wkey)

    r = win["retrieval"]
    assert r["context_recall"] >= 0.90, r
    assert r["context_precision"] >= 0.80, r
    assert r["mrr"] >= 0.80, r

    g = win["generation"]
    assert g is not None, "winner has no committed fixtures"
    assert g["any_forged"] is False, "a fixture failed the forgery check"
    assert g["faithfulness"] >= 0.95, g
    assert g["citation_correctness"] >= 0.95, g
    assert g["hallucination"] <= 0.05, g
    assert g["not_found_honesty"] == 1.0, g
    assert g["requirement_coverage"] >= 0.90, g


def test_gate_is_deterministic():
    a = json.dumps(R.build_report(), sort_keys=True)
    b = json.dumps(R.build_report(), sort_keys=True)
    assert a == b


def test_hash_binding_rejects_tampered_fixture():
    fx = {
        "kind": "negative",
        "retrieved_context": [{"chunk_id": "d#1", "text": "x"}],
        "retrieved_context_sha256": "deadbeef",  # wrong
        "prompt_sha256": FX.judge_prompt_sha(),
        "rubric_sha256": FX.judge_rubric_sha(),
    }
    with pytest.raises(AssertionError, match="retrieved_context_sha256"):
        FX.assert_hash_binding(fx, "tampered.json")

    fx2 = dict(fx)
    fx2["retrieved_context_sha256"] = FX.context_hash(fx["retrieved_context"])
    fx2["prompt_sha256"] = "0" * 64  # wrong prompt hash
    with pytest.raises(AssertionError, match="prompt_sha256"):
        FX.assert_hash_binding(fx2, "tampered2.json")
