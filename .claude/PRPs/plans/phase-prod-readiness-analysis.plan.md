# Feature: Evidence-backed prod-readiness analysis (WA-Lens audit of the synthesized stack)

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
| `.claude/PRPs/compliance-prod-hardening.prd.md` | UPDATE | Phase 6 row: `pending` → `in-progress`, link this plan (planning convention, prd.md:61; **never** touch the Status→`complete` cell — the gate chokepoint owns that) |

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
verbatim; each must exit 0):

1. `test -f docs/analysis/2026-05-16-compliance-prod-readiness.md`
2. `PYTHONPATH=src python -m compliance_assistant.prod_readiness docs/analysis/2026-05-16-compliance-prod-readiness.md` — exits 0 iff: all 7 pillars (`OPS SEC REL PERF COST SUS GENAI`) present; each pillar has ≥1 complete six-field finding **or** an explicit `checked, not a gap because` line; every `GAP-*` has all six fields; no `TBD`/`TODO`/`XXX`/`_(filled in Task N)_`; every `GAP-*` appears ≥2× (inventory + ranked table); every `R-*` token resolves to the doc's own §3.1 catalog
3. `test -f docs/analysis/_evidence/analyze-cdk-project.json && ls docs/analysis/_evidence/cfn-guard-*.txt`
4. `PYTHONPATH=src python -m pytest tests/test_prod_readiness.py -q` — all pass
5. Baseline (no regression): `PYTHONPATH=src python -m pytest tests infra/tests -q` green; `git status --porcelain docs/` shows only `??` (docs stays untracked)

---

## Step-by-Step Tasks

Execute in order. Each task ends with its VALIDATE command.

### Task 1: CREATE `src/compliance_assistant/prod_readiness.py` — the fail-closed checker

- **ACTION**: CREATE the deterministic, stdlib-only audit-doc parser/validator.
- **MIRROR**: `infra/stacks/slo_contract.py:1-60` — module docstring stating
  the contract; `_REPO_ROOT = Path(__file__).resolve().parents[N]` anchoring;
  `raise ValueError(...)` fail-closed on missing file / malformed / ambiguous.
- **IMPLEMENT** (pure functions, no I/O beyond reading the one doc path passed
  in; no network; no subprocess):
  - `PILLARS = ("OPS","SEC","REL","PERF","COST","SUS","GENAI")`
  - `SIX_FIELDS = ("Risk:","Evidence:","Why this matters here","Source:","Counter-argument:","Fix:")`
  - `parse_findings(text) -> list[Finding]` — each `GAP-<PILLAR>-NN` block
    with its six field lines; `Finding` is a frozen dataclass
    (`gap_id, pillar, severity, fields: dict[str,str]`).
  - `validate(text) -> list[str]` — returns the list of violation strings
    (empty == valid). Rules, each independently testable:
    1. every pillar in `PILLARS` has a `## <pillar>`-equivalent section
    2. each pillar section has ≥1 finding with all six fields non-empty
       **or** a line matching `checked, not a gap because `
    3. every parsed `GAP-*` has all six `SIX_FIELDS` present & non-empty
    4. no `TBD`/`TODO`/`XXX`/`_(filled in Task N)_` anywhere
    5. every `GAP-<PILLAR>-NN` token occurs ≥2 times (inventory + ranked)
    6. every `R-[A-Z0-9-]+` token appears in the doc's resource-catalog
       section (the doc's own §3.1-equivalent table)
  - `main(argv=None) -> int` — reads the path arg, prints each violation to
    stderr, returns `1` if any violation else `0`; `raise SystemExit(main())`
    under `__main__`. (This IS the PRD's "grep script", generalized to a
    deterministic checker exactly as Phase 5 generalized "monitor I/O" into a
    binary test.)
- **GOTCHA**: handle CRLF (`splitlines()` is fine); the doc is untracked and
  absent in some callers — `main` must return non-zero with a clear message,
  never traceback, when the file is missing (mirror `slo_contract` `is_file()`
  guard). Keep every rule a separate small function so mutants are killable.
- **VALIDATE**: `PYTHONPATH=src python -c "import compliance_assistant.prod_readiness as m; print([f for f in dir(m) if not f.startswith('_')])"` (imports clean)

### Task 2: CREATE `tests/test_prod_readiness.py` — the kill surface

- **ACTION**: CREATE exhaustive unit tests over the checker.
- **MIRROR**: existing `tests/test_*.py` style (stdlib `tmp_path`, plain
  asserts; see any current `tests/test_startup.py`-class test for the
  fixture-writing idiom).
- **IMPLEMENT**: a `GOOD` in-test constant — a minimal but fully valid audit
  doc (all 7 pillars; ≥1 six-field finding or explicit "checked, not a gap
  because"; §3.1 catalog declaring its `R-*`; each `GAP-*` in inventory +
  ranked table). Then **one test per validation rule** mutating `GOOD` into
  exactly one violation each (missing pillar; finding missing `Source:`;
  empty `Risk:`; a stray `TBD`; a `GAP-*` appearing once; an `R-*` not in the
  catalog; missing file → `main()` returns 1, no traceback). Plus: `GOOD`
  passes (`validate` == []), `main(GOOD path)` returns 0, parser on malformed
  table raises `ValueError`.
- **GOTCHA**: this file's thoroughness is the gate. Every branch in
  `prod_readiness.py` must be hit by ≥1 test (diff-cover ≥0.90 on changed
  lines) and every rule must have a fixture that *fails only that rule* so
  mutmut can't find a surviving mutant (kill-rate ≥0.80).
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
- **GOTCHA**: if an MCP/tool call fails, write a citation stub recording the
  failure + the command, and continue (spine Task 2 Step 2 pattern) — the
  audit must still be producible offline; a failed receipt is a documented
  caveat, not a blocker.
- **VALIDATE**: `ls docs/analysis/_evidence/analyze-cdk-project.json docs/analysis/_evidence/cfn-guard-*.txt docs/analysis/_evidence/synth-manifest.txt`

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
  evidence: `file:line` in `infra/` or the `_evidence/` receipt) and raise
  the **previously-deferred COST and SUS** findings now that
  `analyze-cdk-project.json` exists (e.g. Aurora `MinCapacity:0` scale-to-zero,
  no-OpenSearch, arm64 runtime — cite the receipt). Each finding carries the
  full six fields; each gap appears in its pillar section **and** the Ranked
  backlog (the ≥2× rule). Pillars with no real gap get an explicit
  `checked, not a gap because <reason tied to this system>`.
