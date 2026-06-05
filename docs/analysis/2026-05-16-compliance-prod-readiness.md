# Compliance Assistant — Evidence-backed Production-Readiness Audit

**Initiative:** [`.claude/PRPs/compliance-prod-hardening.prd.md`](../../.claude/PRPs/compliance-prod-hardening.prd.md) (tracked PRD; supersedes the original working-notes spec under `docs/superpowers/`).
**Methodology:** AWS Well-Architected GenAI Lens + Reasoning Gate (same six-field
gate and ranking weights as the spine backlog).
**Author:** ike1112
**Date:** 2026-05-16
**Status:** Phase 6 deliverable; owner-accepted 2026-05-19 (see PRD Progress Log).

This is the post-build full audit the spine backlog deferred. The five hardening
sub-projects are built and synth-green; this scores all seven Well-Architected
pillars against the **synthesized** stack (`cdk synth --all`, exit 0, five
templates — see `_evidence/synth-manifest.txt`), closing the COST and SUS
pillars the spine could not score without a CDK, with `analyze_cdk_project` and
cfn-guard receipts under `_evidence/`.

## 1. Purpose & method

Each gap is defended through the six-field Reasoning Gate (Risk / Evidence /
Why this matters here / Source / Counter-argument / Fix) and ranked
mechanically (`rank = (severity × visibility) / effort`; severity P0=3/P1=2/
P2=1, visibility high=3/mixed=2/low=1, effort S=1/M=2/L=4). A pillar with no
open gap records an explicit "checked, not a gap because" line that itself
carries a Source/Evidence reference. Evidence is a `file:line` in this repo or
a receipt under `_evidence/`. The audit is produced against synthesized
templates only — no deploy (Phase 6 `HUMAN-GATE: none`).

## 2. As-built system map

The to-be architecture from the spine is now synthesized infrastructure:
`cdk synth --all` emits ComplianceKbStack, ComplianceAgentStack,
ComplianceRuntimeEcrStack, ComplianceRuntimeStack, ComplianceObservabilityStack.
`analyze_cdk_project` reports the service inventory bedrock, iam, ssm, ec2,
kms, lambda, rds, s3, s3_notifications, cloudwatch, logs, bedrockagentcore —
and **no opensearch** (`_evidence/analyze-cdk-project.json`).

## 3. ID schemes & rubrics

### 3.1 Resource catalog

| ID | Resource | Source / sub-project |
|----|----------|----------------------|
| R-S3-CORPUS | S3 regulatory-PDF corpus (versioned, SSE-KMS, access logging) | Bedrock knowledge-layer IaC |
| R-KB | Bedrock Knowledge Base | Bedrock knowledge-layer IaC |
| R-KB-DS | KB S3 data source + ingestion trigger | Bedrock knowledge-layer IaC |
| R-AURORA-VEC | Aurora Serverless v2 pgvector store | Bedrock knowledge-layer IaC |
| R-KMS | KMS key (corpus + report encryption) | Bedrock knowledge-layer IaC |
| R-BR-AGENT | Bedrock Agent | Bedrock knowledge-layer IaC |
| R-BR-ALIAS | Bedrock Agent alias | Bedrock knowledge-layer IaC |
| R-GUARDRAIL | Bedrock Guardrail + version | Bedrock knowledge-layer IaC |
| R-AC-RUNTIME | AgentCore Runtime hosting the crew | AgentCore Runtime IaC |
| R-AC-OBS | AgentCore Observability | Observability + SLOs |
| R-S3-REPORT | S3 versioned report-output bucket | AgentCore Runtime IaC |
| R-MIL | Bedrock model-invocation logging sink | Observability + SLOs |
| R-CW-DASH | CloudWatch dashboard | Observability + SLOs |
| R-CW-ALARMS | CloudWatch composite alarms (anchored to SLOs.md) | Observability + SLOs |
| R-EVAL-GOLD | RAG eval labeled gold dataset | RAG eval harness |
| R-EVAL-RUNNER | RAG eval runner + CI gate | RAG eval harness |
| R-CFG | Runtime config validation module | Config & secrets hardening |

### 3.2 Gap id scheme

`GAP-<PILLAR>-NN`, pillar codes `OPS|SEC|REL|PERF|COST|SUS|GENAI`, numbered
per-pillar monotonically. A gap whose fix is built records the resolving
sub-project and the synthesized evidence in its `Fix:` line.

