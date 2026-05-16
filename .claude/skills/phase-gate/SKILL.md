---
name: phase-gate
description: Outer orchestrator loop. Drives PRD phases prp-plan -> prp-ralph -> independent review panel -> PASS-flip or capped fresh-ralph remediation. The builder never marks its own phase complete.
---

# Phase Quality Gate — Orchestrator Loop

Implements `docs/superpowers/specs/2026-05-16-phase-quality-gate-design.md`.
The deterministic logic is the tested `review_gate` package; this skill is
the sequencing layer. **Never** edit a PRD `Status` cell by hand and never
run `cdk deploy` — `HUMAN-GATE:` items halt the loop.

All CLI calls below: `python -m review_gate.cli <cmd> --repo . [...]`.
Exit code 0 = ok/PASS, 1 = gate-FAIL (act on it), 2 = usage/IO (HALT for human).

## Loop

1. **Pick the phase.** Read `.claude/PRPs/compliance-prod-hardening.prd.md`.
   Choose the lowest-numbered phase whose `Status` is `pending` (or
   `in-progress` with no outstanding `HUMAN-GATE:`) and whose every
   dependency is `complete`. If the only remaining work for an otherwise
   actionable phase is a `HUMAN-GATE:` item, **STOP** and report — never
   deploy, never auto-pass it.

2. **`init`.** `python -m review_gate.cli init --phase <P>`. This pins the
   base SHA once and persists state (resumable; re-running keeps the pin).

3. **prp-plan.** Invoke `prp-core:prp-plan` with the PRD. The generated
   plan's validation section MUST be that phase's PRD `CHECK:` items
   verbatim — if it is not, fix the plan before continuing.

4. **Adversarial plan review (before any build is spent).**
   - Run `/codex:adversarial-review --wait --base HEAD` scoped to the
     newly written/committed plan file — challenge the approach,
     assumptions, and tradeoffs, not just defects.
   - Dispatch the Agent tool with
     `subagent_type="agent-skills:code-reviewer"`, fresh context, to
     verify the codex findings and the plan's internal consistency
     against this phase's PRD `CHECK:` items.
   - Revise the plan to resolve any BLOCKER/MAJOR finding, then **commit
     the revised plan** (`git add <plan> && git commit -m "phase <P>:
     plan revised per adversarial review"`). Only then continue. If codex
     is unavailable, HALT for human — never skip this stage silently.

5. **prp-ralph.** Invoke `prp-core:prp-ralph` on the (revised) plan and let
   it run its normal lifecycle to its own green (archive + report). ralph
   builds; ralph does not judge.

6. **`integrity`.** `python -m review_gate.cli integrity --phase <P>`.
   Exit 1 → the bar/fixtures were edited inside the judged diff: go to
   step 10 FAIL. Exit 2 → HALT for human.

7. **`provenance`** (phase 3 only — no-op otherwise).
   `python -m review_gate.cli provenance --phase <P>`. Exit 1 → FAIL
   (step 10). The Phase-3 RAG gold set must be owner-seeded or
   codex-authored and committed *before* the harness; ralph may not
   author its own ground truth.

