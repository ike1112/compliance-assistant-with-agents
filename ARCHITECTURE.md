# Architecture — Compliance Assistant production-hardening

This document is the engineering deep dive. For "what is this and how do I
run it," see [README.md](README.md). For the full WA-Lens audit, see
[`docs/analysis/2026-05-16-compliance-prod-readiness.md`](docs/analysis/2026-05-16-compliance-prod-readiness.md).

The goal of this work was not to ship a feature. It was to convert an AWS
sample with click-ops grounding, no IaC, no evals, no observability, and
zero citations on its output into something defensible to a senior reviewer.
The methodology is the [AWS Well-Architected GenAI Lens](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html),
applied as a six-phase decomposition with each phase gated by an
independent six-leg review panel.

## 1. What was inherited vs what was built

The starting point was a CrewAI sequential pipeline (3 agents, 3 tasks)
that called a Bedrock Agent with a Knowledge Base behind it. Everything
about the *infrastructure* — the Agent, the KB, the Guardrail, the data
source, the chunking config — was click-ops. The crew read `AGENT_ID` and
`AGENT_ALIAS_ID` from a `.env` file with placeholder values. The generated
report had no citations. There were no evals, no SLOs, no IaC, and no
quality gate.

The original artifacts are preserved under
[`analysis/_legacy/`](analysis/_legacy/) for "before/after" contrast — see
in particular `DEPLOYMENT_READINESS_REVIEW.md` (an ad-hoc pre-hardening
review) and the original architecture diagrams.

What was added:

- **CDK IaC for the entire Bedrock knowledge layer**, replacing click-ops:
  S3 PDF corpus + KMS + access logs, Aurora Serverless v2 pgvector,
  Knowledge Base + data source, Bedrock Agent + alias + attached
  Guardrail. SSM publishes the Agent IDs that the crew reads at startup.
  → [`infra/stacks/kb_stack.py`](infra/stacks/kb_stack.py),
  [`infra/stacks/agent_stack.py`](infra/stacks/agent_stack.py)
- **Fail-fast startup validation** so the crew refuses to start with
  placeholder values, missing IDs, or invalid models.
  → [`src/compliance_assistant/startup.py`](src/compliance_assistant/startup.py),
  [`tests/test_startup.py`](tests/test_startup.py)
- **An offline RAG evaluation harness** (retrieval, generation,
  task-level), grounded by a labeled PCI DSS gold set with author
  provenance, gated in CI.
  → [`tests/evals/`](tests/evals/)
- **AgentCore Runtime IaC** plus a documented Fargate fallback,
  with an async pre-start shim that meets the AgentCore HTTP contract.
  → [`infra/stacks/runtime_stack.py`](infra/stacks/runtime_stack.py),
  [`infra/stacks/runtime_ecr_stack.py`](infra/stacks/runtime_ecr_stack.py)
- **A tracing + redaction layer** wired to real CrewAI 1.x callbacks,
  emitting EMF metrics with PAN/email redaction on the path to logs.
  → [`src/compliance_assistant/tracing.py`](src/compliance_assistant/tracing.py),
  [`tests/test_tracing.py`](tests/test_tracing.py),
  [`tests/test_redaction.py`](tests/test_redaction.py)
- **SLO-anchored CloudWatch alarms.** [`docs/SLOs.md`](docs/SLOs.md) is
  the single source of truth — the observability stack parses it and
  creates one alarm per row; an infra test re-parses the same table and
  cross-checks the synthesized template so the alarms cannot drift from
  the document.
  → [`docs/SLOs.md`](docs/SLOs.md),
  [`infra/stacks/observability_stack.py`](infra/stacks/observability_stack.py),
  [`infra/stacks/slo_contract.py`](infra/stacks/slo_contract.py)
- **An evidence-backed WA-Lens audit** of the synthesized stack across
  all seven pillars, with six-field Reasoning-Gate findings and
  `analyze_cdk_project` + cfn-guard receipts.
  → [`docs/analysis/2026-05-16-compliance-prod-readiness.md`](docs/analysis/2026-05-16-compliance-prod-readiness.md),
  [`docs/analysis/_evidence/`](docs/analysis/_evidence/)
