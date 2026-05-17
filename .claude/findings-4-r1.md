# Phase 4 — Gate round 1 findings (consolidated)

Base `288e4ea` · window `288e4ea..HEAD`. Aggregate FAIL. Fix the ROOT
CAUSE of every BLOCKER/MAJOR + the coverage FAIL + the blocking
policy finding. Do NOT weaken tests, thresholds, fixtures, gold, or the
PRD CHECK set.

## BLOCKER / MAJOR (must fix)

### M1 — Async pre-start race (codex F-001, MAJOR, infra/runtime/server.py)
`_busy()` (server.py ~107) is defined only by `thread.is_alive()`, and
`start_invocation` updates `_RUN["state"]="running"` under `_LOCK`,
releases the lock, THEN `thread.start()` outside the lock. In the
window between lock-release and `thread.start()`: `_busy()` is False, so
(a) `ping()` can report `Healthy` for an already-accepted run, and
(b) a second `POST /invocations` passes the single-flight guard and
returns a second `202` → two concurrent crew runs.
**Root-cause fix:** make busy/single-flight authoritative from the
LOCKED state, not thread liveness — e.g. the `start_invocation` guard
checks `_RUN["state"] == "running"` under `_LOCK`, and `_busy()`/`ping`
derive from `_RUN["state"]` (read under `_LOCK`) rather than
`thread.is_alive()`. Add a regression test that delays/blocks
`Thread.start` (or asserts on state) proving: immediately after the
first `202`, a second `start_invocation()` returns `409` and `ping()`
is `HealthyBusy` (no pre-start gap).

### M2 — Over-broad S3/KMS grant (codex F-002, MAJOR, infra/stacks/runtime_stack.py)
`report_bucket.grant_put(role)` expands to `s3:PutObjectLegalHold`,
`s3:PutObjectRetention`, `s3:PutObjectVersionTagging`, `s3:Abort*`, and
the bucket grant also emits `kms:Decrypt` — none of which the shim's
`upload_file` path needs (server.py ~85-88 only puts objects).
**Root-cause fix:** replace `grant_put` + `report_key.grant_encrypt`
with an explicit least-privilege PolicyStatement: `s3:PutObject`
(+`s3:AbortMultipartUpload` only if needed for boto3 multipart) scoped
to `report_bucket.arn_for_objects("*")`, and KMS `Encrypt` /
`GenerateDataKey*` (+`ReEncrypt*` if required) scoped to the report
key — NO `kms:Decrypt`, NO LegalHold/Retention/VersionTagging/Abort*.
Add/extend a test asserting the runtime role's S3 actions are exactly
the upload set and KMS has no `Decrypt`.

### B1 — Commit-subject jargon (code-reviewer LEG D, blocking policy)
The judged-window commit subjects (and the gate-infra base commit
subject) use `phase 4 (...)` / `phase 4 bar` — a roadmap-position
label the user's global CLAUDE.md forbids in commit messages and says
reviewers must treat as blocking. Per the user's stated priority
(user CLAUDE.md > skills), this outranks the phase-gate skill's
prescribed `phase <P>` format.
**Root-cause fix (orchestrator-level):** reword the judged-window
commit subjects to intent/outcome (e.g. `add AgentCore Runtime CDK
stack + async HTTP shim`, `add runtime-IaC plan`, `revise runtime-IaC
plan per adversarial review`) and the gate-infra base commit subject
(drop "phase 4 bar"), then re-pin. Keep PRD/plan/docstring prose
("Phase 4", "observability phase") — those are real phase identities,
allowed.

## Objective-leg FAIL

### C1 — Changed-line coverage 88% < 90% floor (LEG B)
Uncovered: `infra/app.py` 3-stack wiring + `add_dependency` (runs only
in the `cdk synth` subprocess pytest can't see); `server.py`
`_Handler.do_GET/do_POST/_send/log_message`, `serve()`, `__main__`
(offline test calls functions, never the socket).
**Root-cause fix (genuine tests, not coverage theater):**
1. Direct synth test (test-engineer #4): build all three stacks in one
   `cdk.App`, assert `runtime.dependencies` includes the agent stack
   AND `ComplianceRuntimeStack` takes no `knowledge_base` kwarg — tests
   the real deploy-ordering invariant.
2. One compact in-process socket test: `ThreadingHTTPServer` on port 0,
   `http.client` → `GET /ping`, `GET /status`, `POST /invocations`
   (with body, asserting drain + 202), `GET /unknown` → 404. Covers the
   handler routing + Content-Length/404 logic that the AgentCore wire
   contract depends on.
3. test-engineer correctness gaps (also raise coverage AND value):
   `REPORT_BUCKET` unset → run `failed` (not hung); S3 `upload_file`
   raises mid-upload → `failed`, not silent grounded-success.
Re-measure changed-line coverage ≥ 0.90 vs base.

## MINOR / advisory (fix the cheap correctness ones; rest optional)

- F-003 (codex MINOR): align the cfn-lint repro command across
  `infra/README.md` and the plan to the actual installed CLI:
  `cfn-lint -r us-east-1 ... cdk.out/ComplianceRuntimeStack.template.json`
  (1.41.0 uses `-r/--regions`, not `--region`).
- test-engineer #3: tighten `test_runtime_stack.py` SSM assertion —
  bind the two parameter ARNs to a statement whose Action includes
  `ssm:GetParameter` and assert no `parameter/compliance-assistant/*`
  prefix / no `Resource:"*"`.
- code-reviewer nit: `runtime_stack.py` `... or ("latest")` → drop the
  parens.
- Security MINORs (non-blocking, sample-acceptable, OPTIONAL): `/status`
  returns `repr(exc)` (split caller category vs log-only); access-logs
  bucket SSE-S3 not KMS. Note in README if not changing; not required.

## Not in scope to change
review_gate/* and .claude/review-gate.config.json are BASE (gate
machinery / owner-set bar) — must remain out of the judged window.
No src/ or tests/evals/ changes (Phase 2 mutation surface + Phase 3
gold/harness frozen).
