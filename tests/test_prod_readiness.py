"""Kill surface for compliance_assistant.prod_readiness.

The audit doc is git-untracked (not in the review-gate judged diff), so this
checker is the only automated guard on it. Assertions pin the EXACT
violation message (not a loose substring) so message-literal mutants die,
every rule and fail-closed branch has a fixture that fails only it, the
mandatory code-fence/prose false-positive fixtures are present, and the
round-2 hardening cases (line-anchored fields, exactly-one-of-six,
dismissal-as-unit, real cfn-guard citation, COST/SUS Evidence-field,
path-traversal containment, strict R-token + positional catalog exclusion)
are isolated. Strengthening the logic + these real cases carries the 0.80
mutation / 0.90 coverage floors — nothing is weakened.
"""
from pathlib import Path

import pytest

from compliance_assistant.prod_readiness import (
    Finding,
    main,
    parse_catalog,
    parse_findings,
    validate,
    _strip_fenced,
)

PILLARS_T = ("OPS", "SEC", "REL", "PERF", "COST", "SUS", "GENAI")
_SIX = ("Risk:", "Evidence:", "Why this matters here", "Source:",
        "Counter-argument:", "Fix:")


def _finding(pillar: str, n: int, evidence: str,
             drop: str | None = None, dup: str | None = None,
             order: tuple[str, ...] | None = None) -> str:
    head = f"GAP-{pillar}-{n} [P1] sample finding [P1|mixed|S]\n"
    lines = {
        "Risk:": "  Risk: a concrete production risk stated plainly.\n",
        "Evidence:": f"  Evidence: {evidence}\n",
        "Why this matters here": (
            "  Why this matters here (NOT generic): tied to this compliance "
            "report generator whose output users treat as authoritative.\n"
        ),
        "Source:": f"  Source: E6-wa-lens-{pillar.lower()}.md\n",
        "Counter-argument:": (
            "  Counter-argument: skip only if runs are disposable — false.\n"
        ),
        "Fix:": f"  Fix: resolved by the {pillar} hardening sub-project.\n",
    }
    seq = list(order) if order else list(lines)
    body = ""
    for k in seq:
        if k == drop:
            continue
        body += lines[k]
        if k == dup:
            body += lines[k]
    return head + body


_PE = {
    "OPS": "infra/stacks/observability_stack.py:10",
    "SEC": "_evidence/cfn-guard-agent.txt records ComplianceAgentStack",
    "REL": "_evidence/cfn-guard-deferred.txt operator pre-deploy",
    "PERF": "infra/stacks/runtime_stack.py:5",
    "COST": "_evidence/analyze-cdk-project.json (Aurora MinCapacity 0)",
    "SUS": "_evidence/analyze-cdk-project.json (arm64, scale-to-zero)",
    "GENAI": "tests/evals/report.md",
}


def _good_doc(catalog_rows: str | None = None) -> str:
    rows = catalog_rows if catalog_rows is not None else (
        "| R-KB | Bedrock Knowledge Base | Bedrock IaC |\n"
        "| R-AURORA-VEC | Aurora pgvector | Bedrock IaC |\n"
    )
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
        rows.rstrip("\n"),
        "",
        "### 3.2 Gap id scheme",
        "GAP-<PILLAR>-NN, monotonic per pillar.",
        "",
    ]
    for p in PILLARS_T:
        parts += [f"## {p} — pillar", _finding(p, 1, _PE[p]), ""]
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
           analyze: str | None = None, guard: str | None = None,
           deferred: str | None = None) -> Path:
    ev = tmp_path / "_evidence"
    ev.mkdir(exist_ok=True)
    (ev / "analyze-cdk-project.json").write_text(
        analyze if analyze is not None
        else '{"services": ["AWS::RDS::DBCluster", "AWS::S3::Bucket"]}',
        encoding="utf-8")
    (ev / "cfn-guard-agent.txt").write_text(
        guard if guard is not None
        else "ComplianceAgentStack COMPLIANT, 0 violations (aws-security)\n",
        encoding="utf-8")
    (ev / "cfn-guard-deferred.txt").write_text(
        deferred if deferred is not None
        else "KB/Runtime/Observability operator pre-deploy (accepted)\n",
        encoding="utf-8")
    p = tmp_path / "2026-05-16-compliance-prod-readiness.md"
    p.write_text(_good_doc() if doc is None else doc, encoding="utf-8")
    return p


