# Compliance Assistant infrastructure

CDK v2 (Python) for the grounding and runtime layers:

- `ComplianceObservabilityStack` - Bedrock model-invocation logging, SLO
  alarms, dashboard, shared SNS notification topic
- `ComplianceKbStack` - KMS, corpus + access-log buckets, VPC, Aurora
  Serverless v2 pgvector, Knowledge Base, S3 data source, ingest Lambda, DLQ,
  ingest alarms, Bedrock failure event rule
- `ComplianceAgentStack` - Guardrail, Agent, alias, SSM parameters
- `ComplianceRuntimeEcrStack` - deterministic ECR repo for the runtime image
- `ComplianceRuntimeStack` - AgentCore Runtime host, report bucket, least-priv
  runtime role, durable run-manifest access

## Notes

- Aurora is the chosen vector store because the design targets low idle cost.
- The runtime keeps durable run manifests in the report bucket under `runs/`.
- The shared SNS topic is created in `ComplianceObservabilityStack` and reused
  by the KB stack for ingest-failure notifications.
- The repo is still best described as **verified in code and tests, not yet
  proven in production** until the live launch sequence is completed.

## Toolchain

```bash
cd infra
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
source .venv/Scripts/activate
npx --yes aws-cdk@latest synth ComplianceObservabilityStack ComplianceKbStack ComplianceAgentStack ComplianceRuntimeEcrStack ComplianceRuntimeStack -q
```

## Local verification

```bash
PYTHONPATH=src python -m pytest tests infra/tests -q
PYTHONPATH=src python -m pytest tests/evals -m gate -q
cd infra && npx --yes aws-cdk@latest synth ComplianceObservabilityStack ComplianceKbStack ComplianceAgentStack ComplianceRuntimeEcrStack ComplianceRuntimeStack -q
cd infra && cfn-lint -r us-east-1 cdk.out/ComplianceKbStack.template.json
cd infra && cfn-lint -r us-east-1 cdk.out/ComplianceAgentStack.template.json
cd infra && cfn-lint -r us-east-1 cdk.out/ComplianceRuntimeEcrStack.template.json
cd infra && cfn-lint -r us-east-1 cdk.out/ComplianceRuntimeStack.template.json
cd infra && cfn-lint -r us-east-1 cdk.out/ComplianceObservabilityStack.template.json
```

## Deploy runbook

`cdk deploy` provisions billable, slow-to-delete Bedrock + Aurora resources and
is operator-approved only.

Prereqs:

- AWS credentials for account `083340857999`
- region `us-east-1`
- Bedrock model access enabled for `amazon.titan-embed-text-v2:0` and
  `amazon.nova-pro-v1:0`
- Docker running for the `linux/arm64` runtime image

### 1. Bootstrap

```bash
npx --yes aws-cdk@latest bootstrap aws://083340857999/us-east-1 --qualifier complianceha
```

### 2. Pre-deploy checks

```bash
cd infra && npx --yes aws-cdk@latest synth --all -q
PYTHONPATH=src python -m pytest tests infra/tests -q
PYTHONPATH=src python -m pytest tests/evals -m gate -q
```

### 3. Deploy the non-runtime stacks

Never `deploy --all` before the image is pushed.

```bash
cd infra && npx --yes aws-cdk@latest deploy \
  ComplianceObservabilityStack ComplianceKbStack ComplianceAgentStack ComplianceRuntimeEcrStack \
  --require-approval any-change
```

### 4. Push the runtime image

```bash
ACCT=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCT}.dkr.ecr.us-east-1.amazonaws.com/compliance-assistant-runtime"
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "${ACCT}.dkr.ecr.us-east-1.amazonaws.com"
docker buildx build --platform linux/arm64 -f infra/runtime/Dockerfile \
  -t "$ECR_URI:<tag>" --push .
```

### 5. Deploy the runtime

```bash
cd infra && npx --yes aws-cdk@latest deploy ComplianceRuntimeStack \
  -c agentRuntimeImageTag=<tag> --require-approval any-change
```

### 6. Production proof steps

- upload a sample regulatory PDF and confirm ingestion completion
- confirm the SNS email subscription is in place
- run one grounded invocation and confirm artifacts land in `reports/{run_id}/`
- run one correct not-found invocation
- run `PYTHONPATH=src python -m tests.evals.harness.live_agent`
- confirm at least one `ComplianceAssistant/Crew` metric datapoint appears in
  CloudWatch

See [`../docs/live-launch.md`](../docs/live-launch.md) for the ordered launch
protocol and evidence checklist.

## Destroy

```bash
cd infra && npx --yes aws-cdk@latest destroy --all
```

The corpus and access-log buckets are retained by design. Clean them up
manually only when you truly intend to.
