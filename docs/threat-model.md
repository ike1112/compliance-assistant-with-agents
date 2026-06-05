# Threat model — Compliance Assistant

Trust boundaries between components, the controls on each, the threat
scenarios considered, and the residual risks accepted. For the component
narrative see [`../ARCHITECTURE.md`](../ARCHITECTURE.md); for the visual map see
[`diagrams/compliance-assistant-v12.png`](diagrams/compliance-assistant-v12.png);
for the decisions behind specific controls see [`adr/`](adr/).

## Scope and assumptions

- This is a **single-user** compliance-research sample. It turns a regulation
  topic into a cited report; it stores no end-user PII and takes no actions
  (read-and-report only).
- Controls below are verified at **synth time and by tests**, not against live
  AWS — the billable `cdk deploy` is operator-gated. "Mitigated" means the
  control is present in the synthesized template / code and asserted by a test,
  not that it has been pen-tested in production.

## Trust boundaries

| # | Boundary (crosses) | Controls |
|---|--------------------|----------|
| B1 | Operator → AgentCore Runtime (topic in, report out) | TLS; AWS IAM/SigV4 per the AgentCore invoke contract |
| B2 | Runtime/crew → Bedrock Agent (`InvokeAgent`, trace on) | IAM scoped to the agent; Guardrail attached to the agent (input `PROMPT_ATTACK` filter) |
| B3 | Agent → Knowledge Base → Aurora pgvector (retrieval) | Aurora in `PRIVATE_ISOLATED` subnets with `nat_gateways=0` — no internet egress; IAM-scoped access |
| B4 | KB → S3 PDF corpus (ingest reads) | SSE-KMS; `BlockPublicAccess.BLOCK_ALL`; `enforce_ssl=True`; versioned |
| B5 | Runtime → S3 report bucket (writes reports) | SSE-KMS (ReportKey); `BlockPublicAccess.BLOCK_ALL`; `enforce_ssl=True`; versioned |
| B6 | Corpus upload → IngestFn Lambda → `StartIngestionJob` | event-scoped IAM; control-plane call only |
| B7 | Crew / Bedrock → CloudWatch logs | model-invocation logging with **raw data delivery disabled**; spans redacted (Luhn-validated PAN + email); delivery role assume-role conditioned on `aws:SourceAccount` (confused-deputy guard) |

## Threat scenarios

**T1 — Prompt injection via retrieved KB content.** A regulatory PDF in the
corpus contains text crafted to be read as instructions ("ignore your task
and…").
*Mitigation:* the researcher task instructs the agent to treat tool output as
reference data, not instructions (`src/compliance_assistant/config/tasks.yaml:10-11`),
and the Guardrail's `PROMPT_ATTACK` filter screens input. Defense-in-depth, not
a proof — see R2.

**T2 — Sensitive data leaks to logs.** A PAN or email in a prompt/response
reaches CloudWatch.
*Mitigation:* Bedrock model-invocation logging has raw text/image/embedding/
video delivery **disabled** (`infra/stacks/observability_stack.py`), so only
invocation metadata is logged; the in-process span path is redacted
(`src/compliance_assistant/tracing.py` `redact`: Luhn-validated PAN + email). A
redaction test feeds a known fake PAN/email through and asserts it is absent.

**T3 — Ungrounded / fabricated compliance guidance.** Retrieval finds nothing,
but the writer produces a confident report from prior knowledge.
*Mitigation:* the report and solution stages skip when research finds no
grounded source ([ADR 0005](adr/0005-conditional-report-stages.md)); the eval
gate measures faithfulness, citation-correctness, and not-found-honesty against
a frozen gold set ([ADR 0004](adr/0004-codex-authored-frozen-gold-set.md)).

**T4 — Exfiltration from the vector store.** A compromised component tries to
ship corpus/embeddings out.
*Mitigation:* Aurora runs in isolated subnets with no NAT — there is no route
to the internet (`infra/stacks/kb_stack.py:157-188`); data is KMS-encrypted at
rest.

**T5 — Public exposure of corpus or reports.** A bucket misconfiguration
exposes regulatory PDFs or generated reports.
*Mitigation:* both buckets set `BlockPublicAccess.BLOCK_ALL`, `enforce_ssl`,
SSE-KMS, and versioning; infra tests assert public access is blocked and KMS is
used.

**T6 — Over-broad IAM (blast radius / escalation).**
*Mitigation:* infra tests assert no policy uses a literal `Resource:"*"` except
the justified account-level Bedrock-logging op (no resource-ARN form), which is
documented; roles are scoped per component.

**T7 — Confused deputy on the logging delivery role.** Another account induces
Bedrock to write to this account's log group.
*Mitigation:* the delivery role's assume-role is conditioned on
`aws:SourceAccount` (`infra/stacks/observability_stack.py`).

**T8 — Tampering with the eval answer key.** A change relaxes the gold set to
make the system "pass."
*Mitigation:* the gold set is frozen — a test fails if the judged diff modifies
anything under `tests/evals/gold/` ([ADR 0004](adr/0004-codex-authored-frozen-gold-set.md)).

**T9 — Supply-chain / IaC drift.**
*Mitigation:* `uv.lock` is tracked and `uv sync --frozen` is enforced;
`cdk synth`, cfn-lint, and cfn-guard run in the quality gate.

## Residual risks (accepted)

- **R1 — No application-level authorization.** The runtime endpoint relies on
  AWS IAM; there is no per-end-user authz or multi-tenant isolation. This is a
  single-user sample; a multi-user deployment would need an identity layer
  (the sibling trip-tracker project uses Cognito for exactly this).
- **R2 — Redaction is best-effort.** `redact` masks Luhn-validated PANs and
  emails; other regulated identifiers (e.g. national IDs) are not pattern-matched.
- **R3 — Guardrail efficacy is a managed control.** Its filter quality is
  AWS-provided and not independently evaluated here.
- **R4 — Controls are synth/test-verified, not live.** Nothing in this repo
  runs against real AWS; the deploy is an explicit operator decision.

## Out of scope

Booking or other state-changing actions (read-and-report only); storage of
end-user PII; network-layer DoS protection.