- **A meta-quality system**: the 6-leg review gate that ran on every
  phase, with mutation + coverage floors and a per-phase tunable bar.
  → [`review_gate/`](review_gate/),
  [`tests/review_gate/`](tests/review_gate/)

## 2. System shape (post-deploy)

```
+-----------------------------------------------------------------------+
|                            User / operator                            |
+----+----------+----------+----------+----------+----------+-----------+
     |          |          |          |          |          |
     v          v          v          v          v          v
+---------+ +--------+ +--------+ +---------+ +---------+ +------------+
| CrewAI  | | trace  | | start- | | report  | | redact  | | quality    |
| crew    | | layer  | | up val | | source  | | layer   | | gate (CI)  |
| sequen- | | (EMF + | | (fail- | | refs    | | (PAN /  | | (panel +   |
| tial    | | spans) | | fast)  | | (inline)| | email)  | |  mutation) |
+---------+ +--------+ +--------+ +---------+ +---------+ +------------+
     |
     | invokes
     v
+-----------------------------------------------------------------------+
|  Bedrock Agent (R-BR-AGENT) + Alias (R-BR-ALIAS) + Guardrail          |
|                                                                       |
|              + retrieves from                                          |
|              v                                                         |
|  Bedrock Knowledge Base (R-KB)                                         |
|              ^                                                         |
|              | vector store                                            |
|              |                                                         |
|  Aurora Serverless v2 + pgvector (R-AURORA-VEC, min ACU 0)             |
|              ^                                                         |
|              | ingestion                                               |
|              |                                                         |
|  S3 PDF corpus (R-S3-CORPUS) -- versioned, SSE-KMS, access logging     |
+-----------------------------------------------------------------------+
     |
     | runtime hosting (8h, scale-to-zero)
     v
+-----------------------------------------------------------------------+
|  AgentCore Runtime (R-AC-RUNTIME)  + ECR image (separate stack)       |
|        +                                                              |
|        | reports to                                                   |
|        v                                                              |
|  S3 versioned report bucket (R-S3-REPORT)                             |
+-----------------------------------------------------------------------+
     |
     | metrics, traces, logs
     v
+-----------------------------------------------------------------------+
|  CloudWatch dashboard (R-CW-DASH) +                                   |
|  composite alarms (R-CW-ALARMS)   <-- thresholds == docs/SLOs.md rows |
|  Bedrock model-invocation logging (R-MIL)                             |
|  Runtime container logs (R-AC-OBS) -- CloudWatch Logs, IAM grant      |
+-----------------------------------------------------------------------+
```

Resource IDs (R-\*) match the catalog in
[`docs/analysis/2026-05-16-compliance-prod-readiness.md`](docs/analysis/2026-05-16-compliance-prod-readiness.md) §3.1.

Five CDK stacks synthesize: `ComplianceKbStack`, `ComplianceAgentStack`,
`ComplianceRuntimeEcrStack`, `ComplianceRuntimeStack`,
`ComplianceObservabilityStack`. `cdk synth --all -q` returns 0 on a clean
checkout. `analyze_cdk_project` confirms there is no OpenSearch in the
inventory — the vector store decision was Aurora pgvector (rejected
OpenSearch Serverless on idle cost).

## 3. Phase-by-phase narrative

Each phase has its own plan under [`.claude/PRPs/plans/completed/`](.claude/PRPs/plans/completed/)
and was gated by the same panel composition (see §4). The PRD's
[Implementation Phases table](.claude/PRPs/compliance-prod-hardening.prd.md)
is the spine; what follows is the narrative.

### Phase 1 — Bedrock knowledge-layer IaC

**Problem:** the click-ops Agent + KB + Guardrail were un-auditable. The
crew's `.env` carried real account-scoped resource IDs.

**Decisions:**
- Aurora Serverless v2 pgvector (min ACU 0, scale-to-zero) instead of
  OpenSearch Serverless — interview-grade defensible on idle cost.
