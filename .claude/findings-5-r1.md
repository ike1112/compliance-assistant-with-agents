# Phase 5 — Gate round 1 findings (consolidated)

Base `0c6399d` · window `0c6399d..HEAD`. Aggregate FAIL. Two MAJORs
that converge on one root cause: the observability is a SHELL —
nothing real is captured or emitted, so the fixture is hand-authored
and the alarms watch metrics nothing produces. Fix at root; do NOT
weaken tests/CHECKs/fixtures/gold.

## BLOCKER / MAJOR (must fix)

### M1 — Tracer cannot map real CrewAI callback payloads (code-reviewer MAJOR, src/compliance_assistant/tracing.py)
`_span_for` (tracing.py ~136-153) assumes `obj.role`/`obj.name`/
`obj.agent.role`. In CrewAI 1.14.4 `TaskOutput.agent` is a role
**string** and the `step_callback` payload (`AgentAction`-shaped) has
no `.agent`. Against real shapes every branch returns `None` → zero
spans captured. So `Tracer.record()` on a real `TRACING_LIVE=1` run
emits empty spans, which means the committed `run_spans.json` could
NOT have been produced by this code from a real run — it was
hand-authored. The plan-review's resolved "live-recorder-only +
provenance" mitigation is therefore unenforced in the build, and
`test_live_recapture_round_trips` is a stub (`hasattr` only).
**Root-cause fix:** make `_span_for` resolve CrewAI 1.14.4's real
callback shapes — accept a role `str` directly; for `on_step` map via
the agent role actually reachable on the 1.14.4 step payload (inspect
the real object `Crew.step_callback`/`task_callback` passes, not
assumed attribute names). Add a unit test that feeds real-shaped
`TaskOutput` (`agent="Regulation Researcher"`, `description=…`,
`raw=…`) and a real-shaped tool step through `on_task`/`on_step` and
asserts `.spans()` yields exactly the 3 PRD names, researcher-only
non-empty `tool_calls`, round-tripped through `record()`→`verify()`.
Regenerate `run_spans.json` from that exercised path.

### M2 — SLO alarms watch metrics nothing emits (codex F-001 MAJOR)
`docs/SLOs.md` says the latency/availability metrics are emitted by
the tracing module; the stack binds alarms to those metric names; the
test re-parses the same file. But NO changed runtime/tracing code
emits `ComplianceAssistant/Crew` (or `/Quality`) metrics —
`build_tracer` is a passive sink that only writes fixture JSON. The
alarm↔SLO cross-check is circular: it proves the alarm matches the
document, not that the metric is real. An alarm can pass while
watching a metric that is never produced.
**Root-cause fix:** add a real producer for the `ComplianceAssistant/
Crew` metrics the SLOs name (`ResearcherLatencySeconds`,
`WriterLatencySeconds`, `DesignerLatencySeconds`, `RunLatencySeconds`,
`RunSuccessRate`) — emit them via CloudWatch **EMF** (a structured log
line; no boto3/PutMetricData/IAM in the crew path, ingested as metrics
by CloudWatch Logs) from the tracer at run completion. The
`ComplianceAssistant/Quality` metrics (`Faithfulness`,
`CitationCorrectness`) are produced by the Phase-3 eval harness — bind
those rows to that producer and document it. Add a NON-circular
producer-contract test: the emitter, given spans + outcome, produces
EMF whose metric names/namespace are EXACTLY the SLO rows it owns
(derived from the same `slo_contract`, asserting producer⊇crew-SLOs),
so SLOs.md ← emitter and SLOs.md → alarms are tied through real code.

### M3 — Hash-binding is never test-proven (test-engineer #1; gate-integrity)
Deleting the sha-recompute loop from `tracing.verify()` leaves the
whole tracing suite green — `test_fixture_is_provenance_and_hash_bound`
only checks the untouched committed fixture. The headline "a
hand-edited fixture fails" is unproven; the gate could be gamed by
editing fixture+code together. **Root-cause fix:** add a test that
deep-copies the fixture, mutates one span's `output`, and asserts
`tracing.verify(tampered)` raises matching `sha256 mismatch`. Treat as
must-fix (gate-integrity), not advisory.

## MINOR (fix the cheap correctness ones)
- PAN regex (security MINOR + codex F-002): broaden the separator class
  to `[ \-./]` (dot/slash card forms leak today) AND add a right
  boundary `(?!\d)` so a Luhn-valid 13–19 prefix inside a longer digit
  run is not partially masked. Regression tests for both.
- code-reviewer MINOR: `test_tracing.py` email assertion is tautological
  (`[REDACTED-EMAIL]` has no `@`); replace with
  `assert not tracing._EMAIL_RE.search(blob)`.
- test-engineer #3: parametrized `slo_contract` test asserting
  `SLO(comparator=k).comparison_operator == COMPARATORS[k]` for all 4
  keys (the gte/lte mapping is currently dark).
- security MINOR: keep the tamper-evidence claim but make it TRUE via
  M3 (real tamper test); the docstring stays once enforced.

## Not in scope
No change under `agent_ids.py` (Phase-2 frozen), `citations.py`
(Phase-5 mutation target, ≥0.80 untouched), `tests/evals/gold/`
(Phase-3 frozen), `review_gate/` or `.claude/review-gate.config.json`
(BASE). Plan Validation stays the verbatim PRD lines. No jargon.
