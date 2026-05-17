# Phase 5 — Gate round 2 findings (consolidated) — FINAL remediation

Base `0c6399d` · window `0c6399d..HEAD`. Aggregate FAIL. Round-1
MAJORs (real callback mapping, tamper-proof, EMF producer contract) +
all listed MINORs verified RESOLVED. New drivers all say the same
thing: the observability is contract-correct but **not wired to a real
run**, and one metric family is unbacked. This is the last allowed
remediation — fix every item at root cause, exhaustively.

## MAJOR (must fix)

### M1 — EMF producer is never called on a real run (codex F-001 + code-reviewer MAJOR)
`crew.py` makes `_tracer` method-local and returns the `Crew`;
`main.run/train/replay/test` only call `.kickoff()/...` and never
`finalize()`/`record()`. So on a real `crewai run` zero EMF lines are
emitted and every `ComplianceAssistant/Crew` alarm sits in
INSUFFICIENT_DATA (masked by `TreatMissingData.NOT_BREACHING`). The
producer↔document contract is correct but the producer is dead code.
**Root-cause fix:** `crew()` stashes the tracer on `self`
(`self._tracer = build_tracer()`); `main.run()` (and train/replay/test)
capture `ca = ComplianceAssistant()`, build the crew, and call
`ca._tracer.finalize(success=True/False)` exactly once around
`kickoff()` in the existing try/except (preserve the current exception
wrapping + crew output byte-unchanged). Add a test around the run
wrapper (not a bare `Tracer` call) asserting exactly one EMF line on a
run-shaped success and one on failure.

### M2 — Quality SLO alarms are unbacked (codex F-002)
`docs/SLOs.md` defines `ComplianceAssistant/Quality` alarms for
`Faithfulness` and `CitationCorrectness`; the stack creates alarms for
every row; but NO producer emits those metric names (the eval harness
computes values locally, never publishes them). 2 of 11 alarms watch
nothing. The round-2 "documented as eval-harness-produced" claim was
not actually true.
**Root-cause fix:** add a Quality EMF producer
(`build_quality_emf(faithfulness, citation)` + `QUALITY_METRIC_NAMES`
in tracing.py) and emit it from the eval harness report path —
additive, behind an explicit opt-in env flag so the offline gate never
spuriously emits and the deterministic scoring is unchanged
(`tests/evals/harness/` is NOT the Phase-3 frozen surface — only
`tests/evals/gold/`+PROVENANCE are; an additive emit hook with no
scoring change is allowed). Add a non-circular producer-contract test:
`QUALITY_METRIC_NAMES == {Quality-namespace metric names parsed from
docs/SLOs.md}`. Keeps all 11 SLOs backed by real producer code.

### M3 — Committed fixture not proven produced by the exercised path (codex F-003 + code-reviewer MINOR)
`tests/tracing/fixtures/run_spans.json` content differs from
`_drive()` output; `recorded_at_commit`/`recorder_version` are stale
vs the committed bytes. The "produced by the exercised path" claim
overclaims; only the hash is rebound.
**Root-cause fix:** regenerate the fixture FROM `_drive()` verbatim at
the current commit; add a test that builds spans via the SAME
`_drive()` callback path and asserts the committed fixture's spans
equal that output (content binding, not just hash). Correct the
tracing.py / test docstrings to state exactly that.

## MINOR (fix in this final round)
- code-reviewer + jargon: reword the window commit subject that
  contains "gate round 1" (commit `0ee8431`) to an intent-led subject
  (history rewrite of that one commit; base unchanged → integrity
  stays green, path-based).
- codex F-004: `.claude/PRPs/plans/phase-observability-slos.plan.md`
  literally contains the banned phrase as prose; rephrase so a jargon
  scan of durable artefacts is clean without changing intent.
- security (round-2 new): the PAN regex still misses a double-space /
  newline-separated PAN (>1 separator between groups). Collapse
  separator/whitespace runs before matching (or widen the inner class)
  + a regression test for double-space and newline Luhn PANs.

## Not in scope
No change under `agent_ids.py` (Phase-2 frozen), `citations.py`
(Phase-5 mutation target, ≥0.80, untouched), `tests/evals/gold/` +
PROVENANCE (Phase-3 frozen), `review_gate/` /
`.claude/review-gate.config.json` (BASE). The observability stack /
its IAM accounting are already correct — do not regress them. Plan
Validation stays the verbatim PRD lines.
