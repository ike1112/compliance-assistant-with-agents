"""Chunking decision (Phase 1<->3 handoff). The committed report.json is
the machine contract: it must equal a full deterministic recompute (not
just the winner), report.md is rendered from it, and infra/cdk.json must
equal the RECOMPUTED winner directly. >=2 deploy-equivalent FIXED_SIZE
configs plus an advisory HIERARCHICAL one are scored.
"""
import json
from pathlib import Path

import pytest

from tests.evals.harness import report as R

pytestmark = pytest.mark.gate

REPO = Path(__file__).resolve().parents[2]


def test_at_least_two_deploy_equivalent_plus_advisory_hierarchical():
    rep = R.build_report()
    deploy = [c for c in rep["configs"] if c["deploy_equivalent"]]
    assert len(deploy) >= 2, "need >=2 deploy-equivalent FIXED_SIZE configs"
    assert all(c["strategy"] == "FIXED_SIZE" for c in deploy)
    assert all(c["generation"] is not None for c in deploy), (
        "every deploy-equivalent config must have scored fixtures")
    hier = [c for c in rep["configs"] if c["strategy"] == "HIERARCHICAL"]
    assert hier and hier[0]["deploy_equivalent"] is False
    assert hier[0]["generation"] is None  # advisory, no fixtures by design


def test_report_json_and_md_committed():
    assert R.REPORT_JSON.is_file(), "tests/evals/report.json missing"
    assert R.REPORT_MD.is_file(), "tests/evals/report.md missing"


def test_committed_report_json_is_full_recompute_parity():
    recomputed = R.build_report()
    committed = json.loads(R.REPORT_JSON.read_text(encoding="utf-8"))
    # Full canonical parity — every config's metrics, not just winner.
    assert json.dumps(committed, sort_keys=True) == json.dumps(
        recomputed, sort_keys=True), "report.json != deterministic recompute"
    assert recomputed["winner"] is not None, "no deployable winner"


def test_report_md_is_rendered_from_report_json():
    committed = json.loads(R.REPORT_JSON.read_text(encoding="utf-8"))
    assert R.REPORT_MD.read_text(encoding="utf-8") == R.render_md(committed)


def test_cdk_json_equals_recomputed_winner():
    winner = R.build_report()["winner"]
    ctx = json.loads(R.CDK_JSON.read_text(encoding="utf-8"))["context"]
    assert ctx["chunkingStrategy"] == winner["chunkingStrategy"]
    assert ctx["chunkMaxTokens"] == winner["chunkMaxTokens"]
    assert ctx["chunkOverlapPercent"] == winner["chunkOverlapPercent"]
    assert isinstance(ctx["chunkMaxTokens"], int)
    assert isinstance(ctx["chunkOverlapPercent"], int)
    assert winner["chunkingStrategy"] == "FIXED_SIZE"
