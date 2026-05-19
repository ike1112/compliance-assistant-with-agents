"""Kill surface for compliance_assistant.prod_readiness.

The audit doc is git-untracked (not in the review-gate judged diff), so this
checker is the only automated guard on it — every validation rule gets a
fixture that fails *only* that rule, plus the mandatory code-fence/prose
false-positive fixtures, so the mutation floor (0.80) and changed-line
coverage (0.90) hold on real logic.
"""
from pathlib import Path

import pytest

from compliance_assistant.prod_readiness import (
    main,
    parse_catalog,
    parse_findings,
    validate,
)

# A finding with all six Reasoning-Gate fields, parametrised by pillar +
# id + the evidence reference (so COST/SUS can cite the receipt, SEC/REL
# the cfn-guard receipt).
def _finding(pillar: str, n: int, evidence: str) -> str:
    return (
        f"GAP-{pillar}-{n} [P1] sample finding [P1|mixed|S]\n"
        f"  Risk: a concrete production risk stated plainly.\n"
        f"  Evidence: {evidence}\n"
        f"  Why this matters here (NOT generic): tied to this compliance "
        f"report generator whose output users treat as authoritative.\n"
        f"  Source: E6-wa-lens-{pillar.lower()}.md\n"
        f"  Counter-argument: skip only if runs are disposable — false here.\n"
        f"  Fix: resolved by the {pillar} hardening sub-project.\n"
    )


_PILLAR_EVIDENCE = {
    "OPS": "infra/stacks/observability_stack.py:10",
    "SEC": "_evidence/cfn-guard-agent.txt",
    "REL": "_evidence/cfn-guard-agent.txt",
    "PERF": "infra/stacks/runtime_stack.py:5",
    "COST": "_evidence/analyze-cdk-project.json (Aurora MinCapacity 0)",
    "SUS": "_evidence/analyze-cdk-project.json (arm64, scale-to-zero)",
    "GENAI": "tests/evals/report.md",
}


def _good_doc() -> str:
    parts = [
        "# Compliance Assistant — Production-Readiness Audit",
        "Status: working notes — not git-tracked",
        "",
        "## 1. Purpose & method",
        "Audit of the synthesized stack against the WA Lens.",
        "",
        "### 3.1 Resource catalog",
        "| ID | Resource | Source |",
        "|----|----------|--------|",
        "| R-KB | Bedrock Knowledge Base | Bedrock IaC |",
        "| R-AURORA-VEC | Aurora pgvector | Bedrock IaC |",
        "",
        "### 3.2 Gap id scheme",
        "GAP-<PILLAR>-NN, monotonic per pillar.",
        "",
    ]
    for p in ("OPS", "SEC", "REL", "PERF", "COST", "SUS", "GENAI"):
        parts += [f"## {p} — pillar", _finding(p, 1, _PILLAR_EVIDENCE[p]), ""]
    parts += [
        "## Ranked backlog",
        "| Rank | GAP | Score |",
        "|------|-----|-------|",
        "| 1 | GAP-OPS-1 | 4.5 |",
        "| 2 | GAP-SEC-1 | 4.5 |",
        "| 3 | GAP-REL-1 | 4.0 |",
        "| 4 | GAP-PERF-1 | 3.0 |",
        "| 5 | GAP-COST-1 | 2.0 |",
        "| 6 | GAP-SUS-1 | 2.0 |",
        "| 7 | GAP-GENAI-1 | 9.0 |",
        "",
    ]
    return "\n".join(parts)


def _write(tmp_path: Path, doc: str | None = None,
           analyze: str | None = None, guard: str | None = None) -> Path:
    """Write the audit doc + the two evidence receipts; return the doc path."""
    ev = tmp_path / "_evidence"
    ev.mkdir(exist_ok=True)
    (ev / "analyze-cdk-project.json").write_text(
        analyze if analyze is not None
        else '{"services": ["AWS::RDS::DBCluster", "AWS::S3::Bucket"]}',
        encoding="utf-8",
    )
    (ev / "cfn-guard-agent.txt").write_text(
        guard if guard is not None
        else "ComplianceAgentStack COMPLIANT, 0 violations (aws-security)\n",
        encoding="utf-8",
    )
    p = tmp_path / "2026-05-16-compliance-prod-readiness.md"
    p.write_text(_good_doc() if doc is None else doc, encoding="utf-8")
    return p


# --- happy path ----------------------------------------------------------

