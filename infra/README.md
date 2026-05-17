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
- `stacks/runtime_stack.py` — `ComplianceRuntimeStack`: AgentCore
  Runtime host for the crew, versioned KMS report bucket, ECR repo,
  least-privilege execution role. Deploys after the agent stack.
- `runtime/` — the linux/arm64 container artifact: `server.py` is the
  AgentCore HTTP service-contract shim (async pattern); `Dockerfile`
  is built/pushed by the operator at the HUMAN-GATE.
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

## AgentCore Runtime hosting decision (current-docs verified, 2026-05)

**Decision:** host the crew on **AgentCore Runtime**
(`AWS::BedrockAgentCore::Runtime`), not ECS Fargate.

**Current-docs verification** (AWS docs, May 2026):

- Amazon Bedrock AgentCore is **GA since 2025-10**; **CloudFormation
  support since 2025-09**
  ([whats-new](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/)).
- The L1 construct `aws_cdk.aws_bedrockagentcore.CfnRuntime` ships in
  the repo-pinned `aws-cdk-lib>=2.254.0` (verified importable at build).
- `LifecycleConfiguration.MaxLifetime` accepts 60–28800 s; **28800 s
  (8 h) is the documented maximum**
  ([lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)).
- **Synchronous invocations are bounded (~15 min): a session is
  terminated if the invocation path blocks the `/ping` health thread.**
  Minutes-to-hours work MUST use the documented asynchronous pattern —
  background execution + a `/ping` that reports `HealthyBusy`
  ([long-running agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html)).
  `runtime/server.py` implements exactly that, so the crew genuinely
  reaches the 8 h ceiling. Serverless scale-to-zero is inherent
  (consumption billing; the microVM is terminated post-session).

**Conclusion:** AgentCore Runtime IaC is mature *and* async-suitable for
this batch crew → the primary path, not the fallback.

**Rejected alternative — ECS Fargate fallback (documented):** a
run-to-completion Fargate task (arm64, no NAT via public subnet + VPC
endpoints, S3-versioned report output) would also satisfy the run-to-
completion shape. It is unnecessary given the verified maturity: more
moving parts, no idle-zero without extra plumbing, and it would
duplicate AgentCore's session isolation. Retained here only as the
documented contingency if AgentCore IaC regresses.

The hand-rolled stdlib shim (no `bedrock-agentcore` SDK) is deliberate:
it keeps the runtime closure to the crew's own deps and makes the
service contract fully unit-testable offline (`test_runtime_server.py`),
matching this repo's dependency-light, deterministic ethos.

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
- **E3006 `AWS::BedrockAgentCore::Runtime` "does not exist in
  <region>"** — cfn-lint's bundled per-region resource catalog lags
  this **GA** resource type (GA 2025-10; first-class CloudFormation;
  the L1 ships in the pinned `aws-cdk-lib`). It is a catalog-lag false
  positive, not a template defect: cfn-lint is therefore run
  **region-scoped to the single deploy region `us-east-1`**
  (`cfn-lint --region us-east-1`, the region `app.py` and the Phase 1
  runbook deploy to), where AgentCore Runtime is available and the
  template lints **0 errors** (only the W3045 access-log warning
  above, identical to the KB/agent stacks). The unscoped run only
  flags non-deploy partitions (cn-/gov-/…); scoping is the correct
  posture for a GA resource newer than the cfn-lint release.

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
- **`ComplianceRuntimeStack` full cfn-guard runs at operator pre-deploy**
  (same in-loop streaming limitation as the KB stack). *Reasoning-Gate
  justification:* in-loop the runtime stack is covered by cfn-lint
  (0 errors) plus targeted synth assertions in
  `tests/test_runtime_stack.py` — the AgentCore Runtime resource is
  present and HTTP/PUBLIC, the report bucket blocks public access and is
  KMS-encrypted + versioned + TLS-only + access-logged, KMS rotation on,
  no VPC/NAT, the execution role can invoke the Bedrock Agent and reads
  exactly the two agent-id SSM params, and **every execution-role
  statement is resource-scoped with exactly ONE accepted exception**:
  `ecr:GetAuthorizationToken` with `Resource:"*"`. That action is an
  account-level token operation with **no resource-level form** in IAM
  (AWS `bedrock-agentcore` runtime-permissions reference); it is
  isolated in its own statement and the no-wildcard test asserts it is
  the *only* literal wildcard, so an accidental future one still fails.
  CloudWatch metrics and X-Ray (which would each force an additional
  `Resource:"*"`) are intentionally deferred to the observability phase,
  so no other identity wildcard exists in this stack. The operator's
  pre-deploy cfn-guard run checks the same controls enumerated above.

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

### Runtime stack deploy (OPERATOR-GATED — billable, after the above)

**Required pre-deploy gate:** the RAG evaluation gate
(`pytest tests/evals -m gate`) MUST pass on the deploying commit before
the runtime image is built/pushed or `ComplianceRuntimeStack` is
deployed. The runtime hosts the same crew the eval harness scores;
shipping a runtime whose grounding/citation quality has not passed the
gate is not permitted.

**Deploy ordering:** `ComplianceAgentStack` MUST be deployed before
`ComplianceRuntimeStack` — the crew resolves the Bedrock agent ids from
SSM (`/compliance-assistant/agent-id`, `-alias-id`) at container start,
and those parameters are published by the agent stack. `app.py` encodes
this with `runtime_stack.add_dependency(agent_stack)`.

```
# 0. gate: pytest tests/evals -m gate            # MUST be green
# 1. build + push the linux/arm64 crew image to the stack's ECR repo
ECR_URI=$(aws cloudformation describe-stacks --stack-name ComplianceRuntimeStack \
  --query "Stacks[0].Outputs[?OutputKey=='RuntimeRepoUri'].OutputValue" --output text)
docker buildx build --platform linux/arm64 -f infra/runtime/Dockerfile \
  -t "$ECR_URI:<tag>" --push .
# 2. set the tag and deploy the runtime stack (agent stack first)
cd infra && npx --yes aws-cdk@latest deploy ComplianceRuntimeStack \
  -c agentRuntimeImageTag=<tag> --require-approval any-change
```

Post-deploy: upload a sample regulatory PDF to the corpus bucket,
confirm an ingestion job runs, then `crewai run` and confirm
`output/2-report.md` ends with a populated `## Sources` block. For the
hosted runtime, `POST /invocations` returns a `run_id`; poll `/ping`
until `Healthy` and confirm the report artifact lands in the versioned
report bucket (a no-grounded-findings run uploads `1-requirements.md`
and reports success without `2-report.md` — that is correct behaviour).

Destroy: `npx --yes aws-cdk@latest destroy --all`. The corpus and
access-log buckets are `RETAIN` by design (evidence preservation) —
empty/delete them by hand only if you truly intend to.

**Cost note:** deploying incurs real, ongoing charges (Aurora storage
+ active ACUs, KB ingestion, Titan embeddings, Nova-Pro inference).
0-ACU idle keeps the floor low but it is not zero.
