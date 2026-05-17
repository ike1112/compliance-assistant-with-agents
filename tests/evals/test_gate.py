"""The Phase-3 quality gate: deterministic, offline, recomputed.

Offline + no-subprocess is enforced for every `gate`-marked test by
tests/evals/conftest.py. Every metric is recomputed from raw fixtures
bound to the recomputed deterministic retriever; nothing trusts a stored
score. The binding generation criterion is deterministic groundedness;
the recorded judge score is corroborating. Bars are the PRD CHECK
thresholds, applied to the winning deployable config.
"""
import json

import pytest

from tests.evals.harness import fixtures_io as FX
from tests.evals.harness import report as R
from tests.evals.harness.goldset import load_negatives, load_positives

pytestmark = pytest.mark.gate


def test_offline_guard_is_active():
    # conftest replaced socket/subprocess for gate tests.
    import socket
    with pytest.raises(AssertionError, match="offline"):
        socket.socket()


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
    # Deterministic binding criterion:
    assert g["groundedness"] >= 0.95, g
    assert g["citation_correctness"] >= 0.95, g
    assert g["not_found_honesty"] == 1.0, g
    assert g["requirement_coverage"] >= 0.90, g
    # Corroborating evidence (judge):
    assert g["faithfulness"] >= 0.95, g
    assert g["hallucination"] <= 0.05, g


def test_every_deploy_equivalent_config_meets_bars():
    rep = R.build_report()
    for c in rep["configs"]:
        if not c["deploy_equivalent"]:
            continue
        g = c["generation"]
        assert g is not None, f"{c['config_key']}: missing fixtures"
        assert c["retrieval"]["context_recall"] >= 0.90, c
        assert g["groundedness"] >= 0.95 and not g["any_forged"], c


def test_gate_is_deterministic():
    # >=10 byte-identical canonical recomputes (the B4 spec strength).
    runs = {json.dumps(R.build_report(), sort_keys=True) for _ in range(10)}
    assert len(runs) == 1, "build_report() is not deterministic across 10 runs"


def test_hash_binding_rejects_tampered_fixture():
    fx = {
        "kind": "negative",
        "retrieved_context": [{"chunk_id": "d#1", "text": "x"}],
        "retrieved_context_sha256": "deadbeef",
        "prompt_sha256": FX.judge_prompt_sha(),
        "rubric_sha256": FX.judge_rubric_sha(),
    }
    with pytest.raises(AssertionError, match="retrieved_context_sha256"):
        FX.assert_hash_binding(fx, "tampered.json")
    fx2 = dict(fx)
    fx2["retrieved_context_sha256"] = FX.context_hash(fx["retrieved_context"])
    fx2["prompt_sha256"] = "0" * 64
    with pytest.raises(AssertionError, match="prompt_sha256"):
        FX.assert_hash_binding(fx2, "tampered2.json")
