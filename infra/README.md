# Compliance Assistant — Bedrock Knowledge-Layer Infrastructure

CDK v2 (Python) for the grounding layer: an S3 regulatory-PDF corpus,
an Aurora Serverless v2 pgvector store (0-ACU idle), a Bedrock
Knowledge Base + S3 data source, and a Guardrail-attached Bedrock
Agent whose ids are published to SSM. Implements spec §3.1 and the
citations part of §3.4.

## Layout

- `app.py` — two stacks, split by blast radius.
- `stacks/kb_stack.py` — `ComplianceKbStack`: KMS, corpus + access-log
  buckets, VPC, Aurora Serverless v2 (pgvector, bootstrapped over the
  RDS Data API), Knowledge Base, S3 data source, ingestion Lambda.
- `stacks/agent_stack.py` — `ComplianceAgentStack`: Guardrail (+pinned
  version), Agent (KB-associated), alias, SSM parameters.
- `lambdas/ingest/` — re-index handler (S3 ObjectCreated → StartIngestionJob).
- `tests/` — synth-time security/cost assertions.

## Which Aurora path is used

The native `rds.DatabaseCluster` path, **not** the
`generative-ai-cdk-constructs` Aurora helper. That helper requires a
running Docker daemon at synth (it `docker build`s a pgvector-bootstrap
Lambda) and exposes no Serverless-v2 capacity props, so it cannot meet
the spec-locked 0-ACU requirement. pgvector is bootstrapped instead by
an inline-code trigger over the RDS Data API — no Docker, no driver,
no in-VPC Lambda.

## Toolchain

CDK CLI must be **≥ 2.1122.0** (`aws-cdk@latest`); the older
`aws-cdk@2` tag emits a cloud-assembly schema the lib can't read.
Always activate the local venv first so `python app.py` resolves:

```
cd infra
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
source .venv/Scripts/activate
npx --yes aws-cdk@latest synth --all -q
```

## Autonomous validation gate results (synth-time, free)

| Gate | Result |
|------|--------|
| `cdk synth --all` | exit 0, both templates emitted |
| pytest (`tests/`, `infra/tests/`) | 16+ assertions pass |
| cfn-lint (both templates) | 0 errors (warnings accepted below) |
| cfn-guard `ComplianceAgentStack` | COMPLIANT, 0 violations (aws-security) |
| cost (`analyze_cdk_project`) | no OpenSearch line item; Aurora `MinCapacity:0` |

### Lint exceptions (cfn-lint warnings, accepted)

- **W3045 `AccessControl` legacy on the access-log bucket** — CDK sets
  `AccessControl: LogDeliveryWrite` automatically on S3 server-access-log
  target buckets; required for log delivery, not author-controlled.
- **W3005 redundant `DependsOn` (×6)** — CDK emits explicit
  `DependsOn` alongside the `GetAtt`/`Ref` it already implies (and we
  add explicit KB→cluster/bootstrap ordering on purpose). Benign.

### Accepted cfn-guard exceptions

- **`ComplianceKbStack` full cfn-guard runs at operator pre-deploy**
  (see Deploy runbook). *Reasoning-Gate justification:* the autonomous
  loop environment cannot stream the 38 KB KB template into the
  content-only compliance MCP reliably. In-loop the KB stack is covered
  by cfn-lint (0 errors) plus targeted synth assertions: all buckets
  block public access, corpus is KMS-encrypted + versioned + TLS-only +
  access-logged, KMS rotation on, Aurora storage encrypted, every IAM
  policy resource-scoped (no `Resource:"*"`), no OpenSearch. The
  `ComplianceAgentStack` (IAM/Guardrail/Agent) passed cfn-guard fully.
- **RDS automated-backup retention / Multi-AZ not set** — single-AZ,
  default backups: multi-region/DR is explicitly out of scope
  (spec §6). Revisit if this leaves sample status.
- **KMS key policy `Resource:"*"`** — the standard CDK-generated
  account-root key policy (resource policy, not an identity wildcard).

### Cost snapshot

Services: Bedrock, RDS (Aurora Serverless v2), KMS, S3, Lambda, EC2
(VPC, no NAT), SSM, IAM. **No OpenSearch Serverless** — the spec §3.1
cost rationale holds. Aurora `ServerlessV2ScalingConfiguration.MinCapacity`
is `0`, so the cluster pauses to ~zero compute cost between report
runs; standing cost is storage + the (negligible) idle of a no-NAT
VPC. A precise $/month figure requires the deeper pricing flow and is
produced at operator pre-deploy.

## Deploy runbook (OPERATOR-GATED — never run by the autonomous loop)

`cdk deploy` provisions billable, slow-to-delete Bedrock + Aurora
resources and is **operator-approved only**.

Prereqs: AWS credentials for account `083340857999`, region
`us-east-1`; Bedrock model access enabled for
`amazon.titan-embed-text-v2:0` and `amazon.nova-pro-v1:0`.

```
# one-time
npx --yes aws-cdk@latest bootstrap aws://083340857999/us-east-1 --qualifier complianceha

# pre-deploy compliance (operator): run cfn-guard on BOTH templates
npx --yes aws-cdk@latest synth --all -q
#   then check ComplianceKbStack.template.json + ComplianceAgentStack.template.json
#   with the aws-iac compliance check; resolve or justify findings here.

# deploy
cd infra && npx --yes aws-cdk@latest deploy --all --require-approval any-change
```

Post-deploy: upload a sample regulatory PDF to the corpus bucket,
confirm an ingestion job runs, then `crewai run` and confirm
`output/2-report.md` ends with a populated `## Sources` block.

Destroy: `npx --yes aws-cdk@latest destroy --all`. The corpus and
access-log buckets are `RETAIN` by design (evidence preservation) —
empty/delete them by hand only if you truly intend to.

**Cost note:** deploying incurs real, ongoing charges (Aurora storage
+ active ACUs, KB ingestion, Titan embeddings, Nova-Pro inference).
0-ACU idle keeps the floor low but it is not zero.