8. **Review panel — run all legs in parallel on the frozen diff** (the
   range is `<base_sha>..HEAD`; get `base_sha` from
   `python -m review_gate.cli status`):

   - **A · codex adversarial (independent model, BLOCKING).** Run
     `/codex:adversarial-review --wait --base <base_sha>`. Normalize its
     output to a verdict: `severity` = the highest it reports
     (`BLOCKER`/`MAJOR`/`MINOR`/null), `passed` = no BLOCKER/MAJOR.
   - **B · test-integrity (objective, BLOCKING).** Run
     `python -m review_gate.cli mutation --phase <P>` (the gate applies
     this phase's `mutation_floor` override if set, else the global)
     AND a **changed-lines** coverage gate on every line this phase
     added or modified:

     ```
     python -m pytest --cov=<pkg> --cov-context=test \
       --cov-report=xml -q tests
     diff-cover coverage.xml --compare-branch <base_sha> \
       --fail-under=<coverage_floor*100> \
       --src-roots src
     ```

     `<pkg>` is the importable top-level package name (e.g.
     `compliance_assistant`) — **not** a file path; under a `src/`
     layout + `PYTHONPATH=src` a path-form `--cov` matches nothing and
     silently measures zero. `diff-cover` then enforces the floor on the
     intersection of "lines changed in `<base_sha>..HEAD`" and the
     coverage data — so it covers **all** added/modified `src/` lines
     (closing the modified-but-not-pure-logic bypass), needs no heavy
     framework deps (untouched lines in glue modules are out of scope by
     construction, not by an exclusion list), and cannot be gamed by
     moving code into an existing file. `coverage_floor` is unchanged;
     it now reads as "≥ X% of the lines this phase touched are tested".
     `passed` = both the mutation command and `diff-cover` exit 0.
   - **C · security.** Dispatch the Agent tool with
     `subagent_type="agent-skills:security-auditor"`, fresh context, asked
     to review only the frozen diff. Normalize to a verdict.
   - **D · code review.** Dispatch the Agent tool with
     `subagent_type="agent-skills:code-reviewer"`, fresh context, frozen
     diff only. Normalize to a verdict.
   - **E · regression.** Run that phase's PRD `CHECK:` commands verbatim.
     `passed` = every CHECK exits 0.
   - **F · test-engineer (ADVISORY — never blocks).** Dispatch the Agent
     tool with `subagent_type="agent-skills:test-engineer"`, fresh
     context, frozen diff only, asked "are these the right cases? what
     branch/edge is untested?" Record it as a verdict named
     `test_engineer`. It is evidence for the report; mutation (leg B) is
     the objective test bar, not this opinion.

   Write the normalized verdicts to `.claude/review-gate.verdicts.json`
   as a list of `{"name","passed","severity","summary"}`. The five
   required legs use `name` ∈ `codex|test_integrity|security|code|regression`;
   include the advisory leg as `name: "test_engineer"`.

9. **`aggregate`.**
   `python -m review_gate.cli aggregate --phase <P> --verdicts .claude/review-gate.verdicts.json`.
   This writes the base-SHA-bound PASS token. `test_engineer` is recorded
   in evidence but never affects the verdict. Exit 0 = PASS, 1 = FAIL.

10. **Route.**
   - **PASS:** `python -m review_gate.cli complete --phase <P>`. Exit 0 →
     the PRD row is now `complete` with an evidence line. Commit the PRD
     change (`git add .claude/PRPs/compliance-prod-hardening.prd.md &&
     git commit -m "phase <P>: gate PASS"`). Go to step 1 for the next
     phase. Exit 2 → chokepoint refused (no valid token): HALT, report.
   - **FAIL:** Write the consolidated panel findings to
     `.claude/findings-<P>-r<round>.md`. If `round` (from
     `review_gate.cli status`) is < 3: increment it (see "Round
     bookkeeping" below — NOT via re-`init`, which is resume-safe and
     would not advance the counter), then spawn remediation: invoke
     `prp-core:prp-ralph` afresh on the same plan with an appended task
     "Fix the ROOT CAUSE of the findings in
     `.claude/findings-<P>-r<round>.md`. Do NOT weaken tests, thresholds,
     fixtures, or the gold set.", then return to step 6 (re-gate the
     same pinned base SHA — accumulated work judged whole). If `round`
     ≥ 3: **STOP**, leave the phase `in-progress`, emit a consolidated
     report. No silent pass, ever.

## Round bookkeeping

The round counter lives in gate state. On a FAIL that will remediate,
bump it: `python -c "import json,pathlib;p=pathlib.Path('.claude/review-gate.state.json');d=json.loads(p.read_text());d['round']+=1;d['status']='remediating';p.write_text(json.dumps(d,indent=2))"`.
Halt when it would exceed 3.

## Hard rules

- The `complete` chokepoint is the ONLY way a phase becomes `complete`.
  It refuses unless an independent PASS token bound to the exact judged
  base SHA exists. Do not hand-edit the PRD, the token, or the state.
- A reviewer process erroring (e.g. codex unavailable) is a gate FAIL
  → HALT for human, never a silent skip of an independent leg.
- `HUMAN-GATE:` items (billable `cdk deploy`/`bootstrap`) always HALT.