# --- happy path ---------------------------------------------------------

def test_good_doc_passes(tmp_path):
    p = _write(tmp_path)
    assert validate(p) == []
    assert main([str(p)]) == 0


def test_real_audit_doc_passes_strict_checker():
    repo = Path(__file__).resolve().parents[1]
    doc = repo / "docs/analysis/2026-05-16-compliance-prod-readiness.md"
    if doc.is_file():
        assert validate(doc) == []


# --- rule 1 -------------------------------------------------------------

def test_missing_pillar_exact_message(tmp_path):
    p = _write(tmp_path, _good_doc().replace("## SUS — pillar\n", ""))
    assert "pillar section '## SUS' missing" in validate(p)


def test_two_missing_pillars_both_reported(tmp_path):
    # kills a continue->break mutant in the per-pillar loop.
    doc = _good_doc().replace("## SUS — pillar\n", "").replace(
        "## PERF — pillar\n", "")
    v = validate(_write(tmp_path, doc))
    assert "pillar section '## SUS' missing" in v
    assert "pillar section '## PERF' missing" in v


# --- rule 2: dismissal-as-unit (BLOCKER-1) -----------------------------

def _genai_dismissal(tmp_path, dismissal: str) -> Path:
    doc = _good_doc().replace(
        _finding("GENAI", 1, _PE["GENAI"]), dismissal,
    ).replace("| 7 | GAP-GENAI-1 | 9.0 |\n", "")
    return _write(tmp_path, doc)


def test_dismissal_with_source_field_line_passes(tmp_path):
    p = _genai_dismissal(
        tmp_path,
        "checked, not a gap because prior phases closed it.\n"
        "  Source: E6-wa-lens-genai.md\n")
    assert validate(p) == []


def test_dismissal_with_resolvable_evidence_field_passes(tmp_path):
    p = _genai_dismissal(
        tmp_path,
        "checked, not a gap because the receipt shows it.\n"
        "  Evidence: _evidence/cfn-guard-agent.txt\n")
    assert validate(p) == []


def test_dismissal_inline_source_not_a_field_rejected(tmp_path):
    p = _genai_dismissal(
        tmp_path,
        "checked, not a gap because reasons. Source: inline-not-a-field\n")
    assert validate(p) == [
        "pillar GENAI: 'checked, not a gap because' carries no "
        "non-empty Source:/Evidence: reference"]


def test_dismissal_empty_source_value_rejected(tmp_path):
    p = _genai_dismissal(
        tmp_path, "checked, not a gap because reasons.\n  Source:\n")
    assert validate(p) == [
        "pillar GENAI: 'checked, not a gap because' carries no "
        "non-empty Source:/Evidence: reference"]


def test_dismissal_unresolvable_cited_evidence_rejected(tmp_path):
    p = _genai_dismissal(
        tmp_path,
        "checked, not a gap because.\n"
        "  Evidence: _evidence/does-not-exist.txt\n")
    assert ("pillar GENAI dismissal: cited evidence missing: "
            "_evidence/does-not-exist.txt") in validate(p)


def test_evidence_free_not_a_gap_rejected(tmp_path):
    p = _genai_dismissal(
        tmp_path, "checked, not a gap because prior phases closed it\n")
    assert validate(p) == [
        "pillar GENAI: 'checked, not a gap because' carries no "
        "non-empty Source:/Evidence: reference"]


def test_pillar_no_finding_no_dismissal_rejected(tmp_path):
    doc = _good_doc().replace(
        _finding("GENAI", 1, _PE["GENAI"]),
        _finding("GENAI", 1, _PE["GENAI"], drop="Fix:"))
    assert ("pillar GENAI: no complete six-field finding and no "
            "'checked, not a gap because' statement") in validate(
                _write(tmp_path, doc))


def test_two_pillars_undefended_both_reported(tmp_path):
    # kills continue->break in _rule_pillar_defended.
    doc = _good_doc()
    doc = doc.replace(
        _finding("SEC", 1, _PE["SEC"]),
        _finding("SEC", 1, _PE["SEC"], drop="Risk:"))
    doc = doc.replace(
        _finding("GENAI", 1, _PE["GENAI"]),
        _finding("GENAI", 1, _PE["GENAI"], drop="Risk:"))
    v = validate(_write(tmp_path, doc))
    assert ("pillar SEC: no complete six-field finding and no "
            "'checked, not a gap because' statement") in v
    assert ("pillar GENAI: no complete six-field finding and no "
            "'checked, not a gap because' statement") in v