def test_good_doc_passes(tmp_path):
    p = _write(tmp_path)
    assert validate(p) == []
    assert main([str(p)]) == 0


# --- rule 1: every pillar present ---------------------------------------

def test_missing_pillar(tmp_path):
    doc = _good_doc().replace("## SUS — pillar\n", "")
    p = _write(tmp_path, doc)
    v = validate(p)
    assert any("## SUS" in s and "missing" in s for s in v)


# --- rule 2: each pillar defended ---------------------------------------

def test_evidence_free_not_a_gap_rejected(tmp_path):
    doc = _good_doc().replace(
        _finding("GENAI", 1, _PILLAR_EVIDENCE["GENAI"]),
        "checked, not a gap because the prior phases closed it\n",
    ).replace("| 7 | GAP-GENAI-1 | 9.0 |\n", "")
    p = _write(tmp_path, doc)
    v = validate(p)
    assert any("GENAI" in s and "no Source" in s.replace(":", "")
               or ("GENAI" in s and "carries no" in s) for s in v)


def test_not_a_gap_with_source_passes(tmp_path):
    doc = _good_doc().replace(
        _finding("GENAI", 1, _PILLAR_EVIDENCE["GENAI"]),
        "checked, not a gap because prior phases closed it. "
        "Source: E6-wa-lens-genai.md\n",
    ).replace("| 7 | GAP-GENAI-1 | 9.0 |\n", "")
    p = _write(tmp_path, doc)
    assert validate(p) == []


# --- rule 3: COST/SUS must cite the analyze receipt ---------------------

def test_cost_not_citing_receipt(tmp_path):
    doc = _good_doc().replace(
        "_evidence/analyze-cdk-project.json (Aurora MinCapacity 0)",
        "infra/stacks/kb_stack.py:1",
    )
    p = _write(tmp_path, doc)
    v = validate(p)
    assert any(s.startswith("pillar COST") for s in v)


def test_sus_not_citing_receipt(tmp_path):
    doc = _good_doc().replace(
        "_evidence/analyze-cdk-project.json (arm64, scale-to-zero)",
        "infra/stacks/runtime_stack.py:9",
    )
    p = _write(tmp_path, doc)
    v = validate(p)
    assert any(s.startswith("pillar SUS") for s in v)


# --- rule 4: six fields per finding -------------------------------------

def test_finding_missing_source_field(tmp_path):
    doc = _good_doc().replace(
        "  Source: E6-wa-lens-ops.md\n", "", 1
    )
    p = _write(tmp_path, doc)
    v = validate(p)
    assert any("GAP-OPS-1" in s and "Source:" in s for s in v)


def test_finding_empty_risk_field(tmp_path):
    doc = _good_doc().replace(
        "  Risk: a concrete production risk stated plainly.\n  Evidence:"
        " infra/stacks/observability_stack.py:10\n",
        "  Risk:\n  Evidence: infra/stacks/observability_stack.py:10\n",
        1,
    )
    p = _write(tmp_path, doc)
    v = validate(p)
    assert any("GAP-OPS-1" in s and "Risk:" in s for s in v)


# --- rule 5: no placeholders --------------------------------------------

def test_stray_placeholder(tmp_path):
    doc = _good_doc().replace(
        "## 1. Purpose & method\n",
        "## 1. Purpose & method\nTBD finish this section.\n",
    )
    p = _write(tmp_path, doc)
    v = validate(p)
    assert any("TBD" in s for s in v)


# --- rule 6: each GAP twice (prose/code excluded) -----------------------

def test_gap_only_once_fails(tmp_path):
    doc = _good_doc().replace("| 7 | GAP-GENAI-1 | 9.0 |\n", "")
    p = _write(tmp_path, doc)
    v = validate(p)
    assert any("GAP-GENAI-1" in s and "ranked=False" in s for s in v)


# --- rule 7: every R-* declared in 3.1 ----------------------------------

def test_undeclared_r_id(tmp_path):
    doc = _good_doc().replace(
        "  Fix: resolved by the OPS hardening sub-project.\n",
        "  Fix: resolved by the OPS sub-project, see R-NOTDECLARED.\n",
        1,
    )
    p = _write(tmp_path, doc)
    v = validate(p)
    assert any("R-NOTDECLARED" in s for s in v)


# --- rule 8: receipts are real ------------------------------------------

