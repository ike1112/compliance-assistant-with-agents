"""aggregate: the spec §3 step-6 rule, plus a base-SHA-bound PASS token
that makes builder self-certification impossible. test_engineer is
advisory — it is recorded but never blocks."""
import json

from review_gate.aggregate import GateOutcome, Verdict, aggregate, write_outcome_token


def _v(name, passed, severity=None):
    return Verdict(name=name, passed=passed, severity=severity, summary=name)


def _all_clean():
    return [
        _v("codex", True),
        _v("test_integrity", True),
        _v("security", True),
        _v("code", True),
        _v("regression", True),
    ]


def test_all_clean_passes():
    out = aggregate(_all_clean())
    assert out.passed is True
    assert out.blocking == []


def test_test_integrity_fail_blocks():
    v = _all_clean()
    v[1] = _v("test_integrity", False)
    out = aggregate(v)
    assert out.passed is False
    assert "test_integrity" in out.blocking


def test_regression_fail_blocks():
    v = _all_clean()
    v[4] = _v("regression", False)
    assert aggregate(v).passed is False


def test_codex_major_blocks_minor_does_not():
    v = _all_clean()
    v[0] = _v("codex", True, "MINOR")
    assert aggregate(v).passed is True
    v[0] = _v("codex", True, "MAJOR")
    assert aggregate(v).passed is False


def test_security_or_code_blocker_blocks():
    v = _all_clean()
    v[2] = _v("security", True, "BLOCKER")
    assert aggregate(v).passed is False
    v = _all_clean()
    v[3] = _v("code", True, "MAJOR")
    assert aggregate(v).passed is False


def test_missing_required_leg_is_fail_not_pass():
    # Only four legs reported (codex absent) -> cannot pass.
    out = aggregate([_v("test_integrity", True), _v("security", True),
                      _v("code", True), _v("regression", True)])
    assert out.passed is False
    assert "codex" in out.blocking


def test_test_engineer_is_advisory_never_blocks():
    # Even a BLOCKER from test-engineer must not fail the gate; it is
    # evidence only. Mutation is the objective test bar, not this opinion.
    v = _all_clean()
    v.append(_v("test_engineer", False, "BLOCKER"))
    out = aggregate(v)
    assert out.passed is True
    assert "test_engineer" not in out.blocking
    assert "test_engineer" in out.evidence


def test_outcome_token_is_bound_to_base_sha(tmp_path):
    tok = tmp_path / "tok.json"
    write_outcome_token(tok, base_sha="deadbeef", phase="3", round_=2,
                         outcome=aggregate(_all_clean()))
    data = json.loads(tok.read_text(encoding="utf-8"))
    assert data["base_sha"] == "deadbeef"
    assert data["phase"] == "3"
    assert data["round"] == 2
    assert data["passed"] is True
    assert "ts" in data