- KMS-encrypted S3 corpus with versioning + access logging.
- KB type explicitly RDS; chunking config is a CDK context value
  (`infra/cdk.json`) whose winner is selected by the Phase 3 eval harness,
  not by guess.
- Agent + alias provisioned in code, with Guardrail attached and
  citations on.
- Agent/KB IDs published to SSM with the exact crew-contract names; the
  crew reads SSM at startup, not `.env`.

**Verification:** [`infra/tests/`](infra/tests/) assert OpenSearch count
== 0, RDS `MinCapacity == 0`, every IAM policy resource ≠ `"*"`, every S3
bucket blocks public + uses KMS/TLS, KB Type==RDS, and 2 SSM parameters
exist with the crew-contract names. cfn-lint returns 0 errors.
`ComplianceAgentStack` is cfn-guard COMPLIANT.

**Status:** build complete; billable `cdk bootstrap` + `deploy` is
operator-gated (HUMAN-GATE in the PRD).

### Phase 2 — Config & secrets hardening

**Problem:** the original startup only checked for a `TOPIC` env var.
`replace-with-...` placeholders silently passed validation; failure
surfaced deep inside a Bedrock call.

**Decisions:** fail-fast on missing or placeholder values for `TOPIC`,
`MODEL`, and any agent-id resolution path. Verbosity gated by env var,
default off. `.env.example` parity test: every `os.environ` key read
under `src/` must appear in `.env.example`. `uv.lock` is git-tracked;
`uv sync --frozen` exits 0.

**Verification:** [`tests/test_startup.py`](tests/test_startup.py) +
[`tests/test_agent_ids.py`](tests/test_agent_ids.py).

### Phase 3 — RAG evaluation harness (interview-grade strict)

**Problem:** the project claimed RAG correctness but had no way to score
it. Worse: there was no signal that the model was actually grounding
answers vs. hallucinating regulatory language.

**Decisions:**
- Gold set: ≥ 30 positive items (question + ≥1 expected source-passage
  locator) + ≥ 8 out-of-corpus negatives. **Authored by codex, not by
  ralph** — the harness checks that the gold set was not modified by
  the judged diff (you cannot grade your own answers).
  → [`tests/evals/gold/`](tests/evals/gold/),
  [`tests/evals/gold/PROVENANCE.md`](tests/evals/gold/PROVENANCE.md)
- Deterministic offline gate: `pytest tests/evals -m gate -q` runs
  against recorded retrieval and generation fixtures — no Bedrock spend.
  Live re-recording is opt-in via `-m live`.
- Thresholds (mean over gold set): context-recall ≥ 0.90,
  context-precision ≥ 0.80, MRR ≥ 0.80, faithfulness ≥ 0.95,
  citation-correctness ≥ 0.95, hallucination-rate ≤ 0.05,
  not-found-honesty == 1.0 (every out-of-corpus question explicitly says
  "not in knowledge base"; zero fabricated requirements),
  requirement-coverage ≥ 0.90.
- The chunking decision is owned by this phase: the harness scores ≥ 2
  configs, writes [`tests/evals/report.md`](tests/evals/report.md), and
  a test asserts that `infra/cdk.json` context matches the report's
  winner. The chunking value is data, not opinion.

**Verification:** [`tests/evals/test_gate.py`](tests/evals/test_gate.py),
[`tests/evals/test_chunking_decision.py`](tests/evals/test_chunking_decision.py),
[`tests/evals/test_gold_frozen.py`](tests/evals/test_gold_frozen.py).

### Phase 4 — AgentCore Runtime IaC

**Problem:** the crew is a batch job (long-running, idempotent). It
needs a runtime that scales to zero between invocations.

**Decisions:** AgentCore Runtime as the primary target, with a
documented Fargate fallback (run-to-completion, arm64, no NAT, S3-versioned
report output) so the maturity question doesn't block the deliverable.
The runtime image is in a separate stack (`ComplianceRuntimeEcrStack`) so
image lifecycle is decoupled from runtime config. An async pre-start shim
satisfies the AgentCore HTTP contract without blocking the cold-start
path.