def test_cited_evidence_absent(tmp_path):
    p = _write(tmp_path)
    (tmp_path / "_evidence" / "cfn-guard-agent.txt").unlink()
    v = validate(p)
    assert any("cfn-guard-agent.txt" in s and "missing" in s for s in v)


def test_receipt_is_stub(tmp_path):
    p = _write(tmp_path, guard="STUB: cfn-guard could not run\n")
    v = validate(p)
    assert any("stub/placeholder" in s for s in v)


def test_analyze_receipt_not_json(tmp_path):
    p = _write(tmp_path, analyze="not json at all")
    v = validate(p)
    assert any("not valid JSON" in s for s in v)


def test_analyze_receipt_empty_inventory(tmp_path):
    p = _write(tmp_path, analyze="{}")
    v = validate(p)
    assert any("empty service inventory" in s for s in v)


def test_sec_must_cite_cfn_guard(tmp_path):
    doc = _good_doc().replace(
        "## SEC — pillar\n" + _finding("SEC", 1, "_evidence/cfn-guard-agent.txt"),
        "## SEC — pillar\n" + _finding("SEC", 1, "infra/stacks/agent_stack.py:3"),
    )
    p = _write(tmp_path, doc)
    v = validate(p)
    assert any(s.startswith("pillar SEC") and "cfn-guard" in s for s in v)


# --- missing doc / malformed catalog (fail-closed) ----------------------

def test_missing_doc_is_violation_not_exception(tmp_path):
    missing = tmp_path / "nope.md"
    v = validate(missing)
    assert len(v) == 1 and "not found" in v[0]
    assert main([str(missing)]) == 1


def test_no_args_returns_one(tmp_path):
    assert main([]) == 1


def test_malformed_catalog_raises_then_main_returns_one(tmp_path):
    doc = _good_doc().replace(
        "| R-KB | Bedrock Knowledge Base | Bedrock IaC |",
        "| R-KB | only-two-cells |",
    )
    p = _write(tmp_path, doc)
    with pytest.raises(ValueError):
        validate(p)
    assert main([str(p)]) == 1  # no traceback, exit 1


def test_catalog_section_absent_raises(tmp_path):
    doc = _good_doc().replace("### 3.1 Resource catalog", "### 3.0 misc")
    p = _write(tmp_path, doc)
    with pytest.raises(ValueError):
        validate(p)


# --- code-fence / prose false positives (MANDATORY) ---------------------

def test_gap_token_only_in_code_fence_does_not_count(tmp_path):
    # A GAP token appearing only inside a fenced block is stripped: it
    # neither creates a spurious id nor satisfies the >=2x rule.
    doc = _good_doc() + "\n```\nGAP-OPS-1 GAP-OPS-1 GAP-ZZZ-9\n```\n"
    p = _write(tmp_path, doc)
    assert validate(p) == []


def test_r_token_only_in_code_fence_is_not_a_violation(tmp_path):
    doc = _good_doc() + "\n```\nexample uses R-FAKE-THING here\n```\n"
    p = _write(tmp_path, doc)
    assert validate(p) == []


def test_tbd_inside_code_fence_is_not_a_violation(tmp_path):
    doc = _good_doc() + "\n```\n# sample: TBD TODO XXX in an example\n```\n"
    p = _write(tmp_path, doc)
    assert validate(p) == []


def test_inline_code_token_excluded_from_placeholder(tmp_path):
    doc = _good_doc().replace(
        "## 1. Purpose & method\n",
        "## 1. Purpose & method\nsee the `TBD` literal token handling.\n",
    )
    p = _write(tmp_path, doc)
    # `TBD` is inside an inline-code span -> stripped -> not a violation.
    assert validate(p) == []


# --- parser units -------------------------------------------------------

def test_parse_catalog_returns_declared_ids(tmp_path):
    from compliance_assistant.prod_readiness import _strip_fenced
    declared = parse_catalog(_strip_fenced(_good_doc()))
    assert declared == {"R-KB", "R-AURORA-VEC"}


def test_parse_findings_attributes_to_section_pillar(tmp_path):
    from compliance_assistant.prod_readiness import _strip_fenced
    fs = parse_findings(_strip_fenced(_good_doc()))
    assert {f.gap_id for f in fs} == {
        f"GAP-{p}-1" for p in
        ("OPS", "SEC", "REL", "PERF", "COST", "SUS", "GENAI")
    }
    ops = [f for f in fs if f.pillar == "OPS"][0]
    assert all(ops.fields[k] for k in
               ("Risk:", "Evidence:", "Source:", "Fix:"))