# --- rule 3: COST/SUS analyze receipt in Evidence: ---------------------

def test_cost_receipt_outside_evidence_field_rejected(tmp_path):
    f = (
        "GAP-COST-1 [P1] x [P1|mixed|S]\n"
        "  Risk: see _evidence/analyze-cdk-project.json for cost.\n"
        "  Evidence: infra/stacks/kb_stack.py:1\n"
        "  Why this matters here (NOT generic): cost.\n"
        "  Source: E6-wa-lens-cost.md\n"
        "  Counter-argument: skip if disposable — false.\n"
        "  Fix: resolved by Bedrock IaC.\n"
    )
    doc = _good_doc().replace(_finding("COST", 1, _PE["COST"]), f)
    assert (
        "pillar COST: needs a finding citing "
        "_evidence/analyze-cdk-project.json in its Evidence: field "
        "(spine deferral is closed with the receipt, not by assertion)"
    ) in validate(_write(tmp_path, doc))


def test_sus_not_citing_receipt_rejected(tmp_path):
    doc = _good_doc().replace(
        "_evidence/analyze-cdk-project.json (arm64, scale-to-zero)",
        "infra/stacks/runtime_stack.py:9")
    assert (
        "pillar SUS: needs a finding citing "
        "_evidence/analyze-cdk-project.json in its Evidence: field "
        "(spine deferral is closed with the receipt, not by assertion)"
    ) in validate(_write(tmp_path, doc))


# --- rule 4: exactly one non-empty of each six field (MAJOR-5) --------

def test_finding_missing_field_exact(tmp_path):
    doc = _good_doc().replace(
        _finding("OPS", 1, _PE["OPS"]),
        _finding("OPS", 1, _PE["OPS"], drop="Source:"))
    assert "GAP-OPS-1: missing/empty field 'Source:'" in validate(
        _write(tmp_path, doc))


def test_duplicate_field_label_exact(tmp_path):
    doc = _good_doc().replace(
        _finding("OPS", 1, _PE["OPS"]),
        _finding("OPS", 1, _PE["OPS"], dup="Risk:"))
    assert ("GAP-OPS-1: field 'Risk:' appears 2x (exactly one required)"
            ) in validate(_write(tmp_path, doc))


def test_empty_field_value_exact(tmp_path):
    doc = _good_doc().replace(
        "  Risk: a concrete production risk stated plainly.\n", "  Risk:\n", 1)
    assert "GAP-OPS-1: missing/empty field 'Risk:'" in validate(
        _write(tmp_path, doc))


def test_fields_out_of_order_still_parse(tmp_path):
    weird = ("Fix:", "Risk:", "Source:", "Evidence:",
             "Counter-argument:", "Why this matters here")
    doc = _good_doc().replace(
        _finding("OPS", 1, _PE["OPS"]),
        _finding("OPS", 1, _PE["OPS"], order=weird))
    assert not any("GAP-OPS-1" in s for s in validate(_write(tmp_path, doc)))


def test_field_value_mentioning_label_not_miscounted(tmp_path):
    f = (
        "GAP-OPS-1 [P1] x [P1|mixed|S]\n"
        "  Risk: weigh Evidence: carefully before any Fix: is chosen.\n"
        "  Evidence: infra/stacks/observability_stack.py:10\n"
        "  Why this matters here (NOT generic): traceable.\n"
        "  Source: E6-wa-lens-ops.md\n"
        "  Counter-argument: skip if disposable — false.\n"
        "  Fix: resolved by Observability.\n"
    )
    doc = _good_doc().replace(_finding("OPS", 1, _PE["OPS"]), f)
    assert not any("GAP-OPS-1" in s for s in validate(_write(tmp_path, doc)))


# --- rule 6: GAP twice, both directions, exact message ----------------

def test_gap_in_finding_but_not_ranked_exact(tmp_path):
    p = _write(tmp_path, _good_doc().replace("| 7 | GAP-GENAI-1 | 9.0 |\n", ""))
    assert ("GAP-GENAI-1: must appear in both a pillar finding and the "
            "ranked backlog (finding=True, ranked=False)") in validate(p)


