"""End-to-end fail-closed proofs: a poisoned fixture set must NOT yield a
passing gate. Real fixtures are copied to a temp dir, tampered, and
build_report is driven against them.
"""
import json
import shutil

import pytest

from tests.evals.harness import fixtures_io as FX
from tests.evals.harness import report as R

pytestmark = pytest.mark.gate


@pytest.fixture
def fixtures_copy(tmp_path, monkeypatch):
    dst = tmp_path / "fixtures"
    shutil.copytree(FX.FIXTURES_DIR, dst)
    monkeypatch.setattr(FX, "FIXTURES_DIR", dst)
    return dst


def test_baseline_copy_still_passes(fixtures_copy):
    rep = R.build_report()
    assert rep["winner"] is not None


def test_missing_fixture_for_deploy_config_hard_fails(fixtures_copy):
    next(fixtures_copy.glob("pos-020__FIXED_SIZE-256-15.json")).unlink()
    with pytest.raises(AssertionError, match="missing fixture"):
        R.build_report()


def test_tampered_context_is_rejected(fixtures_copy):
    fp = fixtures_copy / "pos-001__FIXED_SIZE-512-20.json"
    fx = json.loads(fp.read_text(encoding="utf-8"))
    fx["retrieved_context"] = [{"chunk_id": "forged#0", "text": "gold-rich"}]
    fx["retrieved_context_sha256"] = FX.context_hash(fx["retrieved_context"])
    fp.write_text(json.dumps(fx), encoding="utf-8")
    with pytest.raises(AssertionError, match="retrieved_context"):
        R.build_report()


def test_fabricating_negative_drops_not_found_honesty(fixtures_copy):
    fp = fixtures_copy / "neg-001__FIXED_SIZE-512-20.json"
    fx = json.loads(fp.read_text(encoding="utf-8"))
    fx["system_answer"] = "Per PCI DSS Requirement 2.2.1 you must harden."
    fp.write_text(json.dumps(fx), encoding="utf-8")
    rep = R.build_report()
    win = next(c for c in rep["configs"]
               if c["config_key"] == "FIXED_SIZE-512-20")
    assert win["generation"]["not_found_honesty"] < 1.0
