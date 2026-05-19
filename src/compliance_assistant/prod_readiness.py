"""Machine-check the evidence-backed prod-readiness audit document.

The Phase 6 deliverable is a Well-Architected Lens audit
(`docs/analysis/2026-05-16-compliance-prod-readiness.md`) plus saved
`_evidence/` receipts. That document is git-untracked working notes, so it
never enters the review-gate's judged diff — this checker, run by the gate's
regression leg against the working tree, is the *only* automated guard on the
audit's completeness and is therefore strict and fail-closed.

It mechanizes the integrity checks the spine backlog ran by hand (its Task 5
Step 3 six-field count and Task 7 Steps 2-3 placeholder + cross-reference
scans), in the deterministic, stdlib-only, fail-closed style of
`infra/stacks/slo_contract.py`: a malformed resource-catalog table raises
`ValueError`; every other shortfall is a returned violation string. `main`
exits non-zero (never a traceback) on any violation or a missing doc/receipt.

Grammar is pinned, not heuristic (a loose matcher breeds equivalent mutants):
- a pillar section header is exactly ``^## <PILLAR>`` (optionally ``— title``);
- the resource catalog is the pipe table under ``^### 3.1``;
- the ranked backlog is the table under ``^## Ranked backlog``;
- a finding header is ``^GAP-<PILLAR>-<n>``.
Fenced code blocks and inline-code spans are stripped before any token scan,
so a GAP/R/TBD token that appears only inside an example block does not
satisfy (or violate) a rule.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PILLARS: tuple[str, ...] = ("OPS", "SEC", "REL", "PERF", "COST", "SUS", "GENAI")

# The six Reasoning-Gate fields every gap must defend itself on
# (spine 2026-05-15-compliance-prod-hardening-spine.md:36-46).
SIX_FIELDS: tuple[str, ...] = (
    "Risk:",
    "Evidence:",
    "Why this matters here",
    "Source:",
    "Counter-argument:",
    "Fix:",
)

_PILLAR_ALT = "|".join(PILLARS)
_PILLAR_HEADER = re.compile(rf"^## ({_PILLAR_ALT})\b.*$", re.MULTILINE)
_CATALOG_HEADER = re.compile(r"^### 3\.1\b.*$", re.MULTILINE)
_RANKED_HEADER = re.compile(r"^## Ranked backlog\b.*$", re.MULTILINE)
_ANY_H2 = re.compile(r"^## .*$", re.MULTILINE)
_ANY_H3 = re.compile(r"^### .*$", re.MULTILINE)
_FINDING_HEADER = re.compile(rf"^GAP-({_PILLAR_ALT})-\d+\b", re.MULTILINE)
_GAP_TOKEN = re.compile(rf"\bGAP-(?:{_PILLAR_ALT})-\d+\b")
_R_TOKEN = re.compile(r"\bR-[A-Z0-9-]+\b")
_PLACEHOLDERS = ("TBD", "TODO", "XXX", "_(filled in Task")
_STUB_SENTINELS = ("STUB", "FAILED-FETCH", "TBD")
_NOT_A_GAP = "checked, not a gap because"
_ANALYZE_RECEIPT = "_evidence/analyze-cdk-project.json"
_CFN_GUARD_GLOB = "cfn-guard-"


@dataclass(frozen=True)
class Finding:
    gap_id: str
    pillar: str
    fields: dict[str, str]


def _strip_fenced(text: str) -> str:
    """Remove ```-fenced code blocks (their lines could otherwise be parsed
    as findings/tables). Inline code is kept so a backticked term inside a
    field value still parses."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def _strip_for_tokens(text: str) -> str:
    """For token-occurrence rules: drop fenced blocks AND inline-code spans
    so a GAP/R/TBD token that appears only inside example code is neither a
    satisfied cross-reference nor a placeholder violation."""
    no_fence = _strip_fenced(text)
    return re.sub(r"`[^`]*`", "", no_fence)


def _sections(stripped: str) -> dict[str, str]:
    """Pillar token -> that ``## <PILLAR>`` section body (header to the next
    ``## `` of any kind)."""
    bounds: list[tuple[int, int, str | None]] = []
    for m in _ANY_H2.finditer(stripped):
        pm = _PILLAR_HEADER.match(stripped, m.start())
        bounds.append((m.start(), m.end(), pm.group(1) if pm else None))
    out: dict[str, str] = {}
    for i, (start, end, pillar) in enumerate(bounds):
        if pillar is None:
            continue
        nxt = bounds[i + 1][0] if i + 1 < len(bounds) else len(stripped)
        out[pillar] = stripped[end:nxt]
    return out


def _table_rows(block: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= {"-", ":"} for c in cells):
            continue  # |---|:--:| separator row
        rows.append(cells)
    return rows


def _section_after(stripped: str, header: re.Pattern[str],
                    stop: re.Pattern[str]) -> str:
    m = header.search(stripped)
    if m is None:
        return ""
    nxt = stop.search(stripped, m.end())
    return stripped[m.end():nxt.start() if nxt else len(stripped)]


def parse_catalog(stripped: str) -> set[str]:
    """Declared R-* ids = column 1 of the table under ``### 3.1``.
    Fail-closed: a present-but-empty catalog is a malformed doc."""
    block = _section_after(stripped, _CATALOG_HEADER, _ANY_H3)
    if not _CATALOG_HEADER.search(stripped):
        raise ValueError("resource catalog (### 3.1) section not found")
    rows = _table_rows(block)
    if len(rows) < 2:  # header row + >=1 data row
        raise ValueError("### 3.1 resource catalog has no data rows")
    declared: set[str] = set()
    for cells in rows[1:]:
        if len(cells) < 3:
            raise ValueError(
                f"### 3.1 row needs >=3 cells (| R-ID | Resource | "
                f"Source |), got {cells}"
            )
        rid = cells[0]
        if _R_TOKEN.fullmatch(rid):
            declared.add(rid)
    if not declared:
        raise ValueError("### 3.1 declares no valid R-* ids")
    return declared


def parse_findings(stripped: str) -> list[Finding]:
    """Each ``GAP-<PILLAR>-n`` block, attributed to the pillar section it
    sits in, with its six indented ``Field:`` values."""
    sections = _sections(stripped)
    findings: list[Finding] = []
    for pillar, body in sections.items():
        starts = [m.start() for m in _FINDING_HEADER.finditer(body)]
        for i, s in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(body)
            block = body[s:end]
            gap_id = block.split()[0]
            # Position-based slice: a field's value runs from the end of its
            # label to the start of the next *present* label (by position).
            # Robust where a regex lookahead is not: "Counter-argument:"
            # has a hyphen, "Why this matters here" has no colon.
            present = sorted(
                (block.find(label), label)
                for label in SIX_FIELDS if block.find(label) >= 0
            )
            fields: dict[str, str] = {label: "" for label in SIX_FIELDS}
            for j, (idx, label) in enumerate(present):
                val_start = idx + len(label)
                val_end = (
                    present[j + 1][0] if j + 1 < len(present) else len(block)
                )
                fields[label] = block[val_start:val_end].strip()
            findings.append(Finding(gap_id, pillar, fields))
    return findings


def _rule_pillars_present(sections: dict[str, str]) -> list[str]:
    return [
        f"pillar section '## {p}' missing"
        for p in PILLARS if p not in sections
    ]


def _rule_pillar_defended(
    sections: dict[str, str], findings: list[Finding]
) -> list[str]:
    by_pillar: dict[str, list[Finding]] = {p: [] for p in PILLARS}
    for f in findings:
        by_pillar.setdefault(f.pillar, []).append(f)
    out: list[str] = []
    for p in PILLARS:
        if p not in sections:
            continue
        complete = [
            f for f in by_pillar[p]
            if all(f.fields[k] for k in SIX_FIELDS)
        ]
        if complete:
            continue
        body = sections[p]
        if _NOT_A_GAP in body:
            idx = body.index(_NOT_A_GAP)
            window = body[idx:idx + 600]
            if "Source:" in window or "Evidence:" in window:
                continue
            out.append(
                f"pillar {p}: 'checked, not a gap because' carries no "
                f"Source:/Evidence: reference"
            )
        else:
            out.append(
                f"pillar {p}: no complete six-field finding and no "
                f"'checked, not a gap because' statement"
            )
    return out


def _rule_cost_sus_cite_receipt(sections: dict[str, str]) -> list[str]:
    out: list[str] = []
    for p in ("COST", "SUS"):
        body = sections.get(p, "")
        if _ANALYZE_RECEIPT not in body:
            out.append(
                f"pillar {p}: must cite {_ANALYZE_RECEIPT} (the spine "
                f"deferral is closed only with the service-inventory "
                f"receipt, not by assertion)"
            )
    return out


def _rule_six_fields(findings: list[Finding]) -> list[str]:
    out: list[str] = []
    for f in findings:
        missing = [k for k in SIX_FIELDS if not f.fields[k]]
        if missing:
            out.append(f"{f.gap_id}: missing/empty field(s) {missing}")
    return out


def _rule_no_placeholder(tokens_text: str) -> list[str]:
    return [
        f"placeholder/unfinished marker present: {ph!r}"
        for ph in _PLACEHOLDERS if ph in tokens_text
    ]


def _rule_gap_twice(
    findings: list[Finding], stripped: str
) -> list[str]:
    """Every GAP id must occur in a pillar-section finding header AND in a
    ranked-table row (>= 2 real occurrences; prose/code excluded)."""
    ranked = _section_after(stripped, _RANKED_HEADER, _ANY_H2)
    ranked_ids = {
        t for row in _table_rows(ranked) for cell in row
        for t in _GAP_TOKEN.findall(cell)
    }
    finding_ids = {f.gap_id for f in findings}
    out: list[str] = []
    for gid in sorted(finding_ids | ranked_ids):
        in_finding = gid in finding_ids
        in_ranked = gid in ranked_ids
        if not (in_finding and in_ranked):
            out.append(
                f"{gid}: must appear in both a pillar finding and the "
                f"ranked backlog (finding={in_finding}, ranked={in_ranked})"
            )
    return out


def _rule_r_declared(stripped: str, declared: set[str]) -> list[str]:
    catalog_block = _section_after(stripped, _CATALOG_HEADER, _ANY_H3)
    used: set[str] = set()
    for m in _R_TOKEN.finditer(stripped):
        if m.group(0) in catalog_block:
            continue
        used.add(m.group(0))
    return [
        f"{rid}: used but not declared in the ### 3.1 catalog"
        for rid in sorted(used - declared)
    ]


def _rule_receipts_real(doc_path: Path, stripped: str,
                        sections: dict[str, str]) -> list[str]:
    """Every cited ``_evidence/*`` resolves, is non-empty, non-stub;
    analyze-cdk-project.json is valid non-empty JSON; SEC and REL each cite
    a cfn-guard receipt so this check covers it."""
    out: list[str] = []
    base = doc_path.parent
    cited = sorted(set(re.findall(r"_evidence/[\w.\-/]+", stripped)))
    for rel in cited:
        p = base / rel
        if not p.is_file():
            out.append(f"cited evidence missing: {rel}")
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        if not body.strip():
            out.append(f"cited evidence empty: {rel}")
            continue
        if any(s in body for s in _STUB_SENTINELS):
            out.append(f"cited evidence is a stub/placeholder: {rel}")
            continue
        if rel.endswith("analyze-cdk-project.json"):
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                out.append(f"{rel}: not valid JSON")
                continue
            if not data:
                out.append(f"{rel}: empty service inventory")
    for p in ("SEC", "REL"):
        body = sections.get(p, "")
        if _CFN_GUARD_GLOB not in body:
            out.append(
                f"pillar {p}: must cite a _evidence/cfn-guard-*.txt receipt"
            )
    return out


def validate(doc_path: str | Path) -> list[str]:
    """Return every violation (empty == the audit is structurally whole).
    A missing doc is one violation, not an exception, so `main` exits 1
    cleanly. A malformed ### 3.1 table raises ValueError (fail-closed)."""
    p = Path(doc_path)
    if not p.is_file():
        return [f"prod-readiness audit not found: {p}"]
    raw = p.read_text(encoding="utf-8")
    stripped = _strip_fenced(raw)
    tokens_text = _strip_for_tokens(raw)
    declared = parse_catalog(stripped)
    sections = _sections(stripped)
    findings = parse_findings(stripped)
    violations: list[str] = []
    violations += _rule_pillars_present(sections)
    violations += _rule_pillar_defended(sections, findings)
    violations += _rule_cost_sus_cite_receipt(sections)
    violations += _rule_six_fields(findings)
    violations += _rule_no_placeholder(tokens_text)
    violations += _rule_gap_twice(findings, stripped)
    violations += _rule_r_declared(stripped, declared)
    violations += _rule_receipts_real(p, stripped, sections)
    return violations


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python -m compliance_assistant.prod_readiness <doc>",
              file=sys.stderr)
        return 1
    try:
        violations = validate(args[0])
    except ValueError as exc:
        print(f"prod-readiness audit malformed: {exc}", file=sys.stderr)
        return 1
    for v in violations:
        print(v, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