def test_gap_in_ranked_but_no_finding_exact(tmp_path):
    doc = _good_doc().replace(
        "| 7 | GAP-GENAI-1 | 9.0 |\n",
        "| 7 | GAP-GENAI-1 | 9.0 |\n| 8 | GAP-OPS-9 | 1.0 |\n")
    assert ("GAP-OPS-9: must appear in both a pillar finding and the "
            "ranked backlog (finding=False, ranked=True)") in validate(
                _write(tmp_path, doc))


def test_ranked_backlog_absent_flags_every_gap(tmp_path):
    doc = _good_doc()
    doc = doc[:doc.index("## Ranked backlog")]
    v = validate(_write(tmp_path, doc))
    assert sum("ranked=False" in s for s in v) >= 7


# --- rule 7 + R-token boundary (MAJOR-6) -------------------------------

def test_undeclared_r_id_exact(tmp_path):
    doc = _good_doc().replace(
        "  Fix: resolved by the OPS hardening sub-project.\n",
        "  Fix: resolved by OPS, see R-NOTDECLARED.\n", 1)
    assert ("R-NOTDECLARED: used but not declared in the ### 3.1 catalog"
            ) in validate(_write(tmp_path, doc))


def test_r_prefix_collision_is_rejected(tmp_path):
    doc = _good_doc().replace(
        "  Fix: resolved by the OPS hardening sub-project.\n",
        "  Fix: resolved by OPS, depends on R-AURORA.\n", 1)
    assert ("R-AURORA: used but not declared in the ### 3.1 catalog"
            ) in validate(_write(tmp_path, doc))


def test_lowercase_r_token_not_matched(tmp_path):
    # `r-kb` is not an R-id token -> no rule-7 violation.
    doc = _good_doc().replace(
        "  Fix: resolved by the OPS hardening sub-project.\n",
        "  Fix: resolved by OPS, see r-kb lower.\n", 1)
    assert validate(_write(tmp_path, doc)) == []


def test_declared_r_only_in_catalog_not_flagged(tmp_path):
    assert validate(_write(tmp_path)) == []


def test_r_token_in_catalog_noncol1_excluded_by_position(tmp_path):
    # R-EXTRA appears only in catalog col-2 prose; positional exclusion
    # must drop it (kills a _catalog_span -> None mutant). declared = col1.
    rows = ("| R-KB | KB also wraps R-EXTRA internally | Bedrock IaC |\n"
            "| R-AURORA-VEC | Aurora pgvector | Bedrock IaC |\n")
    assert validate(_write(tmp_path, _good_doc(rows))) == []


# --- rule 8: receipts real + SEC/REL real cfn-guard cite (BLOCKER-2) --

def test_cited_evidence_absent_exact(tmp_path):
    p = _write(tmp_path)
    (tmp_path / "_evidence" / "cfn-guard-agent.txt").unlink()
    assert ("cited evidence missing: "
            "_evidence/cfn-guard-agent.txt records ComplianceAgentStack"
            not in validate(p))  # the citation token stops at whitespace
    assert any(s == "cited evidence missing: _evidence/cfn-guard-agent.txt"
               for s in validate(p))


def test_receipt_is_stub_exact(tmp_path):
    p = _write(tmp_path, guard="STUB: n/a\n")
    assert ("cited evidence is a stub/placeholder: "
            "_evidence/cfn-guard-agent.txt") in validate(p)


def test_receipt_failed_fetch_sentinel(tmp_path):
    p = _write(tmp_path, guard="FAILED-FETCH upstream\n")
    assert ("cited evidence is a stub/placeholder: "
            "_evidence/cfn-guard-agent.txt") in validate(p)


def test_receipt_tbd_sentinel(tmp_path):
    p = _write(tmp_path, deferred="TBD operator step\n")
    assert ("cited evidence is a stub/placeholder: "
            "_evidence/cfn-guard-deferred.txt") in validate(p)


def test_receipt_empty_whitespace_exact(tmp_path):
    p = _write(tmp_path, guard="   \n")
    assert ("cited evidence empty: _evidence/cfn-guard-agent.txt"
            ) in validate(p)


def test_analyze_receipt_not_json_exact(tmp_path):
    p = _write(tmp_path, analyze="not json")
    assert ("_evidence/analyze-cdk-project.json: not valid JSON"
            ) in validate(p)