### 3.3 Severity rubric

P0 — security/data-loss/correctness or "not production-ready as-is".
P1 — meaningfully degrades reliability/cost/operability.
P2 — polish.

### 3.4 Ranking

`rank = (severity × visibility) / effort`, weights per §1. Mechanical, no
narrative.

## OPS — Operational Excellence

GAP-OPS-01 [P0] KB/Agent/Guardrail were click-ops, not reproducible [P0|high|M]
  Risk: resources could not be recreated, reviewed, or version-controlled; an
        accidental console delete was unrecoverable.
  Evidence: infra/stacks/kb_stack.py:1 and infra/stacks/agent_stack.py:1 — the
        KB (R-KB), Aurora vector store (R-AURORA-VEC), Agent (R-BR-AGENT) and
        Guardrail (R-GUARDRAIL) are now CDK resources; `_evidence/synth-manifest.txt`
        shows both templates synthesize.
  Why this matters here (NOT generic): a compliance system must reproduce the
        exact agent + KB + guardrail that produced an audited report.
  Source: AWS WA GenAI Lens — Operational Excellence (IaC); _evidence/cfn-guard-agent.txt.
  Counter-argument: skip only if the resources were throwaway and never
        recreated — false for an auditable compliance system.
  Fix: resolved by the Bedrock knowledge-layer IaC sub-project.

GAP-OPS-02 [P0] No observability — stdout verbose only [P0|high|M]
  Risk: no per-agent traces or model-invocation logging; failures opaque.
  Evidence: infra/stacks/observability_stack.py:1 (R-AC-OBS, R-MIL, R-CW-DASH,
        R-CW-ALARMS) and src/compliance_assistant/tracing.py:1 (three redacted
        stage spans); ComplianceObservabilityStack synthesizes.
  Why this matters here (NOT generic): compliance runs are audit records and
        must be traceable per agent and per model call.
  Source: AWS WA GenAI Lens — Operational Excellence (observability).
  Counter-argument: skip only if runs are disposable — false; runs are evidence.
  Fix: resolved by the Observability + SLOs sub-project.

## SEC — Security

GAP-SEC-01 [P0] Web-crawl corpus had non-reproducible provenance [P0|high|M]
  Risk: the grounding corpus could change or vanish; you could not prove which
        regulatory text produced a requirement.
  Evidence: infra/stacks/kb_stack.py:1 — S3 corpus (R-S3-CORPUS) is versioned,
        SSE-KMS (R-KMS), TLS-only, access-logged; cfn-guard receipt
        _evidence/cfn-guard-agent.txt records ComplianceAgentStack COMPLIANT.
  Why this matters here (NOT generic): provenance is the core compliance
        property; an unauditable corpus invalidates the output's authority.
  Source: AWS WA GenAI Lens — Security (data protection); _evidence/cfn-guard-agent.txt.
  Counter-argument: skip only if the corpus is ephemeral non-regulatory — false.
  Fix: resolved by the Bedrock knowledge-layer IaC sub-project.

GAP-SEC-02 [P0] .env not gitignored; placeholder config could start the app [P0|high|S]
  Risk: real Bedrock/AWS config could be committed; a placeholder AGENT_ID
        could start a run that fails late.
  Evidence: .gitignore:12-14 (.env ignored, .env.example kept);
        src/compliance_assistant/startup.py:1 fails fast on missing/placeholder
        TOPIC/MODEL/agent-id (R-CFG); cfn-guard receipt _evidence/cfn-guard-agent.txt.
  Why this matters here (NOT generic): leaked Bedrock credentials in a public
        sample are an immediate incident; a half-run wastes a long batch.
  Source: OWASP (secrets management); AWS WA GenAI Lens — Security.
  Counter-argument: none defensible for a credentialed sample.
  Fix: resolved by the Config & secrets hardening sub-project.

## REL — Reliability

GAP-REL-01 [P0] No deployable runtime — local CLI only [P0|high|L]
  Risk: no execution ceiling, retry, idempotency, or isolation; not operable.
  Evidence: infra/stacks/runtime_stack.py:1 — AgentCore Runtime (R-AC-RUNTIME)
        hosting the crew with a versioned S3 report bucket (R-S3-REPORT);
        ComplianceRuntimeStack synthesizes; cfn-guard posture in
        _evidence/cfn-guard-deferred.txt (operator pre-deploy, accepted).
  Why this matters here (NOT generic): "production-ready" requires a managed
        runtime, not a developer laptop, for an auditable compliance service.
  Source: AWS WA GenAI Lens — Reliability.
  Counter-argument: skip only if run solely by a human locally — contradicts
        the stated production-ready goal.
  Fix: resolved by the AgentCore Runtime IaC sub-project (ECS Fargate fallback
        documented in infra/README.md).

