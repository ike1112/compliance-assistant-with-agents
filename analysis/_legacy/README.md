# Legacy artifacts (pre-production-hardening)

These files are the original artifacts from the AWS-sample baseline this
project was hardened from. They are preserved here for provenance and as a
"before" baseline that contrasts with the production-hardening work.

For the current production-readiness audit, see
[`docs/analysis/2026-05-16-compliance-prod-readiness.md`](../../docs/analysis/2026-05-16-compliance-prod-readiness.md)
(full WA-Lens audit across all seven pillars, with `cdk synth` /
`analyze_cdk_project` / cfn-guard evidence receipts under
`docs/analysis/_evidence/`).

## Files

| File | What it is |
|------|-----------|
| `DEPLOYMENT_READINESS_REVIEW.md` | First-pass deployment-readiness review from 2026-05-14, before the WA-Lens hardening initiative began. Useful contrast: lists ad-hoc gaps that the structured WA-Lens audit later categorized and ranked. |
| `a.md` | Verification notes against the click-ops baseline (pre-IaC). Concrete Bedrock resource identifiers have been redacted as `<click-ops-agent>`, `<click-ops-kb>`, `<click-ops-guardrail>`; those resources were replaced by IaC-managed equivalents in the Bedrock knowledge-layer phase. |
| `agent-flow.excalidraw` | Architecture diagram of the click-ops agent flow (Excalidraw source). |
| `Automating regulatory compliance Agent.excalidraw` | Higher-level architecture diagram (Excalidraw source). |

## What changed after these artifacts

The production-hardening work that followed introduced:

- CDK IaC for the entire Bedrock knowledge layer (`infra/stacks/`),
  replacing the click-ops Agent/KB/Guardrail with reproducible templates.
- An offline RAG evaluation harness with a PCI DSS gold set and CI gate
  (`tests/evals/`).
- AgentCore Runtime IaC (`infra/stacks/runtime_stack.py`) for hosting the
  crew.
- Tracing, redaction, and SLO-derived alarms (`src/compliance_assistant/tracing/`,
  `infra/stacks/observability_stack.py`, [`docs/SLOs.md`](../../docs/SLOs.md)).
- A six-leg quality gate (`review_gate/`) that ran on every phase.

See [`ARCHITECTURE.md`](../../ARCHITECTURE.md) for the narrative arc.
