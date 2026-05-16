# Phase 2 gate findings — round 2

**Verdict:** gate FAIL — blocking: `codex`, `test_integrity`.
**Base SHA:** a55cdf3 (pinned, unchanged). PRD Phase 2 stays `pending`.

## What is actually fixed (product)

The two real Phase 2 code defects from round 1 are **resolved and
codex-confirmed**:

- **A1** SSM no longer silently downgrades to env-controlled ids — fails
  closed unless genuinely unreachable or explicit `USE_ENV_AGENT_IDS`.
- **A2** agent-id values are stripped before the placeholder check —
  the ` replace-with-…` whitespace bypass is closed.

Plus the round-1 startup hardening (fail-fast TOPIC/MODEL/agent-id,
env-gated verbosity, `.env.example` parity, lockfile) is green, and the
CHECK-5 packaging fix stands. Security and code review were round-1
PASS; the only change since was the agent-id remediation, which codex
re-reviewed and cleared.

**If the gate's objective legs worked, Phase 2's product would pass.**

## Why the gate still FAILs — all gate machinery, not product

### test_integrity (BLOCKING)

- **Mutation floor unreachable for this module.** `agent_ids.py`
  kill-rate across three honest attempts: 0.686 (original) → 0.632
  (full exception taxonomy) → **0.660** (simplified + comprehensive
  branch tests). The module is defensive SSM/env I/O
  error-classification, not parser-like pure logic; a large share of its
  mutants are equivalent or only killable by contrived assertions. A
  0.80 floor on this kind of code is the wrong instrument. (Predicted by
  the round-1 test-engineer leg.)
- **Coverage leg never worked.** The gate runs `--cov=<filepath>`, but
  under the project's `src/` layout + `PYTHONPATH=src` the module is
  imported as `compliance_assistant.X`; a path-form `--cov` target does
  not match, coverage reports *“module never imported”* and measures
  nothing. The correct target is the module/package name.

### codex (BLOCKING) — defects in the gate-infra commits

- **[HIGH]** B2 scopes coverage to `pure_logic_paths` + *new* src only,
  so *modified* existing src (`main.py`, `crew.py`) is unmeasured — a
  real bypass (move risky code into an existing non-pure-logic file and
  coverage never sees it).
- **[MEDIUM]** B1's unconditional `git checkout --` in `finally`
  destroys uncommitted edits in a target path — no clean-worktree
  preflight.

### Context: the gate's objective legs were never functional

Exercising the quality gate on its first real phase surfaced a stack of
independent defects in the gate itself, none of them product code:
CHECK-5 packaging collision; `mutmut` not installed; bare-`mutmut` PATH
dependency; Windows cp1252 encode crash; parent-side decode crash;
full-suite per-mutant runner tripping mutmut's 10×-baseline guard;
`mutmut results` parser written for a format mutmut 2.5.1 does not emit;
crash-poisons-the-target; coverage `--cov=<path>` measuring nothing;
coverage scope excluding modified files. The deterministic core
(`review_gate` unit suite) was green throughout because it tests parsing
on synthetic fixtures — the *integration seam* had never been run.

## Decisions required (owner-level — not builder authority)

The builder must not weaken the bar (`mutation_floor`,
`coverage_floor`, the CHECK set) or hand-pick coverage exclusions. These
are gate-design calls:

1. **Mutation target/floor for I/O-glue modules.** Keep 0.80 on
   `agent_ids.py` (then it needs a different test strategy or the floor
   is effectively a block), lower it for I/O modules, or change the
   per-phase pure-logic target. (`review-gate.config.json` = the bar.)
2. **Coverage leg.** Fix the cov target to module/package form **and**
   decide the honest scope for modified-but-framework-glue files
   (`main.py`/`crew.py` need `crewai`, absent in the gate interpreter):
   install `crewai` in the gate env, measure changed-lines only, or a
   documented per-phase exclusion list. (codex HIGH.)
3. **B1 mutation cleanup safety.** Add a clean-worktree preflight
   (fail closed if a target is dirty) before mutmut, so the restore can
   never eat real work. (codex MEDIUM — straightforward, owner just
   needs to approve touching gate code again.)

Round 2 of max 3 is spent. Proceeding to round 3 without these
decisions would burn the last round on gate machinery the builder may
not redesign unilaterally. Halting for direction is the correct,
non-gaming action.
