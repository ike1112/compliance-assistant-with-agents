# Phase 6 — HALT after the second full cycle; owner decision required

Two owner-authorized gate cycles, 3 rounds each, are now exhausted. The
deliverable converged to high quality; the gate stays red **only** on the
codex blocking leg, whose final-round finding is — on rigorous independent
analysis — not a real exploitable defect.

Phase 6 stays `in-progress`. The `complete` chokepoint was never invoked
(no PASS token; `aggregate` wrote `passed=false`). PRD Status, Progress
Log, and gate state were not hand-edited. No silent pass.

## Where the deliverable stands (HEAD 0c447b7, base b068a9c)

- `src/compliance_assistant/prod_readiness.py` — deterministic stdlib
  fail-closed audit checker; **leg B: mutation 0.881 ≥ 0.80, changed-line
  coverage 99% ≥ 0.90**.
- `tests/test_prod_readiness.py` — 79 tests; full suite **355 passed / 2
  skipped**, no regression.
- `docs/analysis/2026-05-16-compliance-prod-readiness.md` + `_evidence/`
  receipts — 7-pillar audit, COST/SUS scored against the real
  `analyze_cdk_project` receipt; the checker exits 0 on it.
- Final-round panel: **security PASS, code-reviewer PASS, regression
  PASS, test_integrity PASS, test_engineer advisory** — 5 of 6 legs clean.

## The single remaining blocker — adjudicated

codex (blocking) FAIL, one MAJOR: an inline-code-split marker
(`` `<!`-- token --`>` ``) keeps the prose guard silent while the token
"leaks into downstream scans."

Independently refuted by the other panel legs that traced that exact
attack end to end:
- **security**: the strip-level invariant holds — the counting/cross-ref
  rules read `tokens_text` (inline stripped identically to the guard);
  `cost_sus`/`evidence_anchored` are line-anchored *finding-field*-scoped;
  `_rule_receipts_real` can only *add* a stricter on-disk requirement. No
  surviving string can be **counted** to pass a hollow audit. "No new
  token-injection vector."
- **code-reviewer**: constructed codex's exact bypass; `_HTML_COMMENT`
  (DOTALL) on the full text excises a contiguous well-formed span;
  finding/evidence association is line-anchored. "No token leak path."
- **test_engineer**: every mutant in the changed logic is killed.

codex proved a *string can survive*, not that it can be *counted* to fake
completeness — it never traced countability. Moreover codex's round-3 ask
("an inline marker leaks") directly contradicts its own round-2 ask
("don't false-reject inline/fenced markers"); its suggested fix (strip
backtick spans from `raw` before `_HTML_COMMENT`) would regress the real
audit (which legitimately backticks `_evidence/synth-manifest.txt` in §2)
and/or re-trigger the round-2 false-reject. The finding is a false
positive as a gate-integrity defect.

## Why this stopped here (not silently passed)

The methodology's `complete` chokepoint deliberately cannot be driven by
the agent — only an independent PASS token flips the PRD, and codex
(blocking) returned FAIL. Overriding a blocking leg to force green is the
exact "silent pass" the gate forbids. Adjudicating a blocking-leg FAIL
that contrary independent evidence refutes is an owner decision, the same
human-decision pattern used at every prior fork in this work.

## Owner decision

- **A — Accept Phase 6 on the evidence.** 5/6 legs PASS; the lone codex
  MAJOR is independently refuted (no countable-token leak) and is
  self-contradictory vs. its own prior round. The owner records the
  acceptance decision out-of-band (the chokepoint will not mint a token;
  acceptance is an explicit human override of a tool-gate the agent may
  not bypass). **Recommended** — chasing codex-3 regresses the real audit
  or loops against codex-2.
- **B — One more owner-authorized cycle** to add a *careful* anti-
  injection assertion (NOT codex's risky `raw` backtick-strip) purely to
  turn codex green and obtain an untainted chokepoint PASS token.
- **C — Stop; owner reviews** this report + `findings-6-c2-r2.md` + the
  verdicts and decides later.
- **D — Adjust gate policy** (owner-only): e.g. codex is advisory when ≥2
  independent legs refute its sole finding with traced evidence.
