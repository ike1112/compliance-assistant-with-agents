# Feature: AgentCore Runtime IaC — host the compliance crew as a scale-to-zero, 8-hour run-to-completion job

## Summary

Add a third CDK stack, `ComplianceRuntimeStack`, that declares an
`AWS::BedrockAgentCore::Runtime` (via the L1 `aws_cdk.aws_bedrockagentcore.CfnRuntime`,
present in the repo's pinned `aws-cdk-lib>=2.254.0`) to host the existing
CrewAI compliance crew. The runtime is configured for an 8-hour max
lifetime (`LifecycleConfiguration.MaxLifetime=28800`), serverless
scale-to-zero (inherent to AgentCore Runtime — microVM terminated after
session, consumption billing), a least-privilege execution role, and a
KMS-encrypted, versioned S3 report bucket so the crew's
`output/2-report.md` survives the ephemeral microVM. The crew is
container-packaged for the AgentCore HTTP service contract (linux/arm64,
port 8080, `POST /invocations` → `kickoff()` → S3 upload) via a
repo-committed `infra/runtime/` Dockerfile + thin server shim; the image
build/push and the live deploy are the operator HUMAN-GATE and are NOT
performed in-loop. `infra/cdk.json` gains the runtime context keys; a
new `infra/tests/test_runtime_stack.py` asserts the resource shape;
`infra/README.md` records the AgentCore-vs-Fargate decision with a
current-docs verification and a Reasoning-Gate justification, and the
deploy runbook names the RAG eval gate as a required pre-deploy step.

## User Story

As the operator of the compliance assistant
I want the crew hosted on a serverless, scale-to-zero runtime that can run for up to 8 hours and persist its report to versioned S3
So that long compliance analyses complete reliably, cost nothing at idle, and produce a durable, auditable report artifact — all provisioned reproducibly as infrastructure-as-code.

## Problem Statement

The crew currently only runs locally (`crewai run` → `kickoff()` →
local `output/*.md`). There is no reproducible, idle-free production
host, and a long run's report is lost when the process/host goes away.
Phase 4 must close GAP-REL-01 (no managed runtime) and GAP-PERF-01 (no
scale-to-zero long-run host) as synth-time-verifiable IaC, with the
hosting technology choice (AgentCore Runtime vs. ECS Fargate)
explicitly decided against *current* AWS docs.

## Solution Statement

`AWS::BedrockAgentCore::Runtime` is GA (Oct 2025) with first-class
CloudFormation + an L1 CDK construct already in the repo's CDK floor —
AgentCore IaC is **mature**, so it is the primary path; ECS Fargate is
documented as the rejected alternative. The new `ComplianceRuntimeStack`
mirrors the existing two-stack patterns exactly (constructor signature,
context reads, RETAIN on data-bearing resources, resource-scoped IAM,
S3 hardening, SSM-name reuse). All Phase 4 CHECK items are synth-time
and free; the billable image push + `cdk deploy` stay behind the
HUMAN-GATE.

## Metadata

| Field            | Value                                                                 |
| ---------------- | --------------------------------------------------------------------- |
| Type             | NEW_CAPABILITY                                                        |
| Complexity       | HIGH (new AWS service surface, IAM-scope tension, container contract)  |
| Systems Affected | `infra/` (new stack, app wiring, cdk.json, tests, README), `infra/runtime/` (new container artifact) |
| Dependencies     | `aws-cdk-lib>=2.254.0,<3.0.0` (already pinned; provides `aws_bedrockagentcore.CfnRuntime`), `constructs>=10.3.0`, `pytest>=8.0`, `cfn-lint>=1.0` |
| Estimated Tasks  | 9                                                                     |

---

## UX Design

### Before State
```
╔═══════════════════════════════════════════════════════════════════════════╗
║                              BEFORE STATE                                  ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   ┌────────────┐   crewai run   ┌────────────┐   writes   ┌────────────┐  ║
║   │  operator  │ ─────────────► │ kickoff()  │ ─────────► │ ./output/  │  ║
║   │ (laptop)   │                │ local proc │            │ 2-report.md│  ║
║   └────────────┘                └────────────┘            └────────────┘  ║
║                                                                            ║
║   USER_FLOW: operator runs the crew by hand on a workstation              ║
║   PAIN_POINT: no managed host (GAP-REL-01); no scale-to-zero long-run     ║
║               (GAP-PERF-01); report lost when the process/host dies       ║
║   DATA_FLOW: KB (Phase 1) → crew → ephemeral local file                   ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

### After State
```
╔═══════════════════════════════════════════════════════════════════════════╗
║                               AFTER STATE                                  ║
╠═══════════════════════════════════════════════════════════════════════════╣
║  ┌──────────┐  InvokeAgentRuntime  ┌─────────────────────────┐            ║
║  │ operator │ ───────────────────► │ AWS::BedrockAgentCore   │            ║
║  └──────────┘                      │ ::Runtime (microVM)     │            ║
║                                    │  • maxLifetime 8h       │            ║
║                                    │  • scale-to-zero        │            ║
║                                    │  • linux/arm64, :8080   │            ║
║                                    └───────────┬─────────────┘            ║
║                                  POST /invocations → kickoff()             ║
║                                                │                          ║
║                                                ▼                          ║
║                                    ┌─────────────────────────┐            ║
║                                    │ S3 report bucket        │ ◄── NEW    ║
║                                    │ (KMS, versioned, TLS,   │   durable  ║
║                                    │  block-public, RETAIN)  │   evidence ║
║                                    └─────────────────────────┘            ║
║   USER_FLOW: operator invokes the managed runtime; report lands in S3     ║
║   VALUE_ADD: reproducible IaC host, $0 idle, 8h runs, versioned report    ║
║   DATA_FLOW: KB (Phase 1) → AgentCore Runtime → versioned S3 object       ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

### Interaction Changes
| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| `infra/app.py` | 2 stacks | 3 stacks (adds `ComplianceRuntimeStack`) | `cdk synth --all` emits the runtime template |
| `infra/cdk.json` | KB/agent context only | + runtime context keys | runtime tunables are code-free overrides |
| `infra/README.md` | KB decision record | + AgentCore-vs-Fargate decision + runbook step | reviewer/operator can audit the choice |
| crew report | local `output/2-report.md` | also uploaded to versioned S3 (deploy path) | report is durable and auditable |

---

## Mandatory Reading

**CRITICAL: Implementation agent MUST read these files before starting any task:**

| Priority | File | Lines | Why Read This |
|----------|------|-------|---------------|
| P0 | `infra/stacks/kb_stack.py` | 108–340 | The exact stack/constructor/context/IAM-scope/S3-hardening/KMS/`raise ValueError` pattern to MIRROR |
| P0 | `infra/stacks/agent_stack.py` | 1–160 | Cross-stack ctor arg pattern + the verbatim SSM parameter names to REUSE |
| P0 | `infra/app.py` | 1–43 | How a third stack is instantiated and wired |
| P0 | `infra/tests/test_kb_stack.py` | 1–165 | `Template.from_stack` assertions, the no-wildcard-IAM test, context→ValueError test, TLS test to MIRROR |
| P1 | `infra/tests/test_agent_stack.py` | 1–60 | Cross-stack test fixture + SSM-name assertion pattern |
| P1 | `infra/cdk.json` | all | Context key shape to extend |
| P1 | `infra/README.md` | all | Heading structure + the existing *Reasoning-Gate justification* + "Deploy runbook (OPERATOR-GATED…)" patterns to extend |
| P1 | `src/compliance_assistant/main.py` | 1–60 | `run()` = the run-to-completion entrypoint the container shim calls |
| P1 | `src/compliance_assistant/agent_ids.py` | 1–100 | SSM-first id resolution + default SSM paths the runtime env must supply |
| P2 | `src/compliance_assistant/crew.py` | 90–140 | Output-file contract (`output/2-report.md`) the shim uploads |
| P2 | `infra/requirements.txt`, `pyproject.toml` | all | Pinned CDK/test deps; the `infra` extra |

**External Documentation:**
| Source | Section | Why Needed |
|--------|---------|------------|
| [CfnRuntime — aws-cdk-lib 2.254 (Python)](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrockagentcore/CfnRuntime.html) | constructor + ContainerConfigurationProperty / NetworkConfigurationProperty / LifecycleConfigurationProperty | Exact L1 prop names/shape (see "Patterns to Mirror") |
| [AWS::BedrockAgentCore::Runtime CFN ref](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-runtime.html) | Required props, `ProtocolConfiguration` allowed values, Ref/GetAtt | Required = AgentRuntimeArtifact, AgentRuntimeName, NetworkConfiguration, RoleArn |
| [AgentCore lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html) | maxLifetime / idleRuntimeSessionTimeout (60–28800; defaults 8h / 900s) | Justifies 8h config |
| [AgentCore Runtime service contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html) | HTTP: port 8080, `/invocations`, `/ping` | Container shim contract |
| [IAM permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html) | "AgentCore Runtime execution role" + trust policy | Least-priv role + the one unavoidable `ecr:GetAuthorizationToken: "*"` |
| [AgentCore GA / CFN support](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/) | GA Oct 2025; CFN Sep 2025; 8h windows | The maturity verification fact for the README decision |

---

## Patterns to Mirror

**STACK_CONSTRUCTOR + CROSS-STACK ARG (mirror agent_stack):**
```python
# SOURCE: infra/stacks/kb_stack.py:108-110 + agent_stack.py ctor
class ComplianceRuntimeStack(cdk.Stack):
    """AgentCore Runtime host for the compliance crew + its report bucket."""
    def __init__(self, scope: Construct, construct_id: str, *,
                 knowledge_base, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
```

**CONTEXT READ WITH DEFAULT (mirror kb_stack:232,317):**
```python
# SOURCE: infra/stacks/kb_stack.py:232-238
max_lifetime = int(self.node.try_get_context("runtimeMaxLifetimeSeconds") or 28800)
image_tag = self.node.try_get_context("agentRuntimeImageTag") or "latest"
```

**SYNTH-TIME GUARD (mirror kb_stack:325-330) — keep deploy-equivalence honest:**
```python
# SOURCE: infra/stacks/kb_stack.py:325-330
if not (60 <= max_lifetime <= 28800):
    raise ValueError(
        f"runtimeMaxLifetimeSeconds={max_lifetime!r} out of range: "
        "AgentCore Runtime maxLifetime must be 60..28800 seconds."
    )
```

**RESOURCE-SCOPED IAM, NEVER Resource:'*' (mirror kb_stack:256-273):**
```python
# SOURCE: infra/stacks/kb_stack.py:256-273
self.runtime_role.add_to_policy(iam.PolicyStatement(
    actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
    resources=[f"arn:aws:bedrock:{self.region}::foundation-model/*",
               f"arn:aws:bedrock:{self.region}:{self.account}:*"]))
```

**S3 HARDENING + RETAIN (mirror kb_stack:143-155, reuse self KMS key pattern):**
```python
# SOURCE: infra/stacks/kb_stack.py:143-155
self.report_bucket = s3.Bucket(self, "Report",
    versioned=True, encryption=s3.BucketEncryption.KMS,
    encryption_key=self.report_key,
    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
    enforce_ssl=True,
    object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
    server_access_logs_bucket=access_logs, server_access_logs_prefix="report/",
    removal_policy=cdk.RemovalPolicy.RETAIN)
```

**SSM-FIRST ID NAMES TO REUSE (verbatim — do not invent new names):**
```python
# SOURCE: src/compliance_assistant/agent_ids.py:28-29 / agent_stack.py:142-153
"/compliance-assistant/agent-id"
"/compliance-assistant/agent-alias-id"
```

**TEST FIXTURE + ASSERTION STYLE (mirror test_kb_stack / test_agent_stack):**
```python
# SOURCE: infra/tests/test_agent_stack.py:9-15 + test_kb_stack.py:139-145
def _template() -> Template:
    app = cdk.App()
    kb = ComplianceKbStack(app, "TestKb")
    rt = ComplianceRuntimeStack(app, "TestRt", knowledge_base=kb.knowledge_base)
    return Template.from_stack(rt)
```

**CfnRuntime L1 SHAPE (from CDK 2.254 docs — exact prop names):**
```python
from aws_cdk import aws_bedrockagentcore as agentcore
agentcore.CfnRuntime(self, "Runtime",
    agent_runtime_name="compliance_assistant_runtime",   # ^[a-zA-Z][a-zA-Z0-9_]{0,47}$
    agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
        container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
            container_uri=f"{self.repo.repository_uri}:{image_tag}")),
    network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
        network_mode="PUBLIC"),                          # serverless egress; no customer VPC/NAT
    role_arn=self.runtime_role.role_arn,
    lifecycle_configuration=agentcore.CfnRuntime.LifecycleConfigurationProperty(
        max_lifetime=max_lifetime, idle_runtime_session_timeout=900),
    protocol_configuration="HTTP",
    environment_variables={"TOPIC": ..., "MODEL": ...,
        "AWS_REGION_NAME": self.region,
        "REPORT_BUCKET": self.report_bucket.bucket_name},
    tags={"project": "compliance-assistant", "phase": "runtime"})
```

---

## Files to Change

| File | Action | Justification |
|------|--------|---------------|
| `infra/stacks/runtime_stack.py` | CREATE | The `ComplianceRuntimeStack` (ECR repo, report KMS key, report+access-log buckets, scoped execution role, `CfnRuntime`) |
| `infra/app.py` | UPDATE | Instantiate `ComplianceRuntimeStack(app, "ComplianceRuntimeStack", env=env, knowledge_base=kb_stack.knowledge_base)` |
| `infra/cdk.json` | UPDATE | Add `runtimeMaxLifetimeSeconds`, `agentRuntimeImageTag` context keys |
| `infra/runtime/Dockerfile` | CREATE | linux/arm64 base, `EXPOSE 8080`, installs the crew, runs the shim — the artifact the operator builds at HUMAN-GATE |
| `infra/runtime/server.py` | CREATE | Minimal HTTP shim: `GET /ping`→200, `POST /invocations`→`compliance_assistant.main.run()` then upload `output/2-report.md` to `$REPORT_BUCKET` |
| `infra/runtime/__init__.py` | CREATE | Make the shim importable for the unit test |
| `infra/tests/test_runtime_stack.py` | CREATE | Asserts the `AWS::BedrockAgentCore::Runtime` resource present + shape (8h lifetime, HTTP, role wired), report bucket versioned/KMS/TLS/block-public, role has no bare `Resource:"*"` except the documented-justified ECR-token op, SSM names reused, runtime stack adds no NAT gateway |
| `infra/tests/test_runtime_server.py` | CREATE | Offline unit test: `/ping` ok; `/invocations` calls `run()` and uploads the report (boto3 stubbed) — proves the run-to-completion contract without Docker/AWS |
| `infra/README.md` | UPDATE | Add "AgentCore Runtime hosting decision" section (decision + current-docs verification + Reasoning-Gate justification incl. the Fargate fallback and the single justified IAM-wildcard) and a deploy-runbook step naming the RAG eval gate as required pre-deploy |

---

## NOT Building (Scope Limits)

- **No `DockerImageAsset` / no image build in synth.** Synth must stay
  offline, deterministic, Docker-daemon-free, and spend-free. The stack
  references an `ecr.Repository` + a context image tag; the build/push
  is the operator HUMAN-GATE (documented in the runbook).
- **No `cdk deploy`/`bootstrap`/`InvokeAgentRuntime`.** HUMAN-GATE,
  billable, out of `/goal`.
- **No X-Ray / observability wiring in the role or stack.** Tracing,
  dashboards, model-invocation logging, SLO alarms are Phase 5 — adding
  X-Ray here would both scope-creep and force an `xray:* Resource:"*"`.
- **No changes to `kb_stack.py` / `agent_stack.py` / the crew's
  product code.** The shim lives under `infra/runtime/` and only
  *imports* `compliance_assistant.main.run`; it does not modify it
  (keeps the Phase 2/3 mutation/gold surface byte-stable).
- **No `RuntimeEndpoint` resource.** The default runtime endpoint is
  implicit; a custom endpoint is not required by any CHECK.

---

## Step-by-Step Tasks

Execute in order. Each task is atomic and independently verifiable.

### Task 1: Verify the L1 construct is importable in the pinned CDK
- **ACTION**: Confirm `from aws_cdk import aws_bedrockagentcore` resolves under the installed `aws-cdk-lib` (>=2.254.0).
- **VALIDATE**: `cd infra && python -c "from aws_cdk import aws_bedrockagentcore as a; print(a.CfnRuntime)"` exits 0.
- **GOTCHA**: If it fails, the venv has a pre-2.254 `aws-cdk-lib`; `pip install -U "aws-cdk-lib>=2.254.0,<3.0.0"` (matches the existing pin — not a pin change).

### Task 2: CREATE `infra/runtime/__init__.py` + `infra/runtime/server.py`
- **ACTION**: Minimal stdlib `http.server` app (no new deps): `GET /ping` → 200 `{"status":"Healthy"}`; `POST /invocations` → call `compliance_assistant.main.run()`, then `boto3.client("s3").upload_file("output/2-report.md", os.environ["REPORT_BUCKET", key)`; non-2xx + JSON error on failure.
- **IMPLEMENT**: read `REPORT_BUCKET` from env; key = `reports/{UTC-ISO}-2-report.md`; bind `0.0.0.0:8080`.
- **MIRROR**: import surface only — `from compliance_assistant.main import run` (do not modify `main`).
- **GOTCHA**: AgentCore HTTP contract requires exactly port **8080**, paths `/ping` and `/invocations` (service-contract doc).
- **VALIDATE**: `PYTHONPATH=src python -c "import infra.runtime.server"` exits 0.

### Task 3: CREATE `infra/runtime/Dockerfile`
- **ACTION**: `FROM --platform=linux/arm64 python:3.12-slim`; copy `src/` + `infra/runtime/`; `pip install .`; `EXPOSE 8080`; `CMD ["python","-m","infra.runtime.server"]`.
- **GOTCHA**: AgentCore Runtime requires **linux/arm64** images — the `--platform=linux/arm64` token must be literally present (the test greps for it).
- **VALIDATE**: file exists; `rg -n "linux/arm64" infra/runtime/Dockerfile` and `rg -n "EXPOSE 8080" infra/runtime/Dockerfile` both match.

### Task 4: CREATE `infra/stacks/runtime_stack.py`
- **ACTION**: `ComplianceRuntimeStack(cdk.Stack)` with ctor `(self, scope, construct_id, *, knowledge_base, **kwargs)`.
- **IMPLEMENT** (mirror kb_stack ordering & comment style, `R-<NAME>` tags):
  - `R-RT-KEY` KMS key (rotation on, RETAIN).
  - `R-RT-LOGS` access-logs bucket (OBJECT_WRITER, S3_MANAGED, block-public, TLS, RETAIN) — mirror kb_stack:128-136.
  - `R-RT-REPORT` versioned KMS report bucket (mirror kb_stack:143-155, RETAIN).
  - `R-RT-ECR` `ecr.Repository` (image_scan_on_push, immutable tags, RETAIN).
  - `R-RT-ROLE` execution role: `assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", conditions={"StringEquals":{"aws:SourceAccount":self.account},"ArnLike":{"aws:SourceArn":f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:*"}})`. Scoped statements: ECR image pull on `self.repo.repository_arn`; CloudWatch Logs create/put scoped to `arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*`; `bedrock:InvokeModel*` scoped (pattern above); `ssm:GetParameter` on the two `/compliance-assistant/agent-*` param ARNs; `report_bucket.grant_put` + `report_key.grant_encrypt`; `bedrock-agentcore:GetWorkloadAccessToken*` scoped to the workload-identity ARNs; `cloudwatch:PutMetricData` with `StringEquals cloudwatch:namespace=bedrock-agentcore` condition. The **only** bare `Resource:"*"` permitted: `ecr:GetAuthorizationToken` (account-level token op, no resource form — AWS-documented) — isolate it in its own statement with a `# JUSTIFIED:` comment.
  - `R-RT-RUNTIME` `agentcore.CfnRuntime` per the "Patterns to Mirror" shape; `max_lifetime` from context (validated 60..28800 via the `raise ValueError` guard), `network_mode="PUBLIC"`, `protocol_configuration="HTTP"`, env vars (TOPIC/MODEL from context, region, REPORT_BUCKET), `container_uri=f"{repo.repository_uri}:{image_tag}"`, tags.
  - Expose `self.runtime`, `self.report_bucket`, `self.repo`.
- **MIRROR**: `infra/stacks/kb_stack.py:108-340` (structure), `agent_stack.py` (ctor arg).
- **GOTCHA**: `agent_runtime_name` regex `^[a-zA-Z][a-zA-Z0-9_]{0,47}$` — underscores only, no hyphens.
- **VALIDATE**: `cd infra && python -c "import app"` exits 0.

### Task 5: UPDATE `infra/app.py`
- **ACTION**: Import + instantiate after the agent stack: `ComplianceRuntimeStack(app, "ComplianceRuntimeStack", env=env, knowledge_base=kb_stack.knowledge_base)`.
- **MIRROR**: `infra/app.py:33-41` instantiation style; keep the module docstring accurate (now three stacks, blast-radius note extended).
- **VALIDATE**: `cd infra && npx aws-cdk@latest synth --all -q` exits 0 and emits a third template.

### Task 6: UPDATE `infra/cdk.json`
- **ACTION**: Add `"runtimeMaxLifetimeSeconds": 28800` and `"agentRuntimeImageTag": "latest"` to `context`.
- **GOTCHA**: valid JSON, trailing-comma-free; do not touch the Phase 3 chunking keys.
- **VALIDATE**: `python -c "import json,pathlib;json.loads(pathlib.Path('infra/cdk.json').read_text())"` exits 0.

### Task 7: CREATE `infra/tests/test_runtime_stack.py`
- **ACTION**: `Template.from_stack` assertions (mirror test_kb_stack / test_agent_stack):
  - `t.resource_count_is("AWS::BedrockAgentCore::Runtime", 1)`.
  - `has_resource_properties("AWS::BedrockAgentCore::Runtime", Match.object_like({"LifecycleConfiguration":{"MaxLifetime":28800}, "ProtocolConfiguration":"HTTP", "NetworkConfiguration":{"NetworkMode":"PUBLIC"}}))`.
  - Report bucket: versioned, `BucketEncryption` KMS, block-public, a deny-non-TLS bucket policy (mirror `test_buckets_enforce_tls` kb_stack:148-163).
  - `resource_count_is("AWS::EC2::NatGateway", 0)` (the "no NAT" assertion — runtime stack creates no VPC/NAT).
  - SSM names: the role policy references exactly the two `/compliance-assistant/agent-*` parameter ARNs (mirror test_agent_stack:36-46 intent).
  - No-wildcard rule (mirror test_kb_stack:139-145) **adapted**: every runtime-role statement has a concrete `Resource` **except** a single statement whose only action is `ecr:GetAuthorizationToken` — assert that is the *sole* `Resource:"*"` and it carries the justified action, so an accidental future wildcard still fails.
- **VALIDATE**: `PYTHONPATH=src python -m pytest infra/tests/test_runtime_stack.py -q` all pass.

### Task 8: CREATE `infra/tests/test_runtime_server.py`
- **ACTION**: Offline unit test of the shim. `monkeypatch` `compliance_assistant.main.run` to a no-op that writes a temp `output/2-report.md`; stub `boto3` S3 client (e.g. a fake with `upload_file`); assert `GET /ping`→200, `POST /invocations` invokes `run` exactly once then calls `upload_file` with the `REPORT_BUCKET` and an `output/2-report.md` source; assert a `run()` exception yields a non-2xx JSON error (run-to-completion failure is surfaced, not swallowed).
- **GOTCHA**: no real network/AWS — this is a `gate`-clean offline test; use the test client against the handler, not a live socket if simpler.
- **VALIDATE**: `PYTHONPATH=src python -m pytest infra/tests/test_runtime_server.py -q` all pass.

### Task 9: UPDATE `infra/README.md`
- **ACTION**: Add a section **"AgentCore Runtime hosting decision (current-docs verified)"** containing:
  - **Decision**: AgentCore Runtime (`AWS::BedrockAgentCore::Runtime`) chosen over ECS Fargate.
  - **Current-docs verification** (dated, with the AWS doc URLs): AgentCore GA 2025-10; CloudFormation support 2025-09; L1 `aws_cdk.aws_bedrockagentcore.CfnRuntime` present in pinned `aws-cdk-lib>=2.254.0`; `MaxLifetime` up to 28800s (8h); serverless scale-to-zero (consumption billing, microVM terminated post-session). Conclusion: **AgentCore IaC is mature → not the Fargate fallback.**
  - **Rejected alternative (Fargate fallback, documented)**: run-to-completion Fargate task, arm64, no NAT (public subnet + VPC endpoints), S3-versioned report — why it's unnecessary given the verified maturity (more moving parts, no idle-zero without extra plumbing, duplicates AgentCore session isolation).
  - **Reasoning-Gate justification** for the single accepted IAM exception: `ecr:GetAuthorizationToken` has no resource-level form (AWS-documented account-scoped token op); isolated in its own statement; every other statement is resource-scoped; defer-to-Phase-5 note that X-Ray/observability is intentionally excluded here.
  - Extend the existing **"Deploy runbook (OPERATOR-GATED…)"**: add an explicit **pre-deploy required step** — "the RAG evaluation gate (`pytest tests/evals -m gate`) MUST pass on the deploying commit before building/pushing the image or `cdk deploy` of `ComplianceRuntimeStack`", plus the `docker buildx --platform linux/arm64 → ECR push → cdk deploy` operator steps.
- **MIRROR**: existing README heading style + the inline `*Reasoning-Gate justification:*` phrasing already in "Accepted cfn-guard exceptions".
- **VALIDATE**: `rg -n "RAG eval|evals -m gate" infra/README.md` matches in the runbook section; `rg -n "Fargate" infra/README.md` matches in the decision section.

---

## Testing Strategy

### Unit / synth Tests to Write
| Test File | Test Cases | Validates |
|-----------|-----------|-----------|
| `infra/tests/test_runtime_stack.py` | resource present; 8h lifetime; HTTP; PUBLIC; report bucket hardening; 0 NAT; SSM names; sole-justified IAM wildcard; bad `runtimeMaxLifetimeSeconds` context → `ValueError` (mirror test_kb_stack:21-28) | The IaC contract for CHECK 2 & 3 |
| `infra/tests/test_runtime_server.py` | `/ping` 200; `/invocations` runs crew once + uploads report; crew exception → error response | Run-to-completion container contract, offline |

### Edge Cases Checklist
- [ ] `runtimeMaxLifetimeSeconds` below 60 / above 28800 → synth `ValueError`
- [ ] `agent_runtime_name` contains only `[a-zA-Z0-9_]`, ≤48 chars
- [ ] report bucket has a deny-non-TLS policy (parity with kb buckets)
- [ ] no `AWS::EC2::NatGateway` and no `AWS::EC2::VPC` in the runtime stack
- [ ] runtime role: zero `Resource:"*"` statements except the single `ecr:GetAuthorizationToken` one
- [ ] `/invocations` surfaces a crew failure as non-2xx (not a silent 200)

---

## Validation Commands

> The phase-gate panel + the PRD CHECK regression leg are the gate of
> record. The lines below are **Phase 4's PRD GATE/CHECK/HUMAN-GATE
> items, verbatim** — the only validation contract for this phase.

- GATE: panel PASS required — same panel as Phase 2 (mutation+coverage / codex / security / code / CHECK-regression), evaluated on this phase's frozen diff before `complete`.
- CHECK: `cd infra && npx aws-cdk@latest synth --all -q` exits 0 with the runtime stack; `pytest infra/tests` asserts the AgentCore Runtime resource is present **or** (if AgentCore IaC is verified immature against current AWS docs) the documented ECS Fargate fallback: run-to-completion task, arm64, no NAT, S3-versioned report output.
- CHECK: AgentCore-vs-Fargate decision + the current-docs verification recorded in `infra/README.md` with a Reasoning-Gate justification.
- CHECK: cfn-lint 0 errors; cfn-guard compliant or justified; no IAM `Resource:"*"`.
- CHECK: runtime runbook names the Phase 3 eval gate as a required pre-deploy step.
- HUMAN-GATE: operator deploy of the runtime stack (billable) — excluded from `/goal`.

### Local check commands (how to exercise the CHECK items in-loop)
```bash
cd infra && npx aws-cdk@latest synth --all -q          # CHECK 2 (synth)
cd .. && PYTHONPATH=src python -m pytest infra/tests -q  # CHECK 2 (assertions)
cd infra && cfn-lint cdk.out/ComplianceRuntimeStack.template.json   # CHECK 4
rg -n "Reasoning-Gate|Fargate|current-docs" infra/README.md         # CHECK 3
rg -n "evals -m gate|RAG eval" infra/README.md                      # CHECK 5
# cfn-guard on the runtime template: COMPLIANT or a README-justified exception (CHECK 4)
```
**EXPECT**: every command exits 0 / matches; no `Resource: "*"` in the
synthesized runtime template except the single justified
`ecr:GetAuthorizationToken` statement (recorded in README — the
"or justified" branch of CHECK 4).

---

## Acceptance Criteria
- [ ] `cd infra && npx aws-cdk@latest synth --all -q` exits 0 and emits `ComplianceRuntimeStack`
- [ ] `pytest infra/tests` asserts the `AWS::BedrockAgentCore::Runtime` resource present (+ 8h / HTTP / PUBLIC / report bucket hardened / 0 NAT)
- [ ] `infra/README.md` records the AgentCore-vs-Fargate decision + dated current-docs verification + Reasoning-Gate justification
- [ ] cfn-lint 0 errors on the runtime template; cfn-guard COMPLIANT or README-justified; no unjustified IAM `Resource:"*"`
- [ ] the deploy runbook names the RAG eval gate (`pytest tests/evals -m gate`) as a required pre-deploy step
- [ ] no regression: `pytest infra/tests tests` still green; `kb_stack.py`/`agent_stack.py`/crew product code byte-unchanged
- [ ] no Docker build / no AWS calls during synth or tests

## Completion Checklist
- [ ] Tasks 1–9 done in order, each validated immediately
- [ ] Phase 4 PRD CHECK regression commands all exit 0
- [ ] Phase-gate panel PASS (codex / mutation+coverage / security / code / regression; test-engineer advisory)
- [ ] HUMAN-GATE (image push + `cdk deploy`) left for the operator — not run

---

## Risks and Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| AgentCore execution role needs `Resource:"*"` for token/log ops, colliding with the repo's no-wildcard rule | HIGH | HIGH | Scope every statement that *can* be; isolate the single AWS-mandated `ecr:GetAuthorizationToken:"*"`; condition `cloudwatch:PutMetricData`; record it as the "or justified" cfn-guard exception in README (matches the repo's existing justified-exception pattern). Defer X-Ray to Phase 5 so no `xray:*"*"` is introduced |
| `aws_bedrockagentcore` missing if venv has pre-2.254 `aws-cdk-lib` | MED | HIGH | Task 1 verifies import first; the fix is reinstalling to the *already-pinned* range, not changing the pin |
| `DockerImageAsset` would force a Docker build in synth (non-deterministic, spend, daemon dependency) | MED | HIGH | Explicitly NOT building: reference an `ecr.Repository` + context image tag; build/push is the HUMAN-GATE |
| AgentCore Runtime is request/response, but the crew is a batch job | MED | MED | The HTTP shim adapts `POST /invocations` → synchronous `kickoff()` → S3 upload; an 8-hour `maxLifetime` covers the long run; documented in README |
| `agent_runtime_name` regex rejects hyphens | LOW | MED | Use `compliance_assistant_runtime` (underscores), asserted by the test |
| cfn-guard cannot stream the runtime template in-loop (as already true for the KB stack) | MED | LOW | Reuse the established README Reasoning-Gate justification + cfn-lint(0) + targeted synth assertions; full cfn-guard at operator pre-deploy |

## Notes
- **Phase-gate deviation (deliberate):** the prp-plan skill's default
  "set PRD Status → in-progress" step is **skipped** — the phase-gate
  orchestrator's hard rule makes the `complete` chokepoint the sole PRD
  authority and forbids hand-editing the Status cell. Gate state already
  tracks Phase 4 (`init` done, base `ab3e739`).
- All Phase 4 CHECK items are synth-time and free; the only billable,
  irreversible work (ECR build/push, `cdk deploy`, `InvokeAgentRuntime`)
  is the HUMAN-GATE and is intentionally out of scope.
- The S3-versioned report bucket is built regardless of host choice —
  it is the durable-evidence requirement and the right design for the
  AgentCore path too (the microVM filesystem is ephemeral).
- Confidence: **8/10** for one-pass — the CDK L1 shape, IAM scoping
  tension, and the Docker-free synth strategy are all resolved here; the
  residual risk is exact `cfn-guard`/`cfn-lint` behavior on a brand-new
  resource type, mitigated by the established justified-exception path.
