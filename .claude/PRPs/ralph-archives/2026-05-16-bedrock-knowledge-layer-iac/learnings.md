# Implementation Report — Bedrock Knowledge-Layer IaC

**Plan**: `.claude/PRPs/plans/bedrock-knowledge-layer-iac.plan.md`
**Completed**: 2026-05-16
**Iterations**: 4

## Summary

Stood up the grounding layer as reviewable CDK v2 (Python): KMS-encrypted
versioned S3 PDF corpus + access-log bucket, Aurora Serverless v2 pgvector
(0-ACU idle, Data-API pgvector bootstrap), Bedrock Knowledge Base (RDS-backed,
configurable chunking), S3-event ingestion Lambda, Guardrail-attached Bedrock
Agent + alias with ids published to SSM, and `crew.py` rewired to resolve
those ids (env fallback, placeholders rejected) with agent trace on so the
report is no longer uncited.

## Tasks Completed

1–7 infra build (skeleton, buckets/KMS, asserts, Aurora 0-ACU, KB, data
source+ingest, agent stack); 8 cfn-lint (0 errors); 9 cfn-guard (agent stack
COMPLIANT, KB stack documented operator-pre-deploy exception); 10
best-practices + cost (no OpenSearch, Aurora 0-ACU, termination protection
added); 11 SSM id resolver; 12 deterministic citations; 13 operator-gated
runbook (no deploy executed).

## Validation Results

| Check | Result |
|-------|--------|
| `cdk synth --all` | PASS (exit 0) |
| Unit/synth tests | PASS (16 infra + 8 app = 24) |
| cfn-lint | PASS (0 errors) |
| cfn-guard (agent stack) | PASS (COMPLIANT, 0 violations) |
| Cost regression (no OpenSearch / Aurora 0-ACU) | PASS |
| `import compliance_assistant.crew` | PASS (clean, lazy resolution) |

## Codebase Patterns Discovered

- CDK CLI must be `aws-cdk@latest` (≥2.1122.0); `@2` tag is schema-incompatible.
- Activate `infra/.venv` before `cdk` so `python app.py` resolves (Windows
  `--app` path override gets shell-mangled).
- gen-ai-cdk-constructs Aurora/KB path is Docker-bound at synth → raw L1
  Bedrock + native rds.DatabaseCluster + RDS-Data-API trigger is Docker-free.
- Anchor `Code.from_asset` to the module file, not cwd (cdk vs pytest cwd differ).
- S3 log-target bucket needs `ObjectOwnership.OBJECT_WRITER`.

## Deviations from Plan

- L1 `aws_bedrock.Cfn*` + self-built Aurora instead of the gen-ai-cdk-constructs
  L2 (Docker-at-synth + no 0-ACU control) — the plan's documented Task 4 fallback.
- Module named `agent_ids.py` not `config.py` (collision with existing `config/`).
- Agent-id resolution made lazy (build-time, not import-time) to keep
  `import crew` clean when unconfigured.
- KB-stack cfn-guard deferred to operator pre-deploy (content-only MCP can't
  take the 38 KB template in-loop) — justified in `infra/README.md`.
- `cdk deploy` intentionally NOT run (operator-gated, Task 13).

## Next Step

Operator: review `infra/README.md`, run the pre-deploy cfn-guard on the KB
template, then the gated `cdk bootstrap`/`deploy`. Then PRD phase 1 → complete;
phase 2 (config hardening) or phase 3 (RAG evals) next.
