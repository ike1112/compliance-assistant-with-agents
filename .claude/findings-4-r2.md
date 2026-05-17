# Gate round 2 findings (consolidated) — FINAL remediation

Base `95efaf9` · window `95efaf9..HEAD`. Aggregate FAIL. Round 1 items
all verified RESOLVED (codex+security+code-reviewer concur). Two new
MAJOR drivers + cheap advisory polish. This is the last allowed
remediation — fix everything at root cause, exhaustively.

## MAJOR (must fix)

### M3 — ECR/runtime bootstrap cycle + gate bypass (codex F-004)
`ComplianceRuntimeStack` creates the ECR repo AND the
`AWS::BedrockAgentCore::Runtime` that references `repo_uri:tag` in the
SAME stack. On a clean account, the first `cdk deploy
ComplianceRuntimeStack` creates the repo then the runtime referencing
an image that does not exist yet → CreateAgentRuntime fails. The README
runbook also says `deploy --all` (now including the runtime) BEFORE the
image push and BEFORE the RAG eval gate, which both breaks first-deploy
and lets the runtime bypass its required pre-deploy gate.
**Root-cause fix:**
- New `infra/stacks/runtime_ecr_stack.py` `ComplianceRuntimeEcrStack`:
  the ECR repo only, with a DETERMINISTIC `repository_name` (so the
  push target is knowable from account/region before the runtime
  stack exists), `image_scan_on_push`, IMMUTABLE tags, RETAIN.
- `ComplianceRuntimeStack` no longer creates the repo: take it as a
  `*, ecr_repository` ctor arg (a real used cross-stack ref — not the
  unused-arg anti-pattern); scope the role's ECR pull to its ARN and
  build `container_uri` from its URI + the context tag.
- `app.py`: instantiate the ECR stack; `runtime.add_dependency(ecr)`
  and keep `add_dependency(agent)`; update the docstring.
- `infra/README.md` runbook: REMOVE `deploy --all`; ordered explicit
  deploy — KB + Agent + ECR first, then the RAG eval gate MUST pass,
  then build/push the linux/arm64 image to the deterministic repo,
  then and only then `cdk deploy ComplianceRuntimeStack`. State plainly
  the runtime stack is in no bulk deploy and cannot bypass the gate.
- Tests: new `test_runtime_ecr_stack.py` (repo present, deterministic
  name, immutable, scan-on-push, RETAIN); update the runtime-stack
  fixture to pass an imported/test repo; update the wiring test for
  the new `ecr_repository` arg + `add_dependency(ecr)`; keep the
  sole-wildcard / least-priv / no-NAT assertions green.

### B2 — Task-position-label jargon in the committed plan (code-reviewer LEG D, blocking)
`.claude/PRPs/plans/phase-agentcore-runtime-iac.plan.md` uses
`### Task 1` … `### Task 9` headings (9) plus risk-table
back-references "Task 8 asserts / Task 7 regression-guards / Task 8
covers / Task 1 verifies" (4) = 13. The user's global CLAUDE.md
forbids `Task N` task-position labels in durable artefacts and says
reviewers must treat it as blocking; per the user's stated priority
this outranks the prp-plan skill template that induced it.
**Root-cause fix:** rename every step heading to an intent/deliverable
heading (no ordinal) and rewrite the back-references to name the work
(e.g. "the offline async-contract test asserts non-blocking", "the
synth-contract test regression-guards `bedrock:InvokeAgent`"). Keep
real phase identities ("Phase 1 runbook", "observability phase") —
those are allowed. Then re-scan the whole judged window: infra code,
comments, docstrings, README confirmed clean; gate records
(`findings-*.md`, `review-gate.verdicts.json`) necessarily quote the
findings and are ephemeral gate-run records named by the gate skill —
out of the durable-artefact rule's intent, left as-is.

## Advisory (cheap, do them — final round, no value left behind)
- test-engineer: add `POST /nope` → 404 to the socket test (server.py
  do_POST else arm, 1 line) and a completed→new-run transition test
  (after a completed run, `ping` Healthy and a fresh `start_invocation`
  is accepted). Both genuine, ~few lines.

## Not in scope
review_gate/* and .claude/review-gate.config.json stay BASE. No src/
or tests/evals/ change. PRD CHECK set unchanged.