- **GOTCHA**: `Evidence:` must be a real `file:line` or `_evidence/<file>` —
  the checker doesn't verify the reference resolves on disk, but the codex/
  code-review panel legs will; fabricated evidence is a BLOCKER.
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
- **VALIDATE**: `PYTHONPATH=src python -m compliance_assistant.prod_readiness docs/analysis/2026-05-16-compliance-prod-readiness.md` exits 0 **and** `git status --porcelain docs/` shows only `??`

### Task 7: PRD bookkeeping + full regression

- **ACTION**: update the PRD Phase 6 row `pending` → `in-progress` and link
  this plan in the PRP Plan column (planning convention, prd.md:61).
  **Do not** edit the Status→`complete` cell or the Progress Log — the
  `phase-gate` `complete` chokepoint owns those.
- **VALIDATE**:
  - `PYTHONPATH=src python -m pytest tests infra/tests -q` (no regression)
  - `PYTHONPATH=src python -m pytest tests/test_prod_readiness.py -q` (kill surface green)
  - `git status --porcelain docs/` → only `??` lines

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
test -f docs/analysis/_evidence/analyze-cdk-project.json && ls docs/analysis/_evidence/cfn-guard-*.txt
PYTHONPATH=src python -m pytest tests infra/tests -q
git status --porcelain docs/    # only ?? lines
```
**EXPECT**: every command exit 0; `docs/` untracked.

### Level 4: GATE PANEL (run by the phase-gate orchestrator, not here)
- mutation (`review_gate.cli mutation --phase 6`, floor 0.80 on `prod_readiness.py`)
- changed-line coverage (`diff-cover`, floor 0.90)
- codex adversarial / security-auditor / code-reviewer on the frozen diff
- regression leg = Level 3 commands verbatim

---

## Acceptance Criteria

- [ ] `docs/analysis/2026-05-16-compliance-prod-readiness.md` exists; all 7 pillars present; each pillar ≥1 six-field finding or explicit "checked, not a gap because X"; every gap six-field; no `TBD`/placeholder; every `R-*`/`GAP-*` cross-reference resolves (checker exits 0)
- [ ] `analyze_cdk_project` + `cfn-guard` receipts under `docs/analysis/_evidence/`
- [ ] COST and SUS pillars scored (spine deferral closed)
- [ ] `tests/test_prod_readiness.py` exhaustive; mutation ≥0.80 and changed-line coverage ≥0.90 achievable on `prod_readiness.py`
- [ ] No regression: `pytest tests infra/tests` green; `docs/` stays untracked
- [ ] `HUMAN-GATE: none` honored — no deploy, no live AWS calls

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Checker is thin glue → mutation/coverage leg fails | MED | HIGH | Make every validation rule a small pure function; one failing fixture per rule (Task 2 is the gate-critical task, not Task 5) |
| Audit doc under `docs/` is gitignored → reviewers think nothing shipped | MED | MED | The judged diff is `prod_readiness.py`+tests (real code); the doc is a working-note deliverable per project convention (spine §8); state this explicitly in the audit header |
| `analyze_cdk_project`/`cfn-guard` unavailable in the loop env | MED | MED | Citation-stub-and-continue (spine Task 2 pattern); a failed receipt is a documented caveat, the audit is still producible offline |
| Filename date drift (`2026-05-16` vs today) | LOW | HIGH | The verbatim PRD CHECK path is `2026-05-16`; Task 4 GOTCHA pins it; checker + regression leg both reference that exact path |
| Editing the PRD inside the judged window reads as scope to a panel leg | LOW | MED | Restrict the PRD edit to the documented planning convention (Status `pending`→`in-progress` + plan link); never touch Status→`complete`/Progress Log (chokepoint-owned) |

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
