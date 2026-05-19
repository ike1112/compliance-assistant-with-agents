"""Machine-check the evidence-backed prod-readiness audit document.

The audit (`docs/analysis/2026-05-16-compliance-prod-readiness.md`) plus its
saved `_evidence/` receipts are git-untracked working notes, so they never
enter the review gate's judged diff — this checker, run by the gate's
regression leg against the working tree, is the *only* automated guard on
the audit's completeness. Every rule is therefore fail-CLOSED.

It mechanizes, deterministically and stdlib-only, the checks the
production-hardening spine backlog performed by hand: the per-gap
six-field count, the placeholder scan, and the GAP/R cross-reference
scans — in the fail-closed style of `infra/stacks/slo_contract.py`
(a malformed resource-catalog table raises `ValueError`; every other
shortfall is a returned violation string; `main` exits non-zero, never a
traceback, on any violation or a missing doc/receipt).

Pinned grammar (a loose matcher breeds equivalent mutants and fail-open
holes):
- a pillar section header is exactly ``^## <PILLAR>`` (optionally ``— x``);
- the resource catalog is the pipe table under ``^### 3.1``; an R-id is
  "declared" only as column 1 of a catalog table-ROW (catalog prose does
  not declare); there is no positional exclusion — every R-id used
  anywhere that is not in the declared set is flagged;
- the ranked backlog is the table under ``^## Ranked backlog``;
- a finding header is ``^GAP-<PILLAR>-<n>``;
- a Reasoning-Gate field is detected ONLY at line start (after
  indentation) and must occur exactly once;
- a finding's ``Evidence:`` must carry at least one *checkable* pointer —
  a `_evidence/<name>` citation that resolves, or a `path.ext:line` repo
  reference — never bare prose; no ``Evidence:``/``Source:`` token may be
  an escaping/absolute path (`..`, leading `/`, drive, UNC);
- COST and SUS must cite the exact analyze-cdk-project receipt token.
Fenced code blocks and inline-code spans are stripped before any token
scan. Every `_evidence/` path is resolved through one resolver that
enforces containment under the doc's `_evidence/` directory.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

PILLARS: tuple[str, ...] = ("OPS", "SEC", "REL", "PERF", "COST", "SUS", "GENAI")

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
# Strict R-id boundary: `R-AURORA` in prose is not a prefix-match of a
# catalog `R-AURORA-VEC`.
_R_TOKEN = re.compile(r"(?<![A-Za-z0-9-])R-[A-Z0-9-]+(?![A-Za-z0-9-])")
_R_FULL = re.compile(r"R-[A-Z0-9-]+")
# A citation ends on an id char (no trailing sentence punctuation).
_EVIDENCE_CITE = re.compile(r"_evidence/[A-Za-z0-9._\-/]*[A-Za-z0-9_\-/]")
# A concrete repo reference: a real PATH (>=1 `/`) ending file.ext:line.
# The path/segment classes carry no `.` so they cannot overlap the literal
# `\.` extension dot — linear time, no catastrophic backtracking, and a
# bare prose token like `a.b:1` (no `/`) is rejected as not-a-pointer.
_REPO_REF = re.compile(r"\b[\w\-]+(?:/[\w\-]+)+\.\w+:\d+\b")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# The COST/SUS receipt, exact token (rejects analyze-...json.bak / suffix).
_ANALYZE_EXACT = re.compile(
    r"(?<![\w./\-])_evidence/analyze-cdk-project\.json(?![\w.\-])")
_ANALYZE_REL = "_evidence/analyze-cdk-project.json"
_CFN_GUARD_CITE = re.compile(r"_evidence/cfn-guard-[A-Za-z0-9._\-]+\.txt")
_PLACEHOLDERS = ("TBD", "TODO", "XXX", "_(filled in Task")
_STUB_SENTINELS = ("STUB", "FAILED-FETCH", "TBD")
_NOT_A_GAP = re.compile(r"^\s*checked, not a gap because\b", re.MULTILINE)
# An escaping / absolute / drive / UNC path token (never valid evidence).
# `[A-Za-z]:` (no required separator) also catches drive-relative `C:1`.
_ESCAPE = re.compile(r"(^|[\\/])\.\.([\\/]|$)")
_ABSOLUTE = re.compile(r"^(/|\\\\|[A-Za-z]:)")


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
    return re.sub(r"`[^`]*`", "", _strip_fenced(text))


def _line_label(line: str) -> str | None:
    s = line.lstrip()
    for lab in SIX_FIELDS:
        if s.startswith(lab):
            return lab
    return None


def _cites(text: str) -> list[str]:
    """Cited `_evidence/<x>` tokens, trailing sentence punctuation
    trimmed (the regex already ends on an id char, this is belt-and-
    braces)."""
    return [c.rstrip(".,;:)") for c in _EVIDENCE_CITE.findall(text)]


def _sections(stripped: str) -> dict[str, str]:
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


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|")


def _table_rows(block: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in block.splitlines():
        if not _is_table_row(raw):
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        if all(set(c) <= {"-", ":"} for c in cells):
            continue  # |---|:--:| separator row
        rows.append(cells)
    return rows


def _catalog_block(text: str) -> str:
    return _section_after(text, _CATALOG_HEADER, _ANY_H3)


def _section_after(text: str, header: re.Pattern[str],
                    stop: re.Pattern[str]) -> str:
    m = header.search(text)
    if m is None:
        return ""
    nxt = stop.search(text, m.end())
    return text[m.end():nxt.start() if nxt else len(text)]


def parse_catalog(stripped: str) -> set[str]:
    if not _CATALOG_HEADER.search(stripped):
        raise ValueError("resource catalog (### 3.1) section not found")
    rows = _table_rows(_catalog_block(stripped))
    if len(rows) < 2:  # header row + >=1 data row
        raise ValueError("### 3.1 resource catalog has no data rows")
    declared: set[str] = set()
    for cells in rows[1:]:
        if len(cells) < 3:
            raise ValueError(
                f"### 3.1 row needs >=3 cells (| R-ID | Resource | "
                f"Source |), got {cells}"
            )
        if _R_FULL.fullmatch(cells[0]):
            declared.add(cells[0])
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
    fields: dict[str, list[str]] = {k: [] for k in SIX_FIELDS}
    counts: dict[str, int] = {k: 0 for k in SIX_FIELDS}
    current: str | None = None
    for line in block.splitlines():
        lab = _line_label(line)
        if lab is not None:
            counts[lab] += 1
            current = lab
            fields[lab].append(line.lstrip()[len(lab):])
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


def _escaping_tokens(field_val: str) -> list[str]:
    bad: list[str] = []
    for tok in field_val.split():
        t = tok.strip("`*()[],;")
        if not t:
            continue
        # Decode percent-encoded separators/dots so an encoded traversal
        # (`%2E%2E%2F`) cannot slip past the `..`/absolute guards. The
        # single pass is deliberate: recursive unquote is itself a
        # decode-bomb vector, and this guard is defense-in-depth — the
        # enforced containment control is `_resolve_receipt`.
        dec = unquote(t)
        if (_ESCAPE.search(t) or _ABSOLUTE.match(t)
                or _ESCAPE.search(dec) or _ABSOLUTE.match(dec)):
            bad.append(t)
    return bad


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
        for rel in _cites(unit):
            err = _resolve_receipt(base, rel)
            if err:
                out.append(f"pillar {p} dismissal: {err}")
    return out


def _rule_evidence_anchored(
    findings: list[Finding], base: Path
) -> list[str]:
    """Every finding's Evidence: must carry a checkable pointer (a
    resolvable _evidence/ citation or a path.ext:line repo ref), and no
    Evidence:/Source: token may be an escaping/absolute path."""
    out: list[str] = []
    for f in findings:
        if f.counts["Evidence:"] == 1:
            ev = f.fields["Evidence:"]
            resolved = any(
                _resolve_receipt(base, c) is None for c in _cites(ev)
            )
            if not (resolved or _REPO_REF.search(ev)):
                out.append(
                    f"{f.gap_id}: Evidence: has no checkable reference "
                    f"(need a resolvable _evidence/ citation or a "
                    f"path.ext:line repo ref)"
                )
        for fld in _EVIDENCE_FIELDS:
            if f.counts[fld] != 1:
                continue
            for tok in _escaping_tokens(f.fields[fld]):
                out.append(
                    f"{f.gap_id}: {fld} has an escaping/absolute path "
                    f"token {tok!r}"
                )
    return out


def _rule_cost_sus_evidence(
    findings: list[Finding], base: Path
) -> list[str]:
    out: list[str] = []
    for p in ("COST", "SUS"):
        ok = False
        for f in findings:
            if f.pillar != p or f.counts["Evidence:"] != 1:
                continue
            if _ANALYZE_EXACT.search(f.fields["Evidence:"]) and \
                    _resolve_receipt(base, _ANALYZE_REL) is None:
                ok = True
                break
        if not ok:
            out.append(
                f"pillar {p}: needs a finding citing the exact "
                f"{_ANALYZE_REL} receipt in its Evidence: field "
                f"(spine deferral is closed with the receipt, not by "
                f"assertion)"
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
    """Every R-id used anywhere must be declared in the §3.1 catalog.
    No positional exclusion: a declared id (column 1 of a catalog row) is
    in `declared` so it never self-flags, while an undeclared id is caught
    wherever it appears — catalog prose, a catalog non-id cell, or a
    finding. Closes both the prose-escape and the non-id-cell hole."""
    used = {m.group(0) for m in _R_TOKEN.finditer(tokens_text)}
    return [
        f"{rid}: used but not declared in the ### 3.1 catalog"
        for rid in sorted(used - declared)
    ]


def _rule_receipts_real(base: Path, stripped: str,
                        findings: list[Finding]) -> list[str]:
    out: list[str] = []
    for rel in sorted(set(_cites(stripped))):
        err = _resolve_receipt(base, rel)
        if err:
            out.append(err)
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
    # Strip HTML comments first so a token hidden in `<!-- ... -->`
    # (e.g. a faked analyze-receipt citation) never counts anywhere.
    raw = _HTML_COMMENT.sub("", p.read_text(encoding="utf-8"))
    # Fail closed on a comment marker that survived the single strip pass:
    # a nested `<!-- a <!-- b --> tok -->` or an unterminated `<!-- tok`
    # would otherwise leak `tok` into the scan. Mirrors the §3.1 raise.
    if "<!--" in raw or "-->" in raw:
        raise ValueError("malformed/nested/unterminated HTML comment")
    stripped = _strip_fenced(raw)
    tokens_text = _strip_for_tokens(raw)
    declared = parse_catalog(stripped)
    sections = _sections(stripped)
    findings = parse_findings(stripped)
    v: list[str] = []
    v += _rule_pillars_present(sections)
    v += _rule_pillar_defended(sections, findings, base)
    v += _rule_evidence_anchored(findings, base)
    v += _rule_cost_sus_evidence(findings, base)
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