def test_analyze_receipt_empty_inventory_exact(tmp_path):
    p = _write(tmp_path, analyze="{}")
    assert ("_evidence/analyze-cdk-project.json: empty service inventory"
            ) in validate(p)


def test_sec_bare_cfn_guard_substring_not_accepted(tmp_path):
    f = _finding("SEC", 1, "cfn-guard- was unavailable so see kb_stack.py:1")
    doc = _good_doc().replace(_finding("SEC", 1, _PE["SEC"]), f)
    assert ("pillar SEC: must cite a _evidence/cfn-guard-*.txt receipt "
            "in a finding's Evidence:/Source: field") in validate(
                _write(tmp_path, doc))


def test_rel_must_cite_cfn_guard(tmp_path):
    f = _finding("REL", 1, "infra/stacks/runtime_stack.py:1")
    doc = _good_doc().replace(_finding("REL", 1, _PE["REL"]), f)
    assert ("pillar REL: must cite a _evidence/cfn-guard-*.txt receipt "
            "in a finding's Evidence:/Source: field") in validate(
                _write(tmp_path, doc))


def test_sec_cfn_guard_in_source_field_ok(tmp_path):
    f = (
        "GAP-SEC-1 [P1] x [P1|mixed|S]\n"
        "  Risk: r.\n"
        "  Evidence: infra/stacks/agent_stack.py:1\n"
        "  Why this matters here (NOT generic): w.\n"
        "  Source: see _evidence/cfn-guard-agent.txt\n"
        "  Counter-argument: c — false.\n"
        "  Fix: resolved by Bedrock IaC.\n"
    )
    doc = _good_doc().replace(_finding("SEC", 1, _PE["SEC"]), f)
    assert validate(_write(tmp_path, doc)) == []


def test_sec_cfn_guard_citation_unresolved_rejected(tmp_path):
    f = _finding("SEC", 1, "_evidence/cfn-guard-missing.txt")
    doc = _good_doc().replace(_finding("SEC", 1, _PE["SEC"]), f)
    assert ("pillar SEC: no cited cfn-guard receipt resolves "
            "(exists/non-empty/non-stub)") in validate(_write(tmp_path, doc))


def test_evidence_path_traversal_rejected_exact(tmp_path):
    doc = _good_doc().replace(
        "  Evidence: infra/stacks/observability_stack.py:10\n",
        "  Evidence: see _evidence/../../pyproject.toml\n", 1)
    assert ("cited evidence path escapes _evidence/: "
            "_evidence/../../pyproject.toml") in validate(
                _write(tmp_path, doc))


# --- fail-closed: missing doc / malformed catalog ----------------------

def test_missing_doc_is_violation_not_exception(tmp_path):
    missing = tmp_path / "nope.md"
    v = validate(missing)
    assert v == [f"prod-readiness audit not found: {missing}"]
    assert main([str(missing)]) == 1


def test_no_args_returns_one():
    assert main([]) == 1


def test_malformed_catalog_raises_then_main_returns_one(tmp_path):
    doc = _good_doc().replace(
        "| R-KB | Bedrock Knowledge Base | Bedrock IaC |",
        "| R-KB | only-two-cells |")
    p = _write(tmp_path, doc)
    with pytest.raises(ValueError):
        validate(p)
    assert main([str(p)]) == 1


def test_catalog_absent_raises(tmp_path):
    doc = _good_doc().replace("### 3.1 Resource catalog", "### 3.0 misc")
    with pytest.raises(ValueError):
        validate(_write(tmp_path, doc))


def test_catalog_header_only_no_data_rows_raises(tmp_path):
    with pytest.raises(ValueError):
        validate(_write(tmp_path, _good_doc(catalog_rows="")))


def test_catalog_no_valid_r_ids_raises(tmp_path):
    rows = "| KB | Bedrock Knowledge Base | Bedrock IaC |\n"
    with pytest.raises(ValueError):
        validate(_write(tmp_path, _good_doc(rows)))


def test_catalog_exactly_one_data_row_is_valid(tmp_path):
    # header + exactly 1 data row -> len(rows)==2, NOT < 2: must pass
    # (kills a `< 2` -> `<= 2` boundary mutant).
    rows = "| R-KB | Bedrock Knowledge Base | Bedrock IaC |\n"
    assert validate(_write(tmp_path, _good_doc(rows))) == []


