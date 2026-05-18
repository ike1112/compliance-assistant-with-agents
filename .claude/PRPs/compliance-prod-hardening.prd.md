# PRD: Compliance Assistant Production-Hardening

**Owner:** ike1112
**Created:** 2026-05-15
**Source spec:** `docs/superpowers/specs/2026-05-15-compliance-prod-hardening-design.md`
**Backlog:** `docs/analysis/2026-05-15-compliance-hardening-backlog.md`
**Methodology:** AWS Well-Architected GenAI Lens + Reasoning Gate (spec §2)

---

## Problem Statement

The compliance assistant is a local CrewAI CLI whose grounding layer (Bedrock Agent + Knowledge Base + Guardrail) is un-auditable click-ops, whose corpus is a non-reproducible web crawl, whose reports carry zero source citations (`analysis/a.md`), and which has no IaC, evals, observability, or deployable runtime. It is not credibly production-ready and cannot be defended to a senior/staff reviewer.

## User & Value

As the owner/reviewer of the compliance assistant, I want every grounding decision reproducible, evaluated, observable, and citation-backed, so the system is genuinely production-ready and demonstrably defensible.

## Hypothesis / Success Signal

Driving the work from a WA-Lens prioritized backlog (Reasoning-Gate-defended gaps, mechanical ranking) yields a sequence of self-contained sub-projects, each shippable and verifiable on its own, ending in an evidence-backed prod-readiness analysis against the real synthesized stack.

## Scope Decisions (locked — see spec §8)

- Vector store: Aurora Serverless v2 pgvector (OpenSearch Serverless rejected on idle cost).
- Runtime: AgentCore Runtime + Observability only (ECS Fargate documented fallback).
- Sequencing: design-to then audit-against Well-Architected.
- `docs/` stays untracked working notes; `infra/`/`src/`/`tests/` code and this PRD + plans under `.claude/PRPs/` are tracked.

---

## Implementation Phases

Each phase is an independent sub-project with its own prp-plan and autonomous validation loop. `Status` ∈ `pending | in-progress | complete`. A phase is actionable only when every listed dependency is `complete` (independent phases may run in parallel in separate worktrees).

| # | Phase (intent) | Depends on | Status | PRP Plan | Closes gaps |
|---|----------------|-----------|--------|----------|-------------|
| 1 | Bedrock knowledge-layer IaC — S3 PDF corpus, Aurora pgvector, KB + configurable chunking, Guardrail-attached Agent + alias, citations on, SSM-published ids | — | in-progress | `.claude/PRPs/plans/bedrock-knowledge-layer-iac.plan.md` | GAP-OPS-01, GAP-SEC-01, GAP-SEC-02, GAP-GENAI-01 |
| 2 | Config & secrets hardening — fail-fast startup validation rejecting placeholders, verbose gated by env, lockfile-deploy verification, `.env.example` sync | — | complete | _(not yet planned)_ | GAP-SEC-04, GAP-OPS-04, GAP-OPS-05 |
| 3 | RAG evaluation harness — retrieval / generation / task-level gold sets + LLM-as-judge + CI gate; decides the real chunking value | 1 | complete | `.claude/PRPs/plans/phase-rag-evaluation-harness.plan.md` | GAP-GENAI-02, GAP-GENAI-03 |
| 4 | AgentCore Runtime IaC — host the crew (8h, scale-to-zero); AgentCore IaC maturity verified vs current docs; Fargate fallback documented | 1 (release-gated by 3) | complete | `.claude/PRPs/plans/phase-agentcore-runtime-iac.plan.md` | GAP-REL-01, GAP-PERF-01 |
| 5 | Observability + SLOs — AgentCore Observability wiring, model-invocation logging, `docs/SLOs.md`, composite alarms, verbose redaction | 1, 4 | complete | `.claude/PRPs/plans/phase-observability-slos.plan.md` | GAP-OPS-02, GAP-SEC-03, GAP-OPS-03 |
| 6 | Evidence-backed prod-readiness analysis — full WA-Lens audit against the synthesized stack (cfn-guard, analyze_cdk_project, all 7 pillars) | 1, 2, 3, 4, 5 | pending | _(not yet planned)_ | (audit deliverable; scores COST/SUS deferred from the spine) |

**Parallelism:** Phases 1 and 2 have no dependencies on each other and may run concurrently in separate worktrees.

**`/goal` scope:** the `CHECK:` items of Phases 2–6 (see Success Criteria). All `HUMAN-GATE:` items (billable `cdk deploy`/`bootstrap`, post-deploy live verification) are excluded — `/goal` must not run or auto-pass them; it stops and reports when only a HUMAN-GATE remains.

