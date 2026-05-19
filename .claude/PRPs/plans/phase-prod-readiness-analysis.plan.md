# Feature: Evidence-backed prod-readiness analysis (WA-Lens audit of the synthesized stack)

> **Revision note (post adversarial plan review).** Hardened to resolve the
> codex-rescue BLOCKER + MAJORs and code-reviewer MAJOR-A..D before any build:
> (BLOCKER) required `_evidence/` receipts must be real/non-stub and the
> checker (rule 8) verifies every cited receipt resolves, is non-empty, and is
> parseable — no stub-and-pass; (MAJOR) COST/SUS must cite
> `_evidence/analyze-cdk-project.json` (rule 3) and every "checked, not a gap"
> must carry an evidence/source ref (rule 2) — the spine deferral cannot be
> closed by assertion; (MAJOR) Task 1 now pins the literal pillar/§3.1/ranked
> grammar and strips code-fences/prose before token scans, with mandatory
> false-positive fixtures in Task 2, so the 0.80 mutation floor is reachable;
> (MAJOR) the `git status --porcelain docs/ == ??` assertion was factually
> wrong (`.gitignore:7` `docs/*`) — restated as the correct gitignored-and-
> not-staged invariant in Validation/Level 3/Task 6/Task 7/Acceptance;
> (MAJOR) Task 7 reduced to verify-only since the PRD row was already set
> `in-progress` at plan time. The Validation section remains a verbatim
> reproduction of Phase 6's PRD `CHECK:` items and was **not** altered by this
> revision.

## Summary

The five hardening sub-projects are built and synth-green. This phase produces
the **post-build full audit** the spine backlog deliberately deferred: a
Well-Architected Lens prod-readiness analysis of the now-synthesizable stack,
covering all seven pillars (including COST and SUS, which the spine could not
score without a CDK), each defended through the same six-field Reasoning Gate
the spine used, backed by real `cfn-guard` and `analyze_cdk_project` receipts.
The gate-judged code is a deterministic, stdlib-only checker
(`src/compliance_assistant/prod_readiness.py`) that validates the audit
document's structure and cross-references — the executable realization of the
PRD's "grep script", built fail-closed in the exact style of
`infra/stacks/slo_contract.py`. The audit document and evidence receipts live
under `docs/` (git-untracked working notes, per the project convention); the
judged diff is the checker plus its tests.

## User Story

As the engineer presenting this codebase as interview-grade production-ready
work,
I want a single evidence-backed audit that scores every Well-Architected pillar
against the actual synthesized infrastructure, with every gap defended or
explicitly dismissed,
So that a reviewer can see the system was measured against a recognized bar —
not asserted ready — with receipts they can re-run.

## Problem Statement

The spine backlog (`docs/analysis/2026-05-15-compliance-hardening-backlog.md`)
explicitly deferred COST and SUS scoring and all heavy IaC evidence
(`cfn-guard`, `analyze_cdk_project`) to a post-build audit, because no CDK
existed when it was written (spine §7 method caveats; spine line 7). That audit
does not exist yet. Without it, "production-ready" is asserted, not
demonstrated, and the two deferred pillars are unscored.

## Solution Statement

Produce `docs/analysis/2026-05-16-compliance-prod-readiness.md`: a seven-pillar
WA-Lens audit reusing the spine's `R-*`/`GAP-<PILLAR>-NN` ID schemes and
six-field Reasoning Gate, now grounded in `cdk synth` output plus `cfn-guard`
and `analyze_cdk_project` receipts saved under `docs/analysis/_evidence/`. Make
the audit machine-checkable with `src/compliance_assistant/prod_readiness.py`,
a deterministic parser/validator (fail-closed, mirroring `slo_contract.py`)
that enforces: all 7 pillars present; each pillar carries ≥1 complete six-field
finding **or** an explicit "checked, not a gap because X"; every gap has all
six fields; no `TBD`/placeholder; every `R-*`/`GAP-*` cross-reference resolves
internally (the same integrity checks the spine ran by hand in its Task 5/7
greps). Exhaustively unit-test that checker so the gate's mutation (≥0.80) and
changed-line coverage (≥0.90) legs pass on real logic, not glue.

## Metadata

| Field            | Value                                                                 |
| ---------------- | --------------------------------------------------------------------- |
| Type             | NEW_CAPABILITY (audit deliverable + its machine check)                |
| Complexity       | MEDIUM — analysis is broad; the judged code is one focused parser     |
| Systems Affected | `src/compliance_assistant/` (new checker), `tests/`, `docs/analysis/` |
| Dependencies     | stdlib only for the checker; `aws-cdk` (synth), `cfn-guard`, `mcp__aws-pricing-mcp-server__analyze_cdk_project` for evidence |
| Estimated Tasks  | 7                                                                     |

---

## UX Design

