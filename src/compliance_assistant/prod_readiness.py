"""Machine-check the evidence-backed prod-readiness audit document.

The Phase 6 deliverable is a Well-Architected Lens audit
(`docs/analysis/2026-05-16-compliance-prod-readiness.md`) plus saved
`_evidence/` receipts. That document is git-untracked working notes, so it
never enters the review-gate's judged diff — this checker, run by the gate's
regression leg against the working tree, is the *only* automated guard on the
audit's completeness. Every rule is therefore fail-CLOSED, never fail-open.

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
- a finding header is ``^GAP-<PILLAR>-<n>``;
- a Reasoning-Gate field is detected ONLY at line start (after indentation),
  never by an unanchored substring search, and must occur exactly once.
Fenced code blocks and inline-code spans are stripped before any token scan,
so a GAP/R/TBD token that appears only inside an example block does not
satisfy (or violate) a rule. Every cited ``_evidence/`` path is resolved
through one resolver that enforces containment under the doc's
``_evidence/`` directory (no traversal), non-empty, non-stub, JSON-valid.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PILLARS: tuple[str, ...] = ("OPS", "SEC", "REL", "PERF", "COST", "SUS", "GENAI")

# The six Reasoning-Gate fields every gap must defend itself on
# (spine 2026-05-15-compliance-prod-hardening-spine.md:36-46). Order is the
# canonical document order; detection is line-anchored, not positional.
SIX_FIELDS: tuple[str, ...] = (
    "Risk:",
    "Evidence:",
    "Why this matters here",
    "Source:",
    "Counter-argument:",
    "Fix:",
)
_EVIDENCE_FIELDS = ("Evidence:", "Source:")

_PILLAR_ALT = "|".join(PILLARS)
_PILLAR_HEADER = re.compile(rf"^## ({_PILLAR_ALT})\b.*$", re.MULTILINE)
_CATALOG_HEADER = re.compile(r"^### 3\.1\b.*$", re.MULTILINE)
_RANKED_HEADER = re.compile(r"^## Ranked backlog\b.*$", re.MULTILINE)
_ANY_H2 = re.compile(r"^## .*$", re.MULTILINE)
_ANY_H3 = re.compile(r"^### .*$", re.MULTILINE)
_FINDING_HEADER = re.compile(rf"^GAP-(?:{_PILLAR_ALT})-\d+\b", re.MULTILINE)
_GAP_TOKEN = re.compile(rf"\bGAP-(?:{_PILLAR_ALT})-\d+\b")
# Strict R-id boundary: not preceded or followed by an id char, so
# `R-AURORA` in prose is NOT a prefix-match of catalog `R-AURORA-VEC`.
_R_TOKEN = re.compile(r"(?<![A-Za-z0-9-])R-[A-Z0-9-]+(?![A-Za-z0-9-])")
_R_FULL = re.compile(r"R-[A-Z0-9-]+")
_EVIDENCE_CITE = re.compile(r"_evidence/[A-Za-z0-9._\-/]+")
_CFN_GUARD_CITE = re.compile(r"_evidence/cfn-guard-[A-Za-z0-9._\-]+\.txt")
_ANALYZE_RECEIPT = "_evidence/analyze-cdk-project.json"
_PLACEHOLDERS = ("TBD", "TODO", "XXX", "_(filled in Task")
_STUB_SENTINELS = ("STUB", "FAILED-FETCH", "TBD")
_NOT_A_GAP = re.compile(r"^\s*checked, not a gap because\b", re.MULTILINE)


@dataclass(frozen=True)
class Finding:
    gap_id: str
    pillar: str
    fields: dict[str, str]
    counts: dict[str, int]

    def complete(self) -> bool:
        return all(
            self.counts[k] == 1 and self.fields[k] for k in SIX_FIELDS
        )


def _strip_fenced(text: str) -> str:
    """Remove ```-fenced code blocks (their lines could otherwise be parsed
    as findings/tables). Inline code is kept so a backticked path inside a
    field value still resolves and parses."""
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
    """For token-occurrence rules (placeholder / GAP >=2x / R-declared):
    drop fenced blocks AND inline-code spans so a GAP/R/TBD token that
    appears only inside example code is neither satisfied nor violated."""
    return re.sub(r"`[^`]*`", "", _strip_fenced(text))


def _line_label(line: str) -> str | None:
    """The Reasoning-Gate field a line *starts* (after indentation), or
    None. Line-anchored on purpose: a value that merely mentions
    ``Source:`` mid-sentence is not a field (closes the str.find collision
    that let an empty terminal field be filled by borrowed text)."""
    s = line.lstrip()
    for lab in SIX_FIELDS:
        if s.startswith(lab):
            return lab
    return None


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


def _catalog_span(text: str) -> tuple[int, int] | None:
    m = _CATALOG_HEADER.search(text)
    if m is None:
        return None
    nxt = _ANY_H3.search(text, m.end())
    return (m.start(), nxt.start() if nxt else len(text))


def _section_after(text: str, header: re.Pattern[str],
                    stop: re.Pattern[str]) -> str:
    m = header.search(text)
    if m is None:
        return ""
    nxt = stop.search(text, m.end())
    return text[m.end():nxt.start() if nxt else len(text)]


def parse_catalog(stripped: str) -> set[str]:
    """Declared R-* ids = column 1 of the table under ``### 3.1``.
    Fail-closed: missing section / header-only / no valid R-id raises."""
    if not _CATALOG_HEADER.search(stripped):
        raise ValueError("resource catalog (### 3.1) section not found")
    block = _section_after(stripped, _CATALOG_HEADER, _ANY_H3)
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
        if _R_FULL.fullmatch(rid):
            declared.add(rid)
    if not declared:
        raise ValueError("### 3.1 declares no valid R-* ids")
    return declared


def _finding_blocks(body: str) -> list[tuple[str, str]]:
    starts = [m.start() for m in _FINDING_HEADER.finditer(body)]
    out: list[tuple[str, str]] = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(body)
        block = body[s:end]
        out.append((block.split()[0], block))
    return out


def _parse_block_fields(block: str) -> tuple[dict[str, str], dict[str, int]]:
    """Line-anchored field parse. A field begins only on a line that starts
    (after indentation) with its label; its value runs to the next field
    line. Each label's occurrence count is tracked so 'exactly one of each'
    is enforceable (a duplicate or missing label is a violation)."""
    fields: dict[str, list[str]] = {k: [] for k in SIX_FIELDS}
    counts: dict[str, int] = {k: 0 for k in SIX_FIELDS}
    current: str | None = None
    for line in block.splitlines():
        lab = _line_label(line)
        if lab is not None:
            counts[lab] += 1
            current = lab
            rest = line.lstrip()[len(lab):]
            fields[lab].append(rest)
            continue
        if current is not None:
            fields[current].append(line)
    return ({k: "\n".join(v).strip() for k, v in fields.items()}, counts)


def parse_findings(stripped: str) -> list[Finding]:
    findings: list[Finding] = []
    for pillar, body in _sections(stripped).items():
        for gap_id, block in _finding_blocks(body):
            f, c = _parse_block_fields(block)
            findings.append(Finding(gap_id, pillar, f, c))
    return findings


def _resolve_receipt(base: Path, rel: str) -> str | None:
    """Resolve a cited ``_evidence/<x>`` path fail-closed: it must stay
    inside ``<doc dir>/_evidence`` (no traversal), exist, be non-empty,
    carry no stub sentinel, and (for the analyze receipt) be non-empty
    JSON. Returns a violation string or None."""
    ev_root = (base / "_evidence").resolve()
    target = (base / rel).resolve()
    if target != ev_root and ev_root not in target.parents:
        return f"cited evidence path escapes _evidence/: {rel}"
    if not target.is_file():
        return f"cited evidence missing: {rel}"
    body = target.read_text(encoding="utf-8", errors="replace")
    if not body.strip():
        return f"cited evidence empty: {rel}"
    if any(s in body for s in _STUB_SENTINELS):
        return f"cited evidence is a stub/placeholder: {rel}"
    if rel.endswith("analyze-cdk-project.json"):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return f"{rel}: not valid JSON"
        if not data:
            return f"{rel}: empty service inventory"
    return None


def _rule_pillars_present(sections: dict[str, str]) -> list[str]:
    return [
        f"pillar section '## {p}' missing"
        for p in PILLARS if p not in sections
    ]


def _rule_pillar_defended(
    sections: dict[str, str], findings: list[Finding], base: Path
) -> list[str]:
    by_pillar: dict[str, list[Finding]] = {p: [] for p in PILLARS}
    for f in findings:
        by_pillar.setdefault(f.pillar, []).append(f)
    out: list[str] = []
    for p in PILLARS:
        if p not in sections:
            continue
        if any(f.complete() for f in by_pillar[p]):
            continue
        body = sections[p]
        m = _NOT_A_GAP.search(body)
        if m is None:
            out.append(
                f"pillar {p}: no complete six-field finding and no "
                f"'checked, not a gap because' statement"
            )
            continue
        # The dismissal unit: from the phrase to the next blank line /
        # finding / section. It must itself carry a non-empty Evidence:
        # or Source: field; a cited _evidence/ is resolved.
        unit_lines: list[str] = []
        for line in body[m.start():].splitlines():
            if unit_lines and (not line.strip()
                               or _FINDING_HEADER.match(line)):
                break
            unit_lines.append(line)
        unit = "\n".join(unit_lines)
        ev_val = ""
        for line in unit.splitlines():
            lab = _line_label(line)
            if lab in _EVIDENCE_FIELDS:
                ev_val = line.lstrip()[len(lab):].strip()
                break
        if not ev_val:
            out.append(
                f"pillar {p}: 'checked, not a gap because' carries no "
                f"non-empty Source:/Evidence: reference"
            )
            continue
        for rel in _EVIDENCE_CITE.findall(unit):
            err = _resolve_receipt(base, rel)
            if err:
                out.append(f"pillar {p} dismissal: {err}")
    return out


def _rule_cost_sus_evidence(findings: list[Finding]) -> list[str]:
    out: list[str] = []
    for p in ("COST", "SUS"):
        pf = [f for f in findings if f.pillar == p]
        ok = any(
            f.counts["Evidence:"] == 1
            and _ANALYZE_RECEIPT in f.fields["Evidence:"]
            for f in pf
        )
        if not ok:
            out.append(
                f"pillar {p}: needs a finding citing {_ANALYZE_RECEIPT} "
                f"in its Evidence: field (spine deferral is closed with "
                f"the receipt, not by assertion)"
            )
    return out


def _rule_six_fields(findings: list[Finding]) -> list[str]:
    out: list[str] = []
    for f in findings:
        for k in SIX_FIELDS:
            if f.counts[k] == 0 or not f.fields[k]:
                out.append(f"{f.gap_id}: missing/empty field {k!r}")
            elif f.counts[k] > 1:
                out.append(
                    f"{f.gap_id}: field {k!r} appears {f.counts[k]}x "
                    f"(exactly one required)"
                )
    return out


def _rule_no_placeholder(tokens_text: str) -> list[str]:
    return [
        f"placeholder/unfinished marker present: {ph!r}"
        for ph in _PLACEHOLDERS if ph in tokens_text
    ]


def _rule_gap_twice(
    findings: list[Finding], tokens_text: str
) -> list[str]:
    ranked = _section_after(tokens_text, _RANKED_HEADER, _ANY_H2)
    ranked_ids = {
        t for row in _table_rows(ranked) for cell in row
        for t in _GAP_TOKEN.findall(cell)
    }
    finding_ids = {f.gap_id for f in findings}
    out: list[str] = []
    for gid in sorted(finding_ids | ranked_ids):
        in_f = gid in finding_ids
        in_r = gid in ranked_ids
        if not (in_f and in_r):
            out.append(
                f"{gid}: must appear in both a pillar finding and the "
                f"ranked backlog (finding={in_f}, ranked={in_r})"
            )
    return out


def _rule_r_declared(tokens_text: str, declared: set[str]) -> list[str]:
    span = _catalog_span(tokens_text)
    used: set[str] = set()
    for m in _R_TOKEN.finditer(tokens_text):
        if span is not None and span[0] <= m.start() < span[1]:
            continue  # declared inside the §3.1 catalog (by position)
        used.add(m.group(0))
    return [
        f"{rid}: used but not declared in the ### 3.1 catalog"
        for rid in sorted(used - declared)
    ]


def _rule_receipts_real(base: Path, stripped: str,
                        findings: list[Finding]) -> list[str]:
    out: list[str] = []
    for rel in sorted(set(_EVIDENCE_CITE.findall(stripped))):
        err = _resolve_receipt(base, rel)
        if err:
            out.append(err)
    # SEC and REL must each cite a real, resolvable cfn-guard receipt in a
    # finding's Evidence:/Source: field — not a bare 'cfn-guard-' substring.
    for p in ("SEC", "REL"):
        cited: list[str] = []
        for f in findings:
            if f.pillar != p:
                continue
            for fld in _EVIDENCE_FIELDS:
                if f.counts[fld] == 1:
                    cited += _CFN_GUARD_CITE.findall(f.fields[fld])
        if not cited:
            out.append(
                f"pillar {p}: must cite a _evidence/cfn-guard-*.txt receipt "
                f"in a finding's Evidence:/Source: field"
            )
            continue
        if all(_resolve_receipt(base, c) is not None for c in cited):
            out.append(
                f"pillar {p}: no cited cfn-guard receipt resolves "
                f"(exists/non-empty/non-stub)"
            )
    return out


def validate(doc_path: str | Path) -> list[str]:
    """Return every violation (empty == the audit is structurally whole).
    A missing doc is one violation, not an exception, so `main` exits 1
    cleanly. A malformed ### 3.1 table raises ValueError (fail-closed)."""
    p = Path(doc_path)
    if not p.is_file():
        return [f"prod-readiness audit not found: {p}"]
    base = p.parent
    raw = p.read_text(encoding="utf-8")
    stripped = _strip_fenced(raw)
    tokens_text = _strip_for_tokens(raw)
    declared = parse_catalog(stripped)
    sections = _sections(stripped)
    findings = parse_findings(stripped)
    v: list[str] = []
    v += _rule_pillars_present(sections)
    v += _rule_pillar_defended(sections, findings, base)
    v += _rule_cost_sus_evidence(findings)
    v += _rule_six_fields(findings)
    v += _rule_no_placeholder(tokens_text)
    v += _rule_gap_twice(findings, tokens_text)
    v += _rule_r_declared(tokens_text, declared)
    v += _rule_receipts_real(base, stripped, findings)
    return v


def main(argv: list[str] | None = None) -> int:
    import sys
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