**Verification:** [`infra/tests/test_runtime_stack.py`](infra/tests/),
runtime runbook in [`infra/README.md`](infra/README.md) names the Phase 3
eval gate as a required pre-deploy step.

### Phase 5 — Observability + SLOs (test-enforced)

**Problem:** "observability" usually means "add some logs." This phase
required SLOs that are *numeric* and *test-asserted*, not aspirational.

**Decisions:**
- [`docs/SLOs.md`](docs/SLOs.md) is the single source of truth. Each
  row is one SLO: per-stage + end-to-end latency p50/p95, quality
  (faithfulness + citation-correctness from Phase 3), availability
  (run-success-rate). Every row has a numeric threshold and a 30-day
  error budget.
- `ComplianceObservabilityStack` parses the markdown table at synth
  time and creates exactly one alarm per row, bound to that row's
  metric with that row's threshold.
- The infra test re-parses the same table and cross-checks the
  synthesized CloudFormation: alarm count == row count, and each
  alarm's threshold == the matching row's number. The alarms cannot
  drift from the document.
- Tracing emits three stage spans (researcher / writer / designer)
  each with non-empty input, output, and tool-call list — a captured
  fixture asserts this, making "monitor input and output at each
  agent level" binary.
- A redaction test feeds a known fake PAN/email through the logging
  path and asserts it is masked/absent in emitted logs/traces.

**Verification:** [`tests/test_tracing.py`](tests/test_tracing.py),
[`tests/test_redaction.py`](tests/test_redaction.py),
[`infra/tests/test_observability_stack.py`](infra/tests/).

### Phase 6 — Evidence-backed WA-Lens audit

**Problem:** the spine deferred the "score against the as-built system"
audit because the as-built system didn't exist yet. After Phases 1-5,
this phase produced the audit.

**Decisions:** all seven Well-Architected pillars, each with at least one
six-field Reasoning-Gate finding (Risk / Evidence / Why this matters here
/ Source / Counter-argument / Fix) or an explicit "checked, not a gap
because X" line. Every gap has all six fields. Every evidence reference
is a `file:line` in this repo or a receipt under
[`docs/analysis/_evidence/`](docs/analysis/_evidence/). No `TBD` or
placeholders. The audit is produced against synthesized templates only;
HUMAN-GATE: none.

**Closure:** see §5 — this phase closed by **owner-acceptance**, not by
the gate's automatic PASS path. The mechanics of that override are
visible in the PRD Progress Log and in
[`.claude/review-gate.verdicts.json`](.claude/review-gate.verdicts.json).

**Verification:** the audit document itself plus a machine checker that
asserts the document's invariants
([`src/compliance_assistant/prod_readiness.py`](src/compliance_assistant/prod_readiness.py),
[`tests/test_prod_readiness.py`](tests/test_prod_readiness.py)).

## 4. The quality gate machine

`review_gate/` is the part of the system that made the multi-phase
autonomous work credible. It is its own subsystem with its own tests
([`tests/review_gate/`](tests/review_gate/)).

The gate runs on every phase boundary:

```
                +---------------------+
                |   prp-ralph build   |
                +----------+----------+
                           |
                           v   per-phase diff vs base_sha
                +---------------------+
                |   panel (6 legs)    |
                +----------+----------+
                           |
   +-----------+-----------+-----------+-----------+-----------+
   |           |           |           |           |           |
   v           v           v           v           v           v
+------+   +------+   +------+   +------+   +------+   +------+
|codex |   |secur-|   | code |   | test |   | reg- |   |muta- |
|adver-|   |ity-  |   |re-   |   |engi- |   |ress- |   |tion+ |
|sarial|   |audit-|   |viewer|   |neer  |   |ion   |   |cov.  |
+------+   |or    |   +------+   +------+   |(CHECK|   |floor |
           +------+                          | items|   +------+
                                             | green|
                                             |  )   |
                                             +------+

   - BLOCKER/MAJOR on any leg                          -> FAIL
   - Mutation kill-rate < per-phase floor              -> FAIL
   - Changed-line coverage < per-phase floor           -> FAIL
   - Any CHECK item in PRD regresses                   -> FAIL
   - All legs PASS                                     -> PASS
```

