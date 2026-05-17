"""Chunking decision (Phase 1<->3 handoff). The harness scored >=2
deploy-equivalent FIXED_SIZE configs plus an advisory HIERARCHICAL one;
the committed report.json/report.md exist; and infra/cdk.json equals the
report's winner. The check recomputes the winner deterministically and
compares it to the committed machine contract — not markdown parsing.
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
    hier = [c for c in rep["configs"] if c["strategy"] == "HIERARCHICAL"]
    assert hier and hier[0]["deploy_equivalent"] is False


def test_report_json_and_md_committed():
    assert R.REPORT_JSON.is_file(), "tests/evals/report.json missing"
    assert R.REPORT_MD.is_file(), "tests/evals/report.md missing"


def test_committed_report_matches_recomputed_winner():
    rep = R.build_report()
    committed = json.loads(R.REPORT_JSON.read_text(encoding="utf-8"))
    assert committed["winner"] == rep["winner"]
    assert rep["winner"] is not None, "no deployable winner selected"


def test_cdk_json_equals_report_winner():
    committed = json.loads(R.REPORT_JSON.read_text(encoding="utf-8"))
    winner = committed["winner"]
    ctx = json.loads(R.CDK_JSON.read_text(encoding="utf-8"))["context"]
    assert ctx["chunkingStrategy"] == winner["chunkingStrategy"]
    assert ctx["chunkMaxTokens"] == winner["chunkMaxTokens"]
    assert ctx["chunkOverlapPercent"] == winner["chunkOverlapPercent"]
    assert isinstance(ctx["chunkMaxTokens"], int)
    assert isinstance(ctx["chunkOverlapPercent"], int)
    # winner must be a deployable FIXED_SIZE strategy
    assert winner["chunkingStrategy"] == "FIXED_SIZE"