### Before State

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                              BEFORE STATE                                  ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                                                                           ║
║  spine backlog (2026-05-15)        synthesized stack (infra/)             ║
║   ┌──────────────────┐              ┌──────────────────┐                  ║
║   │ 5 pillars scored  │             │ kb/agent/runtime/ │                  ║
║   │ COST = deferred   │  ── no ──►  │ observability     │                  ║
║   │ SUS  = deferred   │   audit     │ stacks synth-green │                 ║
║   │ IaC evidence = "no │            │ but never WA-Lens  │                 ║
║   │ CDK yet, deferred" │            │ audited end-to-end │                 ║
║   └──────────────────┘              └──────────────────┘                  ║
║                                                                           ║
║  PAIN_POINT: "production-ready" is asserted; COST/SUS unscored; no        ║
║  re-runnable cfn-guard / cost receipts tying the claim to the templates.  ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

### After State

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                               AFTER STATE                                  ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                                                                           ║
║  cdk synth ──► cdk.out/*.template.json                                     ║
║      │                                                                    ║
║      ├──► cfn-guard ───────────────► _evidence/cfn-guard-*.txt             ║
║      ├──► analyze_cdk_project ─────► _evidence/analyze-cdk-project.json    ║
║      └──► WA-Lens reasoning ──────►  2026-05-16-compliance-prod-readiness  ║
║                                       .md  (7 pillars, six-field gaps,     ║
║                                            COST+SUS now scored)            ║
║                                              │                            ║
║              prod_readiness.py  ◄────────────┘  (parses + validates)      ║
║                  │                                                         ║
║                  └─► exit 0  ⇒  regression leg green; mutation+coverage    ║
║                                  on the checker ⇒ test_integrity green     ║
║                                                                           ║
║  VALUE_ADD: every pillar scored against the real templates with receipts  ║
║  a reviewer can re-run; the audit's integrity is machine-enforced.        ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

### Interaction Changes

| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| `docs/analysis/` | spine backlog only; COST/SUS deferred | + full 7-pillar prod-readiness audit with receipts | Reviewer sees a measured, re-runnable readiness verdict |
| `src/compliance_assistant/` | no audit checker | `prod_readiness.py` enforces audit integrity | The audit cannot silently rot (placeholder/missing field/dangling id fails CI) |
| `python -m compliance_assistant.prod_readiness <doc>` | n/a | exits 0 iff the audit is structurally complete | One command proves the deliverable is whole |

---

## Mandatory Reading

**The implementation agent MUST read these before any task:**

| Priority | File | Lines | Why Read This |
|----------|------|-------|---------------|
| P0 | `docs/superpowers/plans/2026-05-15-compliance-prod-hardening-spine.md` | 31-58, 232-278, 451-458, 561-573 | The exact six-field Reasoning-Gate format, the `R-*` catalog (17 ids) + `GAP-<PILLAR>-NN` scheme, severity/visibility/effort weights, and the hand-run integrity greps (Task 5 Step 3, Task 7 Steps 2-3) this checker must mechanize verbatim |
| P0 | `infra/stacks/slo_contract.py` | 1-95 | The fail-closed markdown-parser pattern to MIRROR exactly: anchored repo root, `raise ValueError` on anything ambiguous/empty/duplicate, deterministic, stdlib-only, no network |
| P0 | `.claude/PRPs/compliance-prod-hardening.prd.md` | 125-129 | Phase 6 `GATE:`/`CHECK:`/`HUMAN-GATE:` — reproduced verbatim in this plan's Validation section; the contract |
| P1 | `review_gate/config.py` | 1-128 | How the gate loads the phase-6 bar (`pure_logic_paths` = this module); confirms the kill surface is `tests/test_prod_readiness.py` by the `tests/test_<stem>.py` convention |
| P1 | `infra/README.md` | 120-180 | The exact synth command and the accepted `cfn-guard`/`cfn-lint` exceptions + their Reasoning-Gate justifications the audit must cite, not re-litigate |
| P1 | `docs/analysis/_evidence/` (if present from the spine) | all | Reuse the spine's WA GenAI Lens pillar reference files (`E6-wa-lens-*.md`) as the `Source:` evidence; do not re-fetch what exists |
| P2 | `infra/stacks/` (`kb_stack.py`, `agent_stack.py`, `runtime_stack.py`, `observability_stack.py`) | skim | The actual synthesized resources the COST/SUS/PERF findings must reference by `R-*` id |

**External tooling:**
| Source | How invoked here | Why Needed |
|--------|------------------|------------|
| `aws-cdk` | `cd infra && npx --yes aws-cdk@latest synth --all -q` (infra/README.md:124) | Produces `cdk.out/*.template.json` — local, non-billable, the audit's substrate |
| `cfn-guard` | as run for Phase 1 (`ComplianceAgentStack` COMPLIANT, aws-security ruleset; infra/README.md:134) | Security/REL receipts under `_evidence/` |
| `mcp__aws-pricing-mcp-server__analyze_cdk_project` | tool call on the `infra/` project | COST + SUS receipts (service inventory; no-OpenSearch / Aurora MinCapacity:0 confirmation, infra/README.md:135) |

---

## Patterns to Mirror

**FAIL-CLOSED MARKDOWN PARSER (the prod_readiness.py spine):**
```python
# SOURCE: infra/stacks/slo_contract.py:1-60
# COPY THIS PATTERN: module docstring states the contract; repo root is
# anchored to the module file (not cwd) so pytest-from-root and any other
# caller resolve docs/ identically; parse is deterministic + fail-closed.
_REPO_ROOT = Path(__file__).resolve().parents[2]
...
def _split_row(line: str) -> list[str]:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return cells
# parse_* raises ValueError on missing file / malformed / duplicate / ambiguous
```

**SIX-FIELD REASONING-GATE FINDING (the exact shape the checker validates):**
```
# SOURCE: docs/superpowers/plans/2026-05-15-compliance-prod-hardening-spine.md:36-46
GAP-<PILLAR>-NN  [P0|P1|P2]  <one-line title>  [sev|vis|effort]
  Risk:              ...
  Evidence:          file:line in this repo, or analysis/<file>
  Why this matters here (NOT generic):
                     ...
  Source:            WA GenAI Lens pillar URL, OWASP LLM Top 10, or named principle
  Counter-argument:  ...
  Fix:               → names the sub-project (or "resolved by <sub-project>")
```
The six fields are exactly: `Risk:`, `Evidence:`, `Why this matters here`,
`Source:`, `Counter-argument:`, `Fix:`. Pillar codes: `OPS SEC REL PERF COST
SUS GENAI`.

**HAND-RUN INTEGRITY GREPS TO MECHANIZE (verbatim intent):**
```
# SOURCE: spine Task 5 Step 3 (line 451-455) and Task 7 Steps 2-3 (561-573)
# - count("^GAP-") == count("  Risk:") == count("  Evidence:")
#       == count("  Source:") == count("  Counter-argument:") == count("  Fix:")
# - grep -nE "_\(filled in Task [0-9]+\)_|TBD|TODO|XXX"  -> empty
# - every GAP-<PILLAR>-NN appears >= 2x (inventory + ranked table)
# - every R-[A-Z-]+ token is one of the ids declared in the doc's §3.1 catalog
```

**MUTATION/COVERAGE KILL SURFACE (test file the gate auto-discovers):**
```python
# SOURCE: review_gate/cli.py:106-110 — tests/test_<stem>.py convention
#   pure_logic_paths = ["src/compliance_assistant/prod_readiness.py"]
#   => kill surface auto-resolved to tests/test_prod_readiness.py
# Tests must exercise EVERY validation branch (one failing-fixture per
# rule) so mutmut kill-rate >= 0.80 and diff-cover >= 0.90 on changed lines.
```

---

## Files to Change

| File | Action | Justification |
|------|--------|---------------|
| `src/compliance_assistant/prod_readiness.py` | CREATE | The judged pure-logic checker (phase-6 `pure_logic_paths`); parses + validates the audit doc, fail-closed; `python -m` entrypoint = the PRD's "grep script" |
| `tests/test_prod_readiness.py` | CREATE | Kill surface; one failing fixture per validation rule + the happy path; sized for mutation ≥0.80 / changed-line coverage ≥0.90 |
| `docs/analysis/2026-05-16-compliance-prod-readiness.md` | CREATE | The audit deliverable (git-untracked working notes; **not** in the judged diff) |
| `docs/analysis/_evidence/cfn-guard-<stack>.txt` | CREATE | `cfn-guard` receipts (untracked) |
| `docs/analysis/_evidence/analyze-cdk-project.json` | CREATE | `analyze_cdk_project` receipt (untracked) |
| `docs/analysis/_evidence/synth-manifest.txt` | CREATE | `cdk synth --all` stack list receipt (untracked) |
| `.claude/PRPs/compliance-prod-hardening.prd.md` | (ALREADY EDITED at plan time, commit 0c2361b) | Phase 6 row already `in-progress` + plan linked; Task 7 is **verify-only**, no further PRD edit; the Status→`complete` flip remains the gate chokepoint's |

---

## NOT Building (Scope Limits)

- **No deploy, no live AWS calls.** The audit is produced against `cdk synth`
  output only. `cdk deploy`/`bootstrap` are out of scope (Phase 6
  `HUMAN-GATE: none`; the deploy stays operator-gated under Phase 1).
- **No re-litigating accepted exceptions.** The `cfn-lint`/`cfn-guard`
  exceptions in `infra/README.md:137-180` already carry Reasoning-Gate
  justifications; the audit cites them as resolved, it does not reopen them.
- **No new infrastructure or `src/` behavior changes.** Only the audit
  checker + its tests are added; `crew.py`/`main.py`/stacks are read-only.
- **No multi-region/DR, no load testing with real numbers** (PRD Out of
  scope, prd.md:131-133) — note as justified absences in the audit, do not
  attempt.
- **The spine backlog is not modified.** Phase 6 produces a new dated doc and
  reuses the spine's id schemes; it does not edit `2026-05-15-...backlog.md`.

---

## Validation (Phase 6 PRD `CHECK:` items — reproduced VERBATIM from `.claude/PRPs/compliance-prod-hardening.prd.md:125-129; do not paraphrase)

> ### Phase 6 — Evidence-backed prod-readiness analysis
> - GATE: panel PASS required — same panel as Phase 2 (mutation+coverage / codex / security / code / CHECK-regression), evaluated on this phase's frozen diff before `complete`.
> - CHECK: `docs/analysis/2026-05-16-compliance-prod-readiness.md` exists; a grep script asserts: all 7 WA pillars present, each with ≥1 six-field Reasoning-Gate finding **or** an explicit "checked, not a gap because X"; every gap has all six fields; no `TBD`/placeholder; every `R-*`/`GAP-*` id cross-references resolve (same integrity checks as the spine plan).
> - CHECK: `analyze_cdk_project` + cfn-guard receipts saved under `docs/analysis/_evidence/`.
> - HUMAN-GATE: none (analysis only; produced against the synthesized templates, no deploy required).

**Executable realization of the CHECK items** (the regression leg runs these
verbatim; each must exit 0). The audit doc and `_evidence/` are gitignored
(`.gitignore:7` `docs/*`, only `!docs/SLOs.md` un-ignored), so they are **not
in the judged diff** — the checker run by the regression leg against the
working-tree files is therefore the *only* automated guard on the audit's
content, and is strengthened accordingly:

1. `test -f docs/analysis/2026-05-16-compliance-prod-readiness.md`
2. `PYTHONPATH=src python -m compliance_assistant.prod_readiness docs/analysis/2026-05-16-compliance-prod-readiness.md` — exits 0 iff ALL hold:
   - all 7 pillars (`OPS SEC REL PERF COST SUS GENAI`) present as sections matching the literal grammar pinned in Task 1;
   - each pillar has ≥1 complete six-field finding **or** an explicit `checked, not a gap because X` line **that itself carries a `Source:`/`Evidence:` reference** (no evidence-free dismissal);
   - **COST and SUS** sections each cite `_evidence/analyze-cdk-project.json` (or `_evidence/synth-manifest.txt`) in an `Evidence:` field — the spine's deferral of these two pillars is closed only with the now-available receipt, never by a bare "checked, not a gap";
   - every `GAP-*` has all six fields non-empty; no `TBD`/`TODO`/`XXX`/`_(filled in Task N)_`;
   - every `GAP-<PILLAR>-NN` appears ≥2× (inventory **and** ranked table), counting only real content — tokens inside fenced code blocks / inline-code spans / prose do **not** count;
   - every `R-*` token used anywhere resolves to a declared row in the doc's §3.1 catalog table; unknown `R-*` = violation;
   - every `_evidence/*` path the audit cites exists, is non-empty, and is non-placeholder (no `STUB`/`FAILED-FETCH`/`TBD` sentinel); `analyze-cdk-project.json` parses as JSON and contains a non-empty service inventory.
3. `test -f docs/analysis/_evidence/analyze-cdk-project.json && python -c "import json,sys; d=json.load(open('docs/analysis/_evidence/analyze-cdk-project.json')); sys.exit(0 if d else 1)" && ls docs/analysis/_evidence/cfn-guard-*.txt && ! grep -rl 'STUB\|FAILED-FETCH' docs/analysis/_evidence/`
4. `PYTHONPATH=src python -m pytest tests/test_prod_readiness.py -q` — all pass
5. Baseline / untracked invariant (no regression): `PYTHONPATH=src python -m pytest tests infra/tests -q` green; the audit is correctly **gitignored, not staged** — `git check-ignore -q docs/analysis/2026-05-16-compliance-prod-readiness.md` exits 0 (path is ignored by design) **and** `git diff --cached --name-only` lists nothing under `docs/`. (`git status --porcelain docs/` is *empty* under the current `.gitignore`; an implementer must NOT un-ignore `docs/` to make work "visible" — that would violate prd.md:74-75.)

---

## Step-by-Step Tasks

Execute in order. Each task ends with its VALIDATE command.

### Task 1: CREATE `src/compliance_assistant/prod_readiness.py` — the fail-closed checker

- **ACTION**: CREATE the deterministic, stdlib-only audit-doc parser/validator.
- **MIRROR**: `infra/stacks/slo_contract.py:1-60` — module docstring stating
  the contract; `_REPO_ROOT = Path(__file__).resolve().parents[N]` anchoring;
  `raise ValueError(...)` fail-closed on missing file / malformed / ambiguous.
- **IMPLEMENT** (pure functions, no network, no subprocess; reads only the
  doc path passed in and the `_evidence/` files it cites, both relative to
  the doc's own directory):

  **Pinned grammar (rigid, mirroring `slo_contract.py`'s exact-shape parse —
  loose matchers cause equivalent mutants and miss the 0.80 floor; this is
  the top risk, closed here at spec level):**
  - `PILLARS = ("OPS","SEC","REL","PERF","COST","SUS","GENAI")`
  - `SIX_FIELDS = ("Risk:","Evidence:","Why this matters here","Source:","Counter-argument:","Fix:")`
  - A **pillar section** header is exactly `^## (OPS|SEC|REL|PERF|COST|SUS|GENAI)\b` (anchored, start of line, the pillar token immediately after `## `; a trailing ` — title` is allowed). Nothing else counts as a pillar section.
  - The **resource catalog** is the markdown table under the header matching `^### 3\.1\b`; each data row is `| R-ID | Resource | Source/Sub-project |` (≥3 pipe-cells, leading/trailing pipe), parsed with the `slo_contract._split_row` idiom. The set of declared `R-*` = column-1 of those rows.
  - The **ranked backlog** is the table under `^## Ranked backlog\b`.
  - **Code/prose stripping:** before any token scan, remove fenced code
    blocks (```` ``` ```` … ```` ``` ````) and inline-code spans (`` `…` ``).
    `GAP-*`/`R-*` tokens are counted only in the stripped content, and only
    `GAP-*` occurrences that are either a finding header in a pillar section
    or a ranked-table row cell count toward the ≥2× rule (prose mentions do
    not satisfy it).
  - `parse_findings(stripped) -> list[Finding]` — `Finding` is a frozen
    dataclass (`gap_id, pillar, severity, fields: dict[str,str]`); a finding
    header is `^GAP-(OPS|SEC|REL|PERF|COST|SUS|GENAI)-\d+\b`, its six fields
    are the indented `Field:` lines until the next finding/section.
  - `cited_evidence(text) -> set[str]` — every `_evidence/<name>` path
    referenced in any `Evidence:`/`Source:` field.

  `validate(doc_path) -> list[str]` returns violation strings (empty ==
  valid). Each rule is its own small pure function (independently mutmut-
  killable):
    1. every `PILLARS` member has exactly one pillar section (pinned grammar)
    2. each pillar section has ≥1 finding with all six fields non-empty
       **or** a line matching `checked, not a gap because ` **that line/section
       also carries a `Source:` or `Evidence:` reference** (no evidence-free
       dismissal — Codex MAJOR / code-reviewer MAJOR-A)
    3. **COST and SUS specifically**: their section must cite
       `_evidence/analyze-cdk-project.json` or `_evidence/synth-manifest.txt`
       in an `Evidence:` field — the spine deferred these two *only* for lack
       of a CDK; closing them now requires the receipt, not prose
    4. every parsed `GAP-*` has all six `SIX_FIELDS` present & non-empty
    5. no `TBD`/`TODO`/`XXX`/`_(filled in Task N)_` in stripped content
    6. every `GAP-<PILLAR>-NN` occurs ≥2× across {pillar-section finding
       header} ∪ {ranked-table row} (prose/code excluded)
    7. every `R-*` token used outside §3.1 resolves to a declared §3.1 row;
       any `R-*` not declared there = violation (distinguishes inherited
       spine ids from new synthesized-resource ids — both must be declared
       with the catalog columns; Codex MINOR Q4)
    8. **evidence receipts are real**: every path in `cited_evidence` exists
       relative to the doc dir, is non-empty, and contains no
       `STUB`/`FAILED-FETCH`/`TBD` sentinel; if `analyze-cdk-project.json`
       is cited it must `json.loads` and be non-empty (Codex BLOCKER)
  - `main(argv=None) -> int` — resolves the path arg, prints each violation
    to stderr, returns `1` if any violation (or the doc/required receipt is
    missing) else `0`; `raise SystemExit(main())` under `__main__`. This IS
    the PRD's "grep script", generalized to a deterministic checker exactly
    as Phase 5 generalized "monitor I/O" into a binary test.
- **GOTCHA**: handle CRLF (`splitlines()`); `main` returns non-zero with a
  one-line message, never a traceback, when the doc or a required receipt is
  missing (mirror `slo_contract` `is_file()` guard). Every rule is a separate
  function returning `list[str]`; `validate` concatenates them — so one
  surviving mutant maps to exactly one rule's test fixture.
- **VALIDATE**: `PYTHONPATH=src python -c "import compliance_assistant.prod_readiness as m; print(sorted(f for f in dir(m) if not f.startswith('_')))"` (imports clean)

### Task 2: CREATE `tests/test_prod_readiness.py` — the kill surface

- **ACTION**: CREATE exhaustive unit tests over the checker.
- **MIRROR**: existing `tests/test_*.py` style (stdlib `tmp_path`, plain
  asserts; see any current `tests/test_startup.py`-class test for the
  fixture-writing idiom).
- **IMPLEMENT**: a `GOOD` in-test constant — a minimal but fully valid audit
  doc (all 7 pillars; ≥1 six-field finding or an evidence-citing "checked,
  not a gap because"; COST+SUS citing `_evidence/analyze-cdk-project.json`;
  §3.1 catalog declaring every `R-*`; each `GAP-*` in inventory + ranked
  table) written into `tmp_path` together with a minimal valid
  `_evidence/analyze-cdk-project.json` + `_evidence/synth-manifest.txt`.
  Then **one test per validation rule (1–8)**, each mutating `GOOD` into
  exactly one violation: missing pillar; finding missing `Source:`; empty
  `Risk:`; evidence-free `checked, not a gap`; COST section not citing the
  receipt; SUS section not citing the receipt; stray `TBD`; a `GAP-*`
  appearing once; an `R-*` not in §3.1; missing doc → `main()` returns 1 no
  traceback; cited `_evidence/x.json` absent; cited receipt containing
  `STUB`; `analyze-cdk-project.json` not valid JSON. **Plus the
  false-positive fixtures (Codex MAJOR Q1 / code-reviewer MAJOR-C):** a
  `GAP-*` token that appears twice but *both inside a fenced code block* must
  still fail rule 6 (prose/code excluded); an `R-*` mentioned only in a code
  fence must still fail rule 7; a `TBD` inside a code fence is **not** a
  rule-5 violation (stripped). Plus: `GOOD` passes (`validate` == []),
  `main(GOOD)` returns 0, parser on a malformed §3.1 table raises
  `ValueError`.
- **GOTCHA**: this file's thoroughness is the gate. Every branch in
  `prod_readiness.py` must be hit by ≥1 test (diff-cover ≥0.90 on changed
  lines) and every rule must have a fixture that *fails only that rule* so
  mutmut can't find a surviving mutant (kill-rate ≥0.80). The code-fence /
  prose exclusion is the subtlest surface — its fixtures are mandatory, not
  optional, because a regex-counting implementation would pass every other
  test and silently strand the mutation floor.
- **VALIDATE**: `PYTHONPATH=src python -m pytest tests/test_prod_readiness.py -q` (all pass)

### Task 3: Synthesize templates + capture evidence receipts

- **ACTION**: produce the audit substrate and receipts under
  `docs/analysis/_evidence/` (untracked).
- **IMPLEMENT**:
  - `cd infra && npx --yes aws-cdk@latest synth --all -q` (local,
    non-billable). Save the emitted stack list to
    `docs/analysis/_evidence/synth-manifest.txt`.
  - Run `cfn-guard` on the synthesizable templates as Phase 1 did
    (`ComplianceAgentStack`, aws-security ruleset; infra/README.md:134).
    Save raw output to `docs/analysis/_evidence/cfn-guard-<stack>.txt` for
    each stack run; for stacks deferred to operator pre-deploy
    (`ComplianceKbStack`, `ComplianceRuntimeStack`, infra/README.md:162-180)
    record the existing Reasoning-Gate justification as the receipt, do not
    re-litigate.
  - Call `mcp__aws-pricing-mcp-server__analyze_cdk_project` on `infra/`; save
    the structured result to
    `docs/analysis/_evidence/analyze-cdk-project.json`.
  - Reuse existing `docs/analysis/_evidence/E6-wa-lens-*.md` (spine) as the
    `Source:` references; only fetch a pillar reference if absent.
- **GOTCHA (Codex BLOCKER — no stub-and-pass):** the two **required**
  receipts — `analyze-cdk-project.json` (real JSON service inventory) and at
  least the `ComplianceAgentStack` `cfn-guard` output — must be genuine,
  non-empty, non-placeholder artifacts. They are produced from local
  `cdk synth` output and carry **no billable cost**, so "the tool failed" is
  not an acceptable terminal state: if `analyze_cdk_project` or `cfn-guard`
  cannot be run, that is a **gate-blocking condition to surface, not a stub
  to wave through** (checker rule 8 fails on any `STUB`/`FAILED-FETCH`
  sentinel or unparseable JSON). The *only* legitimately-deferred receipts
  are the `ComplianceKbStack`/`ComplianceRuntimeStack` full cfn-guard runs,
  and those are recorded by citing the **already-accepted Reasoning-Gate
  justification in `infra/README.md:162-180`** (a real, reviewed prior
  decision) — not by an empty stub. WA-Lens pillar `Source:` references reuse
  the spine's existing `_evidence/E6-wa-lens-*.md`; only fetch one if absent.
- **VALIDATE**: `test -s docs/analysis/_evidence/analyze-cdk-project.json && python -c "import json;json.load(open('docs/analysis/_evidence/analyze-cdk-project.json'))" && ls docs/analysis/_evidence/cfn-guard-*.txt docs/analysis/_evidence/synth-manifest.txt && ! grep -rl 'STUB\|FAILED-FETCH' docs/analysis/_evidence/`

### Task 4: Write the audit skeleton + §3.1 resource catalog

- **ACTION**: CREATE `docs/analysis/2026-05-16-compliance-prod-readiness.md`
  with the section skeleton and the resource catalog.
- **IMPLEMENT**: header (Spec/Methodology/Author `ike1112`/Date 2026-05-16/
  Status: working notes — not git-tracked); sections: `## 1. Purpose &
  method`, `## 2. As-built system map`, `## 3. ID schemes & rubrics` (3.1
  resource catalog table — every `R-*` the findings will cite, reusing the
  spine's 17 + any new `R-*` for synthesized resources; 3.2 gap id scheme;
  3.3 severity; 3.4 ranking weights — copy from spine §3 verbatim), one
  `## <PILLAR>` section per pillar in `OPS SEC REL PERF COST SUS GENAI`,
  `## Ranked backlog`, `## Out of scope & method caveats`.
- **GOTCHA**: the date in the filename is **exactly** `2026-05-16` — that is
  the verbatim PRD CHECK path; do not substitute today's date.
- **VALIDATE**: `grep -c "^## " docs/analysis/2026-05-16-compliance-prod-readiness.md` ≥ 11

### Task 5: Fill every pillar with Reasoning-Gate findings (incl. COST + SUS)

- **ACTION**: for each of the 7 pillars, write ≥1 six-field finding **or** an
  explicit `checked, not a gap because X` statement, evidenced by the Task 3
  receipts and the synthesized stacks.
- **IMPLEMENT**: reuse/close the spine's `GAP-*` (mark resolved-by with
  evidence: `file:line` in `infra/` or the `_evidence/` receipt) and **score
  the previously-deferred COST and SUS pillars against
  `_evidence/analyze-cdk-project.json`** (e.g. Aurora `MinCapacity:0`
  scale-to-zero, no-OpenSearch line item, arm64 runtime) — the COST and SUS
  sections MUST cite that receipt (checker rule 3), closing the spine's
  deferral with the receipt rather than asserting readiness. Each finding
  carries the full six fields; each gap appears in its pillar section **and**
  the Ranked backlog (the ≥2× rule). A pillar with no real gap gets an
  explicit `checked, not a gap because <reason tied to this system>` that
  itself carries a `Source:`/`Evidence:` reference (checker rule 2 — no
  evidence-free dismissal).
- **GOTCHA**: the checker now verifies every cited `_evidence/*` resolves,
  is non-empty, and is non-stub (rule 8) and that COST/SUS cite the receipt
  (rule 3) — so a hollow audit fails the regression leg. What the checker
  cannot judge is whether an `Evidence: file:line` *says what the finding
  claims*; the audit doc is gitignored and **not in the judged diff**, so no
  codex/security/code panel leg inspects its prose (correcting the earlier
  mistaken assumption). Accuracy of every `file:line` is therefore the audit
  author's responsibility and an explicit acceptance criterion — fabricated
  or mis-cited evidence is a correctness defect the author must not commit;
  re-open each cited line and confirm it says what the finding claims (spine
  Task 5 Step 1 pattern).
- **VALIDATE**: `PYTHONPATH=src python -m compliance_assistant.prod_readiness docs/analysis/2026-05-16-compliance-prod-readiness.md` exits 0

### Task 6: Ranked backlog + purpose/caveats + final integrity sweep

- **ACTION**: complete `## 1`, `## Ranked backlog` (mechanical
  `score=(sev×vis)/effort`, spine weights), and `## Out of scope & method
  caveats` (note COST/SUS now scored — the spine deferral is closed; record
  any failed receipt as a caveat).
- **IMPLEMENT**: ranked table lists every `GAP-*` from the pillar sections
  (closes the ≥2× cross-reference rule); caveats explicitly state which
  `cfn-guard` runs are operator-deferred and why (cite infra/README.md, do
  not reopen).
- **VALIDATE**: `PYTHONPATH=src python -m compliance_assistant.prod_readiness docs/analysis/2026-05-16-compliance-prod-readiness.md` exits 0 **and** the audit is correctly gitignored (not staged): `git check-ignore -q docs/analysis/2026-05-16-compliance-prod-readiness.md` exits 0 **and** `git diff --cached --name-only` lists nothing under `docs/`

### Task 7: PRD verify-only + full regression

- **ACTION (verify-only — MAJOR-D):** the PRD Phase 6 row was **already**
  set `in-progress` with this plan linked at plan-creation time (commit
  0c2361b; see Progress Log 2026-05-18). Task 7 makes **no PRD edit** —
  confirm the row reads `in-progress` with `phase-prod-readiness-analysis.plan.md`
  linked and stop. Do **not** "correct" it, do **not** touch
  Status→`complete` or the Progress Log (chokepoint-owned). An unnecessary
  PRD edit here lands in the judged window for no reason.
- **VALIDATE**:
  - `grep -n "in-progress.*phase-prod-readiness-analysis.plan.md" .claude/PRPs/compliance-prod-hardening.prd.md` (row already correct — no edit made)
  - `PYTHONPATH=src python -m pytest tests infra/tests -q` (no regression)
  - `PYTHONPATH=src python -m pytest tests/test_prod_readiness.py -q` (kill surface green)
  - audit untracked: `git check-ignore -q docs/analysis/2026-05-16-compliance-prod-readiness.md` exits 0; `git diff --cached --name-only` lists nothing under `docs/`

---

## Testing Strategy

### Unit Tests to Write

| Test File | Test Cases | Validates |
|-----------|-----------|-----------|
| `tests/test_prod_readiness.py` | happy path; missing pillar; each of the six missing/empty fields; stray `TBD`; `GAP-*` appearing once; `R-*` absent from catalog; missing file (`main`→1, no traceback); malformed table (`ValueError`) | Every `validate()`/`parse_findings()`/`main()` branch — the gate's mutation + changed-line-coverage surface |

### Edge Cases Checklist

- [ ] CRLF line endings in the doc
- [ ] A pillar present but with only a "checked, not a gap because" line (must pass)
- [ ] A finding whose field label is present but value is whitespace (must fail rule 3)
- [ ] `GAP-*` id in a code-fence/comment vs. real occurrence (count rule must not be fooled — define the token regex tightly)
- [ ] `R-*` token inside a word (anchor the regex)
- [ ] Doc file absent → `main` returns 1 with a one-line message, no stack trace

---

## Validation Commands

### Level 1: STATIC / IMPORT
```bash
PYTHONPATH=src python -c "import compliance_assistant.prod_readiness"
```
**EXPECT**: exit 0.

### Level 2: UNIT (kill surface)
```bash
PYTHONPATH=src python -m pytest tests/test_prod_readiness.py -q
```
**EXPECT**: all pass; every checker branch covered.

### Level 3: REGRESSION (PRD CHECK + no regression)
```bash
test -f docs/analysis/2026-05-16-compliance-prod-readiness.md
PYTHONPATH=src python -m compliance_assistant.prod_readiness docs/analysis/2026-05-16-compliance-prod-readiness.md
test -s docs/analysis/_evidence/analyze-cdk-project.json && python -c "import json;json.load(open('docs/analysis/_evidence/analyze-cdk-project.json'))" && ls docs/analysis/_evidence/cfn-guard-*.txt
! grep -rl 'STUB\|FAILED-FETCH' docs/analysis/_evidence/
PYTHONPATH=src python -m pytest tests infra/tests -q
git check-ignore -q docs/analysis/2026-05-16-compliance-prod-readiness.md   # exit 0: correctly gitignored
git diff --cached --name-only | grep '^docs/' && exit 1 || true             # nothing under docs/ staged
```
**EXPECT**: every command exit 0; the audit is gitignored-by-design and never staged (NOT expected to appear in `git status` — `.gitignore:7` `docs/*`).

### Level 4: GATE PANEL (run by the phase-gate orchestrator, not here)
- mutation (`review_gate.cli mutation --phase 6`, floor 0.80 on `prod_readiness.py`)
- changed-line coverage (`diff-cover`, floor 0.90)
- codex adversarial / security-auditor / code-reviewer on the frozen diff
- regression leg = Level 3 commands verbatim

---

## Acceptance Criteria

- [ ] `docs/analysis/2026-05-16-compliance-prod-readiness.md` exists; all 7 pillars present; each pillar ≥1 six-field finding or an **evidence-citing** "checked, not a gap because X"; every gap six-field; no `TBD`/placeholder; every `R-*`/`GAP-*` cross-reference resolves; tokens in code-fences/prose excluded (checker exits 0)
- [ ] `analyze_cdk_project` + `cfn-guard` receipts under `docs/analysis/_evidence/` are **real, non-empty, non-stub** (rule 8); `analyze-cdk-project.json` is valid JSON with a non-empty service inventory
- [ ] COST and SUS pillars scored **against `_evidence/analyze-cdk-project.json`** (spine deferral closed with the receipt, not asserted)
- [ ] Every cited `Evidence: file:line` was re-opened and confirms what the finding claims (author responsibility — the doc is not in the judged diff, no panel leg inspects it)
- [ ] `tests/test_prod_readiness.py` exhaustive incl. code-fence/prose false-positive fixtures; mutation ≥0.80 and changed-line coverage ≥0.90 achievable on `prod_readiness.py`
- [ ] No regression: `pytest tests infra/tests` green; the audit is gitignored-by-design and never staged (`git check-ignore` exits 0; nothing under `docs/` in `git diff --cached`)
- [ ] `HUMAN-GATE: none` honored — no deploy, no live/billable AWS calls (synth + cfn-guard + analyze_cdk_project are all local/free)

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Checker is thin glue → mutation/coverage leg fails | MED | HIGH | Make every validation rule a small pure function; one failing fixture per rule (Task 2 is the gate-critical task, not Task 5) |
| Audit doc under `docs/` is gitignored → reviewers think nothing shipped | MED | MED | The judged diff is `prod_readiness.py`+tests (real code); the doc is a working-note deliverable per project convention (spine §8); state this explicitly in the audit header |
| `analyze_cdk_project`/`cfn-guard` unavailable in the loop env | MED | HIGH | These run on local synth output (free) — there is no stub-and-pass: checker rule 8 fails any `STUB`/`FAILED-FETCH`/unparseable receipt, so an unproducible required receipt is a gate-blocking condition to surface, not a waved-through caveat. Only the `KbStack`/`RuntimeStack` full cfn-guard is legitimately deferred, recorded by citing the accepted `infra/README.md:162-180` justification |
| Filename date drift (`2026-05-16` vs today) | LOW | HIGH | The verbatim PRD CHECK path is `2026-05-16`; Task 4 GOTCHA pins it; checker + regression leg both reference that exact path |
| Unnecessary judged-window PRD edit | LOW | MED | The only PRD edit (row→`in-progress` + plan link) was made once at plan time (commit 0c2361b); Task 7 is verify-only and makes no further PRD edit; Status→`complete`/Progress Log stay chokepoint-owned |

## Notes

- **Why a Python checker, not literal `grep`:** the gate's `test_integrity`
  leg needs pure logic to mutate/cover; a stdlib parser invoked via
  `python -m` is the same generalization Phase 5 applied ("monitor I/O" →
  binary test). It fully subsumes the spine's hand-run greps (Task 5 Step 3,
  Task 7 Steps 2-3) and makes the audit's integrity machine-enforced.
- **Why the audit doc is not in the judged diff:** project convention
  (spine §8; prd.md:74 "nothing under `docs/` is staged"). The regression
  leg still validates the produced (untracked) doc at gate time, so the
  deliverable is enforced without tracking it.
- **Completion authority unchanged:** this plan never flips Phase 6 to
  `complete`. Only the `phase-gate` `complete` chokepoint does, after the
  independent panel mints a PASS token bound to base `b068a9c`.