**Next actionable:** Phase 1 autonomous build is done (HUMAN-GATE deploy outstanding → still `in-progress`). Phase 2 (independent) and Phase 3 (RAG evals — its CHECK suite is deterministic/offline, so it does **not** need the deployed stack, only Phase 1's committed code + `cdk.json`) are both `/goal`-actionable now and parallelizable.

---

## Progress Log

- 2026-05-17 — phase 5 -> complete via quality gate (base_sha=0c6399da8027b22cc1687be9149ac7cbcda26e15 passed=True phase=5 round=3 ts=2026-05-18T00:09:19.940293+00:00).
- 2026-05-17 — phase 4 -> complete via quality gate (base_sha=95efaf96e744c83e624b6b0f28abfc5fb982dc93 passed=True phase=4 round=3 ts=2026-05-17T20:27:40.547667+00:00).
- 2026-05-16 — phase 3 -> complete via quality gate (base_sha=2dd18538b0777c6a3eb8d2d6b1dee659f90aa94c passed=True phase=3 round=3 ts=2026-05-17T00:52:10.239820+00:00).
- 2026-05-16 — phase 2 -> complete via quality gate (base_sha=df224338b838be286670ff5d1de35abbb182c982 passed=True phase=2 round=1 ts=2026-05-16T22:20:21.298352+00:00).
Append one line per phase status change (newest last). prp-ralph / prp-plan update this and the table above.

- 2026-05-15 — PRD created. Phase 1 planned (`bedrock-knowledge-layer-iac.plan.md`) and set in-progress. Phases 2-6 pending.
- 2026-05-16 — Phase 1 autonomous build COMPLETE via prp-ralph (4 iterations, 9 commits). All synth-time gates green: `cdk synth --all` 0, 24 tests pass, cfn-lint 0 errors, agent-stack cfn-guard COMPLIANT, no OpenSearch, Aurora 0-ACU. Plan archived to `ralph-archives/2026-05-16-bedrock-knowledge-layer-iac/`, moved to `plans/completed/`. **Status stays in-progress**: the only remaining work is the operator-gated `cdk bootstrap`/`deploy` + KB-stack pre-deploy cfn-guard (see `infra/README.md`); the loop deliberately does not run billable deploys. Phase 1 → `complete` once the operator deploys and verifies. Phase 2 (config hardening) and Phase 3 (RAG evals, depends on 1) are now actionable.

---

## Success Criteria (per phase, machine-checkable)

**Rule for `/goal` / prp-ralph:** a phase flips to `complete` only when **every**
`CHECK:` command below exits 0. `CHECK:` items are autonomous and gating.
`HUMAN-GATE:` items are operator-only (billable/irreversible deploys) — never
run, auto-passed, or marked complete by an autonomous driver; they are recorded
in the Progress Log when the operator does them. A phase with outstanding
`HUMAN-GATE:` items stays `in-progress`. Baseline for every phase: prior phases'
checks still green (no regression), and nothing under `docs/` is staged
(it is gitignored). A phase reaches `complete` only via the `phase-gate`
orchestrator's `complete` chokepoint after the independent review panel
passes; prp-ralph finishing its plan is necessary but **not** sufficient,
and prp-ralph never edits the `Status` column.

Thresholds below are **interview-grade strict** (Phase 3) and **test-enforced**
(Phase 5) per the owner's decision 2026-05-16.

### Phase 1 — Bedrock knowledge-layer IaC
- CHECK: `cd infra && npx aws-cdk@latest synth --all -q` exits 0.
- CHECK: `pytest infra/tests -q` all pass; asserts include OpenSearch count == 0, RDS `ServerlessV2ScalingConfiguration.MinCapacity == 0`, every IAM policy resource ≠ `"*"`, all S3 buckets block public + KMS/TLS, KB Type==RDS, 2 SSM params with the exact crew-contract names.
- CHECK: `cfn-lint` on both templates → 0 `E` findings.
- CHECK: `ComplianceAgentStack` cfn-guard COMPLIANT (0 violations).
- CHECK: `PYTHONPATH=src python -c "import compliance_assistant.crew"` exits 0.
- HUMAN-GATE: operator `cdk bootstrap`+`deploy` to `083340857999/us-east-1`; KB-stack cfn-guard resolved/justified pre-deploy; post-deploy upload a sample PDF → ingestion job `COMPLETE` → `crewai run` → `output/2-report.md` ends with a non-empty `## Sources` block. Phase → `complete` only after this.

### Phase 2 — Config & secrets hardening
- GATE: panel PASS required — mutation kill-rate ≥ `review-gate.config.json` `mutation_floor`; coverage ≥ `coverage_floor`; codex adversarial no BLOCKER/MAJOR; security-auditor + code-reviewer no BLOCKER/MAJOR; all CHECK: items below green (regression leg). The plan is adversarially reviewed (codex + code-reviewer-verify) and revised before any build; test-engineer reviews case coverage as an advisory, non-blocking leg.
- CHECK: `pytest tests/test_startup.py -q` passes — startup raises a clear error on missing **or** `replace-with-` placeholder for every required var (TOPIC, MODEL, and the agent-id resolution path), not just TOPIC.
- CHECK: a test asserts crew verbosity follows an env flag and defaults **off**.
- CHECK: `.env.example` parity test — every `os.environ` key read under `src/` appears in `.env.example`.
- CHECK: `uv sync --frozen` exits 0 and `uv.lock` is git-tracked.
- CHECK: full prior suite (`pytest infra/tests tests`) still green.

### Phase 3 — RAG evaluation harness (interview-grade strict)
- GATE: panel PASS required — same panel as Phase 2, PLUS the gold-set provenance rule: `tests/evals/gold/PROVENANCE.md` declares an `owner` or `codex` author and the gold set is unmodified by the judged diff (ralph may not author its own ground truth).
- CHECK: gold set committed at `tests/evals/gold/` — ≥ 30 positive items across the in-scope regulations (each: question + ≥1 expected source-passage locator) **and** ≥ 8 out-of-corpus negative questions.
- CHECK: `pytest tests/evals -m gate` exits 0 **deterministically offline** (recorded retrieval/generation fixtures, no live Bedrock spend); same suite runnable `-m live` (opt-in).
- CHECK (retrieval, mean over gold set): context-recall ≥ 0.90, context-precision ≥ 0.80, MRR ≥ 0.80.
- CHECK (generation, LLM-as-judge; judge prompt+rubric committed): faithfulness/groundedness ≥ 0.95, citation-correctness ≥ 0.95, hallucination-rate ≤ 0.05.
- CHECK (task-level): not-found-honesty == 1.0 (every out-of-corpus question answered with an explicit "not in knowledge base"; **zero** fabricated requirements); requirement-coverage ≥ 0.90 on the labeled subset.
- CHECK (chunking decision = the Phase 1↔3 handoff): harness scores ≥ 2 chunking configs (FIXED_SIZE baseline + ≥1 of HIERARCHICAL/SEMANTIC), writes `tests/evals/report.md`; selection rule = max context-recall@k subject to faithfulness ≥ 0.95; the winning chunking values are written into `infra/cdk.json` context and a test asserts `cdk.json` == the report's winner.
- CHECK: `docs/evals.md` documents metrics, thresholds, judge model, run instructions (untracked is fine; file must exist).

### Phase 4 — AgentCore Runtime IaC
- GATE: panel PASS required — same panel as Phase 2 (mutation+coverage / codex / security / code / CHECK-regression), evaluated on this phase's frozen diff before `complete`.
- CHECK: `cd infra && npx aws-cdk@latest synth --all -q` exits 0 with the runtime stack; `pytest infra/tests` asserts the AgentCore Runtime resource is present **or** (if AgentCore IaC is verified immature against current AWS docs) the documented ECS Fargate fallback: run-to-completion task, arm64, no NAT, S3-versioned report output.
- CHECK: AgentCore-vs-Fargate decision + the current-docs verification recorded in `infra/README.md` with a Reasoning-Gate justification.
- CHECK: cfn-lint 0 errors; cfn-guard compliant or justified; no IAM `Resource:"*"`.
- CHECK: runtime runbook names the Phase 3 eval gate as a required pre-deploy step.
- HUMAN-GATE: operator deploy of the runtime stack (billable) — excluded from `/goal`.

### Phase 5 — Observability + SLOs (test-enforced)
- GATE: panel PASS required — same panel as Phase 2 (mutation+coverage / codex / security / code / CHECK-regression), evaluated on this phase's frozen diff before `complete`.
- CHECK: `docs/SLOs.md` exists with **numeric** targets: per-stage + end-to-end latency p50/p95, quality (reuses Phase 3 faithfulness/citation bars), run-success-rate availability, and an explicit 30-day error budget per SLO.
- CHECK: `pytest tests/test_tracing.py -q` passes — a captured run (recorded fixture; opt-in live) emits exactly 3 stage spans (researcher / writer / designer), **each with non-empty input, output, and tool-call list** (this is the owner's "monitor input and output at each agent level", made binary).
- CHECK: `pytest infra/tests` asserts Bedrock model-invocation logging resource present, a CloudWatch dashboard present, and **alarm count == count of SLOs in `SLOs.md`** with **each alarm threshold == the matching `SLOs.md` number** (test parses both and cross-checks).
- CHECK: redaction test — feeding a known fake PAN/email through the logging path asserts it is masked/absent in emitted logs/traces.
- CHECK: cfn-lint 0 errors; cfn-guard compliant or justified; prior suites green.

### Phase 6 — Evidence-backed prod-readiness analysis
- GATE: panel PASS required — same panel as Phase 2 (mutation+coverage / codex / security / code / CHECK-regression), evaluated on this phase's frozen diff before `complete`.
- CHECK: `docs/analysis/2026-05-16-compliance-prod-readiness.md` exists; a grep script asserts: all 7 WA pillars present, each with ≥1 six-field Reasoning-Gate finding **or** an explicit "checked, not a gap because X"; every gap has all six fields; no `TBD`/placeholder; every `R-*`/`GAP-*` id cross-references resolve (same integrity checks as the spine plan).
- CHECK: `analyze_cdk_project` + cfn-guard receipts saved under `docs/analysis/_evidence/`.
- HUMAN-GATE: none (analysis only; produced against the synthesized templates, no deploy required).

## Out of scope (spec §6)

Multi-region/DR; load testing with real numbers; alternative agent frameworks; deeper AgentCore primitives (Gateway/Identity/Memory/Browser/Code Interpreter).