## PERF — Performance Efficiency

GAP-PERF-01 [P1] No runtime sizing or scale model [P1|mixed|M]
  Risk: no defined concurrency, CPU/mem, or scale-to-zero behaviour.
  Evidence: infra/stacks/runtime_stack.py:1 — AgentCore Runtime (R-AC-RUNTIME),
        arm64, scale-to-zero; `_evidence/analyze-cdk-project.json` shows
        bedrockagentcore (managed runtime, no always-on compute).
  Why this matters here (NOT generic): scalability and cost-performance are
        explicit goals for a batch compliance generator.
  Source: AWS WA GenAI Lens — Performance Efficiency.
  Counter-argument: skip only if strictly single-user occasional — contradicts
        the scalability goal.
  Fix: resolved by the AgentCore Runtime IaC sub-project.

## COST — Cost Optimization

GAP-COST-01 [P1] Vector store could have carried a standing OpenSearch cost floor [P1|mixed|M]
  Risk: a provisioned OpenSearch vector domain bills continuously regardless of
        query volume — a large idle cost for a bursty compliance workload.
  Evidence: _evidence/analyze-cdk-project.json — the service inventory contains
        **no opensearch** entry; the vector store is Aurora Serverless v2
        pgvector (R-AURORA-VEC, rds) with MinCapacity 0 (scale-to-zero) per
        infra/stacks/kb_stack.py and the infra/tests assertions.
  Why this matters here (NOT generic): the spine deferred COST for lack of a
        CDK; the synthesized inventory now proves no idle vector-store spend —
        this is the receipt-backed closure of that deferral.
  Source: AWS WA GenAI Lens — Cost Optimization; _evidence/analyze-cdk-project.json.
  Counter-argument: revisit only if sustained high QPS makes Aurora autoscale
        cost exceed a provisioned domain — out of scope for this sample's load.
  Fix: resolved by the Bedrock knowledge-layer IaC sub-project (Aurora
        Serverless v2, MinCapacity 0; no OpenSearch).

GAP-COST-02 [P1] Always-on compute would bill while idle [P1|mixed|M]
  Risk: a warm Fargate/EC2 host for an infrequently-run batch generator bills
        24/7 for occasional use.
  Evidence: _evidence/analyze-cdk-project.json — compute is lambda +
        bedrockagentcore (managed scale-to-zero) + Aurora Serverless v2; no
        provisioned always-on compute service in the inventory.
  Why this matters here (NOT generic): a compliance report is generated on
        demand, not continuously; idle compute is pure waste here.
  Source: AWS WA GenAI Lens — Cost Optimization; _evidence/analyze-cdk-project.json.
  Counter-argument: revisit only if cold-start latency violates an SLO —
        docs/SLOs.md latency targets accommodate it.
  Fix: resolved by the AgentCore Runtime IaC sub-project (scale-to-zero runtime).

## SUS — Sustainability

GAP-SUS-01 [P1] Idle provisioned capacity wastes energy [P1|mixed|M]
  Risk: always-on vector domains and warm compute consume energy proportional
        to provisioned, not used, capacity.
  Evidence: _evidence/analyze-cdk-project.json — no opensearch; Aurora
        Serverless v2 MinCapacity 0 (R-AURORA-VEC) and bedrockagentcore
        scale-to-zero mean capacity tracks demand; arm64 runtime
        (infra/stacks/runtime_stack.py:1) is more energy-efficient per unit work.
  Why this matters here (NOT generic): the spine deferred SUS for lack of a
        CDK; the synthesized scale-to-zero + arm64 posture is the receipt-backed
        closure — capacity (and energy) tracks actual compliance-run demand.
  Source: AWS WA GenAI Lens — Sustainability; _evidence/analyze-cdk-project.json.
  Counter-argument: revisit only if scale-to-zero cold starts force an
        always-warm pool — not required at this workload.
  Fix: resolved by the Bedrock knowledge-layer IaC + AgentCore Runtime IaC
        sub-projects (scale-to-zero Aurora + arm64 managed runtime).