# --- code-fence / prose false positives (MANDATORY) --------------------

def test_gap_token_only_in_code_fence_does_not_count(tmp_path):
    doc = _good_doc() + "\n```\nGAP-OPS-1 GAP-OPS-1 GAP-ZZZ-9\n```\n"
    assert validate(_write(tmp_path, doc)) == []


def test_r_token_only_in_code_fence_is_not_a_violation(tmp_path):
    doc = _good_doc() + "\n```\nexample uses R-FAKE-THING here\n```\n"
    assert validate(_write(tmp_path, doc)) == []


def test_tbd_inside_code_fence_is_not_a_violation(tmp_path):
    doc = _good_doc() + "\n```\n# sample: TBD TODO XXX example\n```\n"
    assert validate(_write(tmp_path, doc)) == []


def test_inline_code_placeholder_excluded(tmp_path):
    doc = _good_doc().replace(
        "## 1. Purpose & method\n",
        "## 1. Purpose & method\nsee the `TBD` token handling.\n")
    assert validate(_write(tmp_path, doc)) == []


def test_stray_placeholder_tbd_exact(tmp_path):
    doc = _good_doc().replace(
        "## 1. Purpose & method\n", "## 1. Purpose & method\nTBD finish.\n")
    assert "placeholder/unfinished marker present: 'TBD'" in validate(
        _write(tmp_path, doc))


def test_stray_placeholder_todo_exact(tmp_path):
    doc = _good_doc().replace(
        "## 1. Purpose & method\n", "## 1. Purpose & method\nTODO later.\n")
    assert "placeholder/unfinished marker present: 'TODO'" in validate(
        _write(tmp_path, doc))


def test_stray_placeholder_xxx_exact(tmp_path):
    doc = _good_doc().replace(
        "## 1. Purpose & method\n", "## 1. Purpose & method\nXXX hole.\n")
    assert "placeholder/unfinished marker present: 'XXX'" in validate(
        _write(tmp_path, doc))


def test_stray_placeholder_filled_in_task_exact(tmp_path):
    doc = _good_doc().replace(
        "## 1. Purpose & method\n",
        "## 1. Purpose & method\n_(filled in Task 4)_\n")
    assert ("placeholder/unfinished marker present: '_(filled in Task'"
            ) in validate(_write(tmp_path, doc))


def test_pillar_header_inside_fence_is_ignored(tmp_path):
    doc = _good_doc().replace(
        "## SEC — pillar\n" + _finding("SEC", 1, _PE["SEC"]) + "\n",
        "```\n## SEC — pillar\n```\n")
    assert "pillar section '## SEC' missing" in validate(
        _write(tmp_path, doc))


def test_unclosed_code_fence_does_not_silently_pass(tmp_path):
    doc = _good_doc().replace("## OPS — pillar", "```\n## OPS — pillar")
    assert validate(_write(tmp_path, doc)) != []


# --- pillar section at EOF ---------------------------------------------

def test_pillar_section_at_eof(tmp_path):
    base = _good_doc()
    ranked = base[base.index("## Ranked backlog"):]
    genai = "## GENAI — pillar\n" + _finding("GENAI", 1, _PE["GENAI"]) + "\n"
    doc = base.replace(ranked, "").replace(genai, "") + ranked + "\n" + genai
    v = validate(_write(tmp_path, doc))
    assert not any("## GENAI" in s and "missing" in s for s in v)


# --- parser units ------------------------------------------------------

def test_parse_catalog_returns_declared_ids():
    assert parse_catalog(_strip_fenced(_good_doc())) == {
        "R-KB", "R-AURORA-VEC"}


def test_parse_findings_attributes_to_section_pillar():
    fs = parse_findings(_strip_fenced(_good_doc()))
    assert {f.gap_id for f in fs} == {f"GAP-{p}-1" for p in PILLARS_T}
    assert [f for f in fs if f.pillar == "OPS"][0].complete()


def test_finding_complete_method():
    assert Finding("g", "OPS", {k: "x" for k in _SIX},
                   {k: 1 for k in _SIX}).complete()
    assert not Finding("g", "OPS", {k: "x" for k in _SIX},
                       {**{k: 1 for k in _SIX}, "Fix:": 2}).complete()
    assert not Finding("g", "OPS", {**{k: "x" for k in _SIX}, "Fix:": ""},
                       {k: 1 for k in _SIX}).complete()
