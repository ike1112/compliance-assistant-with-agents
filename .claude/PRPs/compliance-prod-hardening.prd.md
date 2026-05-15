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
| 2 | Config & secrets hardening — fail-fast startup validation rejecting placeholders, verbose gated by env, lockfile-deploy verification, `.env.example` sync | — | pending | _(not yet planned)_ | GAP-SEC-04, GAP-OPS-04, GAP-OPS-05 |
| 3 | RAG evaluation harness — retrieval / generation / task-level gold sets + LLM-as-judge + CI gate; decides the real chunking value | 1 | pending | _(not yet planned)_ | GAP-GENAI-02, GAP-GENAI-03 |
| 4 | AgentCore Runtime IaC — host the crew (8h, scale-to-zero); AgentCore IaC maturity verified vs current docs; Fargate fallback documented | 1 (release-gated by 3) | pending | _(not yet planned)_ | GAP-REL-01, GAP-PERF-01 |
| 5 | Observability + SLOs — AgentCore Observability wiring, model-invocation logging, `docs/SLOs.md`, composite alarms, verbose redaction | 1, 4 | pending | _(not yet planned)_ | GAP-OPS-02, GAP-SEC-03, GAP-OPS-03 |
| 6 | Evidence-backed prod-readiness analysis — full WA-Lens audit against the synthesized stack (cfn-guard, analyze_cdk_project, all 7 pillars) | 1, 2, 3, 4, 5 | pending | _(not yet planned)_ | (audit deliverable; scores COST/SUS deferred from the spine) |

**Parallelism:** Phases 1 and 2 have no dependencies on each other and may run concurrently in separate worktrees.

**Next actionable:** Phase 1 (in-progress, plan ready for prp-ralph). Phase 2 may start in parallel once planned.

---

## Progress Log

Append one line per phase status change (newest last). prp-ralph / prp-plan update this and the table above.

- 2026-05-15 — PRD created. Phase 1 planned (`bedrock-knowledge-layer-iac.plan.md`) and set in-progress. Phases 2-6 pending.

---

## Per-phase completion criteria

A phase moves to `complete` only when: its prp-plan's Acceptance Criteria all pass; its autonomous validation gates (synth / cfn-lint / cfn-guard / best-practices / cost / tests, as applicable) are green or Reasoning-Gate-justified; and no `docs/` files were staged. Operator-gated deploys (e.g., Phase 1 Task 13) are recorded here when the operator approves and runs them — they are never auto-completed by the loop.

## Out of scope (spec §6)

Multi-region/DR; load testing with real numbers; alternative agent frameworks; deeper AgentCore primitives (Gateway/Identity/Memory/Browser/Code Interpreter).