## GENAI — Generative AI

GAP-GENAI-01 [P0] Citations off — report had zero source attribution [P0|high|S]
  Risk: users treated uncited compliance guidance as authoritative.
  Evidence: src/compliance_assistant/citations.py:1 renders a deterministic
        Sources block from the agent trace; tests/evals/ gold set + judge gate
        (R-EVAL-GOLD, R-EVAL-RUNNER) assert citation-correctness ≥ 0.95.
  Why this matters here (NOT generic): a compliance report without citations is
        unusable for audit and actively dangerous.
  Source: AWS WA GenAI Lens — responsible AI (traceability).
  Counter-argument: skip only if output is a labelled non-authoritative draft —
        false; the README positions it as actionable.
  Fix: resolved by the Bedrock knowledge-layer IaC + RAG eval harness sub-projects.

GAP-GENAI-02 [P0] Retrieval quality was unmeasured [P0|high|L]
  Risk: chunking chosen blind; retrieval regressions ship silently; the crew
        could fabricate requirements instead of saying "not in KB".
  Evidence: tests/evals/conftest.py:1 — deterministic offline gate (R-EVAL-RUNNER) over a
        ≥30-item gold set (R-EVAL-GOLD) enforcing context-recall ≥ 0.90,
        faithfulness ≥ 0.95, not-found-honesty == 1.0; winning chunking written
        to infra/cdk.json and asserted.
  Why this matters here (NOT generic): retrieval is the named single most
        important property; a fabricated requirement outranks a missed one.
  Source: AWS WA GenAI Lens — responsible AI (evals).
  Counter-argument: skip only if retrieval were a trivial exact lookup — false
        for regulatory retrieval over long PDFs.
  Fix: resolved by the RAG eval harness sub-project.

## Ranked backlog

| Rank | GAP | Pillar | Sev | Vis | Effort | Score | Status |
|------|-----|--------|-----|-----|--------|-------|--------|
| 1 | GAP-GENAI-01 | GENAI | P0 | high | S | 9.00 | resolved (Bedrock IaC + RAG evals) |
| 2 | GAP-SEC-02 | SEC | P0 | high | S | 9.00 | resolved (Config hardening) |
| 3 | GAP-OPS-01 | OPS | P0 | high | M | 4.50 | resolved (Bedrock IaC) |
| 4 | GAP-OPS-02 | OPS | P0 | high | M | 4.50 | resolved (Observability + SLOs) |
| 5 | GAP-SEC-01 | SEC | P0 | high | M | 4.50 | resolved (Bedrock IaC) |
| 6 | GAP-GENAI-02 | GENAI | P0 | high | L | 2.25 | resolved (RAG eval harness) |
| 7 | GAP-REL-01 | REL | P0 | high | L | 2.25 | resolved (AgentCore Runtime IaC) |
| 8 | GAP-PERF-01 | PERF | P1 | mixed | M | 2.00 | resolved (AgentCore Runtime IaC) |
| 9 | GAP-COST-01 | COST | P1 | mixed | M | 2.00 | scored now (no OpenSearch; Aurora MinCapacity 0) |
| 10 | GAP-COST-02 | COST | P1 | mixed | M | 2.00 | scored now (scale-to-zero compute) |
| 11 | GAP-SUS-01 | SUS | P1 | mixed | M | 2.00 | scored now (scale-to-zero + arm64) |

## Out of scope & method caveats

### Method caveats
- COST and SUS are now scored against `_evidence/analyze-cdk-project.json`; the
  spine's deferral of these two pillars is closed with the receipt, not by
  assertion.
- The cfn-guard CLI / content-only compliance MCP is not available in this
  autonomous analysis environment. Per the project's accepted posture
  (infra/README.md:160-217), the in-loop substitute is cfn-lint (0 errors) plus
  the targeted infra/tests synth assertions; the full cfn-guard stream for the
  KB/Runtime/Observability stacks is the documented operator pre-deploy step
  (`_evidence/cfn-guard-deferred.txt`). ComplianceAgentStack's COMPLIANT result
  is the accepted reviewed prior result re-confirmed against the current synth
  (`_evidence/cfn-guard-agent.txt`). This is a stated limitation, not a hidden
  gap.

### Non-goals (spec §6)
Multi-region/DR; load testing with real numbers; alternative agent frameworks;
deeper AgentCore primitives (Gateway/Identity/Memory/Browser/Code Interpreter).