The gate has a `complete` chokepoint that mints a PASS token. The PRD
table's `Status` column is updated only via that token. `prp-ralph`
finishing its plan is necessary but not sufficient — and prp-ralph
itself is forbidden from editing the `Status` column.

Per-phase floors live in
[`review_gate/config.py`](review_gate/config.py) and are tuned per phase
(Phase 3 is interview-grade strict; Phase 5 is test-enforced; etc.).

## 5. The Phase 6 owner-acceptance

Phase 6 closed by **explicit owner-acceptance** rather than an automatic
gate PASS. Two cycles of three rounds each ran on the audit deliverable;
on the final round, five of the six legs returned PASS but the codex
adversarial leg returned FAIL on a single MAJOR finding — an inline-code
split comment that the codex leg believed leaked a real token marker.
The security leg, the code-reviewer leg, and the test-engineer mutant
sweep independently traced and refuted the claim. Mutation kill-rate on
leg B was 0.881; changed-line coverage was 99%.

The owner reviewed the findings in
[`.claude/findings-6-c2-r3.md`](.claude/findings-6-c2-r3.md), determined
the codex finding was adjudicated-spurious, and accepted the deliverable
on the evidence — overriding the dissenting block with a written
defense in the PRD Progress Log (2026-05-19 entry).

The gate state is preserved: `aggregate` wrote `passed=false` and the
`complete` chokepoint was correctly never invoked. The dissenting
record stays in [`.claude/review-gate.verdicts.json`](.claude/review-gate.verdicts.json).

This is the kind of decision a real production-engineering practice has
to make periodically: a gate fires on a contested finding, an
independent panel disagrees, and a human adjudicates with a written
defense. Hiding it would be worse than owning it. Specifically, the
override is defensible because:

- It is **traceable**: gate state, both sets of findings, and the
  override rationale are all in the repo, in one commit
  (`65ab9d1`).
- It is **bounded**: the override applies only to this one phase; no
  precedent rule was added.
- It is **adjudicated**: five legs independently refuted the dissenting
  finding before the owner accepted.
- It is **preserved as dissent**, not erased.

## 6. Engineering posture (deliberate calls that look like gaps)

Three things in this repo look like gaps but are intentional:

**Synth + test ≠ deploy.** The PRD's `CHECK:` items are autonomous and
free (synth, lint, pytest, cfn-guard). `HUMAN-GATE:` items are
operator-gated because they cost money — `cdk deploy` runs Aurora
pgvector, Bedrock Agent provisioning, AgentCore Runtime startup, and KB
ingestion. An autonomous loop running deploy would burn spend and
silently drift the stack. The line is drawn at "anything the
CloudFormation API mutates in real AWS." See the *HUMAN-GATE* rows in
the PRD's Success Criteria section.

**`docs/` is mostly working notes.** Only named deliverables are
tracked: the SLO contract, the eval contract, the WA-Lens audit, and its
evidence receipts. The original spec/plan under `docs/superpowers/` is
intentionally untracked — superseded by code that is the source of
truth. See `.gitignore` for the exact set. This rule has one documented
exception (Progress Log 2026-05-19 in the PRD).

**Phase 6 closed by owner-acceptance, not gate PASS.** Covered above
in §5.

## 7. Reading order for a senior reviewer

If you have 5 minutes: this file, plus
[`docs/analysis/2026-05-16-compliance-prod-readiness.md`](docs/analysis/2026-05-16-compliance-prod-readiness.md) §1-3.

If you have 30 minutes: add [`docs/SLOs.md`](docs/SLOs.md) (the contract),
[`infra/stacks/observability_stack.py`](infra/stacks/observability_stack.py)
(how the contract is mechanically enforced), and the full WA-Lens audit.

If you want to verify on a clean checkout: follow the *Quick start* in
[README.md](README.md). All four commands exit 0 deterministically.

## License

MIT-0. See [LICENSE](LICENSE).
