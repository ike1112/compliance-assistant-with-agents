# Feature: AgentCore Runtime IaC — host the compliance crew as a scale-to-zero, async long-running job

## Summary

Add a third CDK stack, `ComplianceRuntimeStack`, that declares an
`AWS::BedrockAgentCore::Runtime` (via the L1 `aws_cdk.aws_bedrockagentcore.CfnRuntime`,
present in the repo's pinned `aws-cdk-lib>=2.254.0`) to host the existing
CrewAI compliance crew. AgentCore terminates a session after 15 minutes
if the invocation path blocks the `/ping` health thread; a multi-agent
compliance run routinely exceeds that. So the container implements the
**AWS-documented asynchronous long-running pattern**: `POST /invocations`
starts the crew on a background daemon thread and returns immediately
with a run id; a custom `GET /ping` reports `HealthyBusy` while a run is
in flight and `Healthy` when idle, which keeps the session alive up to
the 8-hour `LifecycleConfiguration.MaxLifetime`. The crew's terminal
artifacts are uploaded to a KMS-encrypted, versioned S3 report bucket so
they survive the ephemeral microVM; a no-grounded-findings run (a valid,
desirable not-found-honesty outcome) is uploaded and reported as a
successful completion, not an infrastructure failure. The execution role
is least-privilege and includes the `bedrock:InvokeAgent` grant the crew
actually needs (it builds `BedrockInvokeAgentTool` from SSM-resolved
agent ids). The image build/push and the live deploy are the operator
HUMAN-GATE and are NOT performed in-loop. `infra/cdk.json` gains the
runtime context keys; `infra/tests/test_runtime_stack.py` +
`test_runtime_server.py` assert the resource shape and the async
contract offline; `infra/README.md` records the AgentCore-vs-Fargate
decision with a dated current-docs verification and a Reasoning-Gate
justification, and the deploy runbook names the RAG eval gate as a
required pre-deploy step and the runtime→agent stack deploy ordering.

## User Story

As the operator of the compliance assistant
I want the crew hosted on a serverless, scale-to-zero runtime that can run asynchronously for up to 8 hours and persist its artifacts to versioned S3
So that long compliance analyses complete reliably, cost nothing at idle, and produce durable, auditable output — all provisioned reproducibly as infrastructure-as-code.

## Problem Statement

The crew currently only runs locally (`crewai run` → `kickoff()` →
local `output/*.md`). There is no reproducible, idle-free production
host, and a long run's output is lost when the process/host goes away.
Phase 4 must close GAP-REL-01 (no managed runtime) and GAP-PERF-01 (no
scale-to-zero long-run host) as synth-time-verifiable IaC, with the
hosting technology choice (AgentCore Runtime vs. ECS Fargate) explicitly
decided against *current* AWS docs, and the runtime↔crew contract
correct (async execution model; the IAM the crew actually needs; the
conditional-report outcome handled).

## Solution Statement

`AWS::BedrockAgentCore::Runtime` is GA (Oct 2025) with first-class
CloudFormation + an L1 CDK construct already in the repo's CDK floor —
AgentCore IaC is **mature**, so it is the primary path; ECS Fargate is
documented as the rejected alternative. AgentCore's *asynchronous*
execution model (background work + busy `/ping`) is the AWS-documented,
supported way to run minutes-to-hours jobs; the container implements
exactly that contract with the Python standard library (no new runtime
dependency, fully offline-testable — matching the repo's hand-rolled,
dependency-light ethos). The new `ComplianceRuntimeStack` mirrors the
existing two-stack patterns exactly (constructor signature, context
reads, RETAIN on data-bearing resources, resource-scoped IAM, S3
hardening, SSM-name reuse) and is wired to deploy after the agent stack.
All Phase 4 CHECK items are synth-time and free; the billable image
push + `cdk deploy` stay behind the HUMAN-GATE.

## Metadata

| Field            | Value                                                                 |
| ---------------- | --------------------------------------------------------------------- |
| Type             | NEW_CAPABILITY                                                        |
| Complexity       | HIGH (new AWS service surface, async contract, IAM-scope precision)   |
| Systems Affected | `infra/` (new stack, app wiring, cdk.json, tests, README), `infra/runtime/` (new container artifact) |
| Dependencies     | `aws-cdk-lib>=2.254.0,<3.0.0` (already pinned; provides `aws_bedrockagentcore.CfnRuntime`), `constructs>=10.3.0`, `pytest>=8.0`, `cfn-lint>=1.0` — no new runtime deps |
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
║   │ (laptop)   │                │ local proc │            │ N-*.md     │  ║
║   └────────────┘                └────────────┘            └────────────┘  ║
║   USER_FLOW: operator runs the crew by hand on a workstation              ║
║   PAIN_POINT: no managed host (GAP-REL-01); no scale-to-zero long-run     ║
║               (GAP-PERF-01); output lost when the process/host dies       ║
║   DATA_FLOW: KB+Agent (Phase 1) → crew → ephemeral local files            ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

### After State
```
╔═══════════════════════════════════════════════════════════════════════════╗
║                               AFTER STATE                                  ║
╠═══════════════════════════════════════════════════════════════════════════╣
║  ┌──────────┐ POST /invocations ┌─────────────────────────┐               ║
║  │ operator │ ─────────────────►│ AWS::BedrockAgentCore    │               ║
║  └──────────┘ ◄── 202 + run_id  │ ::Runtime (microVM)      │               ║
║       │  GET /ping → HealthyBusy │  • async bg thread       │               ║
║       │                         │  • maxLifetime 8h        │               ║
║       │                         │  • scale-to-zero         │               ║
║       │                         │  • linux/arm64, :8080    │               ║
║       │                         └───────────┬─────────────┘               ║
║       │            bg thread: main.run() → upload artifacts                ║
║       ▼                                     ▼                             ║
║  GET /ping → Healthy (done)     ┌─────────────────────────┐               ║
║                                 │ S3 report bucket        │ ◄── NEW       ║
║                                 │ (KMS, versioned, TLS,   │   durable     ║
║                                 │  block-public, RETAIN)  │   evidence    ║
║                                 └─────────────────────────┘               ║
║   USER_FLOW: operator starts an async run; polls /ping; artifacts in S3   ║
║   VALUE_ADD: reproducible IaC host, $0 idle, real 8h async runs, durable  ║
║   DATA_FLOW: KB+Agent (Phase 1) → AgentCore Runtime (async) → versioned S3║
╚═══════════════════════════════════════════════════════════════════════════╝
```

### Interaction Changes
| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| `infra/app.py` | 2 stacks | 3 stacks; runtime `add_dependency` on agent stack | `cdk synth --all` emits the runtime template; deploy order enforced |
| `infra/cdk.json` | KB/agent context only | + runtime context keys | runtime tunables are code-free overrides |
| `infra/README.md` | KB decision record | + AgentCore-vs-Fargate decision + runbook steps | reviewer/operator can audit the choice + ordering |
| crew output | local `output/*.md` | terminal artifacts uploaded to versioned S3 (deploy path) | output is durable and auditable; no-grounding run still succeeds |

---

## Mandatory Reading

**CRITICAL: Implementation agent MUST read these files before starting any task:**

| Priority | File | Lines | Why Read This |
|----------|------|-------|---------------|
| P0 | `infra/stacks/kb_stack.py` | 108–340 | The exact stack/constructor/context/IAM-scope/S3-hardening/KMS/`raise ValueError` pattern to MIRROR |
| P0 | `infra/stacks/agent_stack.py` | 1–160 | Cross-stack ctor pattern + the verbatim SSM parameter names to REUSE; note the agent-alias ARN is NOT exported (do not mutate this file) |
| P0 | `infra/app.py` | 1–43 | How a third stack is instantiated, env-wired, and `add_dependency`-ordered |
| P0 | `infra/tests/test_kb_stack.py` | 1–165 | `Template.from_stack` assertions, the no-wildcard-IAM test, context→ValueError test, TLS test to MIRROR |
| P0 | `src/compliance_assistant/crew.py` | 1–140, 240–260 | `compliance_reporting_task` is a `ConditionalTask` (`_has_grounded_findings`); `BedrockInvokeAgentTool` is built from SSM agent ids → the runtime role needs `bedrock:InvokeAgent` |
| P1 | `src/compliance_assistant/main.py` | 1–60 | `run()` = the blocking run-to-completion entrypoint the bg thread calls |
| P1 | `src/compliance_assistant/agent_ids.py` | 1–100 | SSM-first id resolution + default SSM paths; resolves at container start → runtime depends on agent stack being deployed |
| P1 | `infra/tests/test_agent_stack.py` | 1–60 | Cross-stack test fixture + SSM-name assertion pattern |
| P1 | `infra/cdk.json` | all | Context key shape to extend |
| P1 | `infra/README.md` | 43–95 | Heading style + the existing *Reasoning-Gate justification* + "Deploy runbook (OPERATOR-GATED…)" depth to mirror |
| P2 | `infra/requirements.txt`, `pyproject.toml` | all | Pinned CDK/test deps; the `infra` extra; no new runtime deps allowed |

**External Documentation:**
| Source | Section | Why Needed |
|--------|---------|------------|
| [Handle async & long-running agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html) | ping `Healthy`/`HealthyBusy`; entrypoint must not block; 15-min idle termination | The async contract the shim MUST implement (root of F-001 fix) |
| [AgentCore Runtime service contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html) | HTTP: port 8080, `/invocations`, `/ping` | Container endpoints/port |
| [CfnRuntime — aws-cdk-lib 2.254 (Python)](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrockagentcore/CfnRuntime.html) | ctor + ContainerConfiguration / NetworkConfiguration / LifecycleConfiguration props | Exact L1 prop names/shape |
| [AWS::BedrockAgentCore::Runtime CFN ref](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-runtime.html) | Required props; `agent_runtime_name` regex `^[a-zA-Z][a-zA-Z0-9_]{0,47}$`; Ref/GetAtt | Resource shape |
| [AgentCore lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html) | `maxLifetime`/`idleRuntimeSessionTimeout` (60–28800; defaults 8h / 900s) | Justifies the 8h config + range guard |
| [IAM permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html) | execution role + trust policy; `ecr:GetAuthorizationToken` is account-level (no resource form) | Least-priv role + the single justified wildcard |
| [AgentCore GA / CFN support](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/) | GA Oct 2025; CFN Sep 2025; 8h windows | The dated maturity verification fact for the README decision |

---

## Patterns to Mirror

**STACK_CONSTRUCTOR + CROSS-STACK ARGS (mirror agent_stack ctor):**
```python
# SOURCE: infra/stacks/kb_stack.py:108-110 + agent_stack.py ctor
class ComplianceRuntimeStack(cdk.Stack):
    """AgentCore Runtime host for the compliance crew + its report bucket."""
    def __init__(self, scope: Construct, construct_id: str, *,
                 knowledge_base, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
```

**CONTEXT READ WITH DEFAULT + RANGE GUARD (mirror kb_stack:232,317-330):**
```python
# SOURCE: infra/stacks/kb_stack.py:232-238 / 325-330
max_lifetime = int(self.node.try_get_context("runtimeMaxLifetimeSeconds") or 28800)
if not (60 <= max_lifetime <= 28800):
    raise ValueError(
        f"runtimeMaxLifetimeSeconds={max_lifetime!r} out of range: "
        "AgentCore Runtime maxLifetime must be 60..28800 seconds.")
image_tag = self.node.try_get_context("agentRuntimeImageTag") or "latest"
```

**RESOURCE-SCOPED IAM, NEVER literal Resource:'*' (mirror kb_stack:256-273):**
```python
# SOURCE: infra/stacks/kb_stack.py:256-273
self.runtime_role.add_to_policy(iam.PolicyStatement(
    actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
    resources=[f"arn:aws:bedrock:{self.region}::foundation-model/*",
               f"arn:aws:bedrock:{self.region}:{self.account}:*"]))
# The crew calls the deployed Bedrock Agent via BedrockInvokeAgentTool:
self.runtime_role.add_to_policy(iam.PolicyStatement(
    actions=["bedrock:InvokeAgent"],
    resources=[f"arn:aws:bedrock:{self.region}:{self.account}:agent-alias/*"]))
```

**S3 HARDENING + RETAIN (mirror kb_stack:128-155):**
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

**SSM-FIRST ID NAMES TO REUSE (verbatim — do not invent / do not mutate agent_stack):**
```python
# SOURCE: src/compliance_assistant/agent_ids.py:28-29 / agent_stack.py:142-153
"/compliance-assistant/agent-id"
"/compliance-assistant/agent-alias-id"
```

**DEPLOY ORDERING (runtime needs the agent stack's SSM params at container start):**
```python
# SOURCE: infra/app.py:33-41 instantiation style
rt = ComplianceRuntimeStack(app, "ComplianceRuntimeStack", env=env,
                            knowledge_base=kb_stack.knowledge_base)
rt.add_dependency(agent_stack)   # SSM agent-id params must exist first
```

**ASYNC SHIM CONTRACT (AWS runtime-long-run.html — stdlib, no new deps):**
```python
# /ping  -> 200 {"status": "HealthyBusy"}  while a run thread is alive
#        -> 200 {"status": "Healthy"}      when idle/done
# /invocations (POST) -> start daemon thread running main.run() then
#        upload terminal artifacts; return 202 {"run_id": ...} immediately.
#        Reject (409) if a run is already in flight for this microVM.
# bg thread MUST NOT be joined on the request path (would block /ping).
from compliance_assistant import main          # NOT `from ... import run`
# ... thread target: main.run(); then upload whatever output/*.md exist.
```

**CfnRuntime L1 SHAPE (CDK 2.254 — exact prop names):**
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
    tags={"project": "compliance-assistant", "component": "runtime"})
```

**TEST FIXTURE (mirror test_agent_stack:9-15 + test_kb_stack no-wildcard/ValueError):**
```python
# SOURCE: infra/tests/test_agent_stack.py:9-15
def _template() -> Template:
    app = cdk.App()
    kb = ComplianceKbStack(app, "TestKb")
    rt = ComplianceRuntimeStack(app, "TestRt", knowledge_base=kb.knowledge_base)
    return Template.from_stack(rt)
```

---

## Files to Change

| File | Action | Justification |
|------|--------|---------------|
| `infra/stacks/runtime_stack.py` | CREATE | `ComplianceRuntimeStack` (ECR repo, report KMS key, report+access-log buckets, scoped execution role incl. `bedrock:InvokeAgent`, `CfnRuntime`) |
| `infra/app.py` | UPDATE | Instantiate `ComplianceRuntimeStack`; `rt.add_dependency(agent_stack)`; extend module docstring (three stacks, blast radius, ordering) |
| `infra/cdk.json` | UPDATE | Add `runtimeMaxLifetimeSeconds`, `agentRuntimeImageTag` context keys |
| `infra/runtime/Dockerfile` | CREATE | linux/arm64 base, `EXPOSE 8080`, installs the crew, runs the async shim — the artifact the operator builds at HUMAN-GATE |
| `infra/runtime/server.py` | CREATE | stdlib async shim: `/ping` busy-state, `/invocations` starts bg thread → `main.run()` → upload existing `output/*.md`; no-report (no grounding) = success |
| `infra/runtime/__init__.py` | CREATE | Make the shim importable for the unit test |
| `infra/tests/test_runtime_stack.py` | CREATE | Asserts the `AWS::BedrockAgentCore::Runtime` resource + shape (context lifetime, HTTP, PUBLIC, role wired), report bucket hardened, `bedrock:InvokeAgent` present & scoped, sole literal `Resource:"*"` is `ecr:GetAuthorizationToken`, SSM names reused, 0 NAT, bad-lifetime context → `ValueError` |
| `infra/tests/test_runtime_server.py` | CREATE | Offline: `/ping` Healthy↔HealthyBusy across a run; `/invocations` returns fast (non-blocking) then runs once + uploads; **no-grounding (no 2-report.md) = 2xx success**; crew exception surfaced |
| `infra/README.md` | UPDATE | "AgentCore Runtime hosting decision" (decision + dated current-docs verification incl. sync-15min vs async-8h + Reasoning-Gate justification enumerating the single IAM wildcard, mirroring README:62-77 depth) + runbook steps (RAG eval gate pre-deploy; runtime→agent deploy ordering; arm64 build/push) |

---

## NOT Building (Scope Limits)

- **No `DockerImageAsset` / no image build in synth.** Synth stays
  offline, deterministic, Docker-daemon-free, spend-free. The stack
  references an `ecr.Repository` + a context image tag; build/push is
  the operator HUMAN-GATE.
- **No `cdk deploy`/`bootstrap`/`InvokeAgentRuntime`.** HUMAN-GATE,
  billable, out of `/goal`.
- **No observability in the role/stack — including `cloudwatch:PutMetricData` and X-Ray.** Metrics, dashboards, model-invocation
  logging, SLO alarms, tracing are Phase 5. Including them here would
  scope-creep AND introduce additional `Resource:"*"` statements
  (`cloudwatch:PutMetricData` has no resource form) the no-wildcard
  CHECK forbids. Log-group create/write IS included (operational
  necessity for the runtime), scoped to the runtime log-group ARN.
- **No new runtime dependency.** The async contract is implemented with
  the Python standard library; the optional `bedrock-agentcore` SDK is
  deliberately not added (keeps the runtime closure minimal and the
  shim fully offline-testable; documented in README).
- **No changes to `kb_stack.py` / `agent_stack.py` / crew product
  code.** The shim only *imports* `compliance_assistant.main`; it does
  not modify it (keeps the Phase 2 mutation surface and Phase 3
  gold/harness byte-stable). The agent-alias ARN is scoped by ARN
  pattern, not by exporting it from frozen `agent_stack.py`.
- **No `RuntimeEndpoint` resource.** The default runtime endpoint is
  implicit; no CHECK requires a custom endpoint.

---

## Step-by-Step Tasks

Execute in order. Each task is atomic and independently verifiable.

### Task 1: Verify the L1 construct is importable in the pinned CDK
- **ACTION**: Confirm `from aws_cdk import aws_bedrockagentcore` resolves.
- **VALIDATE**: `cd infra && python -c "from aws_cdk import aws_bedrockagentcore as a; print(a.CfnRuntime)"` exits 0.
- **GOTCHA**: If it fails, the venv has a pre-2.254 `aws-cdk-lib`; reinstall to the *already-pinned* range `pip install -U "aws-cdk-lib>=2.254.0,<3.0.0"` (not a pin change).

### Task 2: CREATE `infra/runtime/__init__.py` + `infra/runtime/server.py` (ASYNC contract)
- **ACTION**: stdlib `http.server` app implementing the AgentCore async long-run contract:
  - Module-level thread-safe state: `_run = {"thread": None, "id": None, "error": None}` guarded by a `threading.Lock`.
  - `GET /ping` → `200 {"status": "HealthyBusy"}` if `_run["thread"]` is alive, else `200 {"status": "Healthy"}`. Must be cheap and never blocked by the run.
  - `POST /invocations` → if a run thread is alive return `409`; else create `run_id` (uuid4), start a `threading.Thread(daemon=True, target=_do_run)`, return `202 {"run_id": run_id}` immediately (do NOT join).
  - `_do_run()`: `from compliance_assistant import main; main.run()`; then upload **whatever `output/*.md` exist** to `os.environ["REPORT_BUCKET"]` under key prefix `reports/{run_id}/`; record `_run["error"]` on exception (surfaced via `/ping` payload or a `/status` 200 with error field — never a silent success).
  - Bind `0.0.0.0:8080`.
- **IMPORT RULE (F-006)**: use `from compliance_assistant import main` and call `main.run()` (so a test patching `compliance_assistant.main.run` takes effect); do NOT `from compliance_assistant.main import run`.
- **ARTIFACT RULE (F-005)**: a missing `output/2-report.md` is a VALID no-grounded-findings outcome (`crew.py` `compliance_reporting_task` is a `ConditionalTask`); upload every `output/*.md` that exists (at minimum `output/1-requirements.md`), return success with a structured body `{"status":"completed","grounded": <2-report.md present>, "artifacts":[keys]}`. Absence of the report is NOT an error.
- **GOTCHA**: AgentCore HTTP contract requires exactly port **8080**, paths `/ping` and `/invocations`; `@entrypoint`-equivalent must not block the ping thread (AWS runtime-long-run.html).
- **VALIDATE**: `PYTHONPATH=src python -c "import infra.runtime.server"` exits 0.

### Task 3: CREATE `infra/runtime/Dockerfile`
- **ACTION**: `FROM --platform=linux/arm64 python:3.12-slim`; copy `src/` + `infra/runtime/`; `pip install .`; `EXPOSE 8080`; `CMD ["python","-m","infra.runtime.server"]`.
- **GOTCHA**: AgentCore Runtime requires **linux/arm64** images — the literal `--platform=linux/arm64` token must be present (the test greps for it).
- **VALIDATE**: file exists; `rg -n "linux/arm64" infra/runtime/Dockerfile` and `rg -n "EXPOSE 8080" infra/runtime/Dockerfile` both match.

### Task 4: CREATE `infra/stacks/runtime_stack.py`
- **ACTION**: `ComplianceRuntimeStack(cdk.Stack)` ctor `(self, scope, construct_id, *, knowledge_base, **kwargs)`.
- **IMPLEMENT** (mirror kb_stack ordering & `R-<NAME>` comment style):
  - `R-RT-KEY` KMS key (rotation on, RETAIN).
  - `R-RT-LOGS` access-logs bucket (OBJECT_WRITER, S3_MANAGED, block-public, TLS, RETAIN) — mirror kb_stack:128-136.
  - `R-RT-REPORT` versioned KMS report bucket (mirror kb_stack:143-155, RETAIN).
  - `R-RT-ECR` `ecr.Repository` (image_scan_on_push, immutable tags, RETAIN).
  - `R-RT-ROLE` execution role, trust `iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", conditions={"StringEquals":{"aws:SourceAccount":self.account},"ArnLike":{"aws:SourceArn":f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:*"}})`. Statements, **every one resource-scoped except the single documented exception**:
    - ECR image pull: `ecr:BatchGetImage`,`ecr:GetDownloadUrlForLayer` on `self.repo.repository_arn`.
    - **`ecr:GetAuthorizationToken` — SOLE statement with `Resource:"*"`** (account-level token op, no resource form per AWS docs). Isolate it; prefix a `# JUSTIFIED:` comment citing the AWS permissions doc.
    - CloudWatch Logs: `logs:CreateLogGroup`,`logs:CreateLogStream`,`logs:PutLogEvents` scoped to `arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*` (ARN with path wildcard — NOT literal `"*"`).
    - `bedrock:InvokeModel`,`bedrock:InvokeModelWithResponseStream` scoped (pattern above).
    - **`bedrock:InvokeAgent`** scoped to `arn:aws:bedrock:{region}:{account}:agent-alias/*` (F-002 — the crew's `BedrockInvokeAgentTool` calls the deployed agent alias; ARN pattern, not literal `"*"`; does not require mutating frozen `agent_stack.py`).
    - `ssm:GetParameter` on the two `/compliance-assistant/agent-*` param ARNs.
    - `report_bucket.grant_put(role)` + `report_key.grant_encrypt(role)`.
    - `bedrock-agentcore:GetWorkloadAccessToken*` scoped to the workload-identity-directory ARNs.
    - **NO `cloudwatch:PutMetricData`, NO `xray:*`** (Phase 5; would add wildcards — F-003).
  - `R-RT-RUNTIME` `agentcore.CfnRuntime` per the Patterns shape; `max_lifetime` from context with the 60..28800 `raise ValueError` guard, `network_mode="PUBLIC"`, `protocol_configuration="HTTP"`, env vars (TOPIC/MODEL from context, region, REPORT_BUCKET), `container_uri=f"{repo.repository_uri}:{image_tag}"`, tags.
  - Expose `self.runtime`, `self.report_bucket`, `self.repo`.
- **MIRROR**: `infra/stacks/kb_stack.py:108-340`; `agent_stack.py` ctor.
- **GOTCHA**: `agent_runtime_name` regex `^[a-zA-Z][a-zA-Z0-9_]{0,47}$` — underscores only, no hyphens (`compliance_assistant_runtime`).
- **VALIDATE**: `cd infra && python -c "import app"` exits 0.

### Task 5: UPDATE `infra/app.py`
- **ACTION**: Import + instantiate after the agent stack; capture the agent stack in a variable; `rt = ComplianceRuntimeStack(app, "ComplianceRuntimeStack", env=env, knowledge_base=kb_stack.knowledge_base)`; `rt.add_dependency(agent_stack)` (SSM agent-id params must exist at container start — agent_ids.py resolves via SSM).
- **MIRROR**: `infra/app.py:33-41`; extend the module docstring (now three stacks; runtime deploys after the agent stack; blast-radius note).
- **VALIDATE**: `cd infra && npx aws-cdk@latest synth --all -q` exits 0 and emits a third template; the runtime template `DependsOn`/stack-dependency reflects the agent stack.

### Task 6: UPDATE `infra/cdk.json`
- **ACTION**: Add `"runtimeMaxLifetimeSeconds": 28800` and `"agentRuntimeImageTag": "latest"` to `context`.
- **GOTCHA**: valid JSON, no trailing comma; do not touch the Phase 3 chunking keys.
- **VALIDATE**: `python -c "import json,pathlib;json.loads(pathlib.Path('infra/cdk.json').read_text())"` exits 0.

### Task 7: CREATE `infra/tests/test_runtime_stack.py`
- **ACTION**: `Template.from_stack` assertions (mirror test_kb_stack / test_agent_stack):
  - `resource_count_is("AWS::BedrockAgentCore::Runtime", 1)`.
  - `has_resource_properties(... Match.object_like({"ProtocolConfiguration":"HTTP","NetworkConfiguration":{"NetworkMode":"PUBLIC"}}))`.
  - **Lifetime test (M-003)**: assert `LifecycleConfiguration.MaxLifetime` equals the value the app context yields (read it the same way the stack does), NOT a hardcoded literal; PLUS a `pytest.raises(ValueError, match="out of range")` test instantiating the stack with `cdk.App(context={"runtimeMaxLifetimeSeconds": 30})` (mirror test_kb_stack:21-28).
  - Report bucket: versioned, KMS, block-public, deny-non-TLS bucket policy (mirror `test_buckets_enforce_tls`).
  - `resource_count_is("AWS::EC2::NatGateway", 0)` and `resource_count_is("AWS::EC2::VPC", 0)` (the "no NAT" assertion — runtime stack creates no VPC).
  - **`bedrock:InvokeAgent` present & scoped** to an `agent-alias/*` ARN (F-002 regression guard).
  - SSM: role policy references exactly the two `/compliance-assistant/agent-*` param ARNs.
  - **Wildcard rule (F-003, not a rubber stamp)**: collect every runtime-role statement whose `Resource == "*"`; assert that set has exactly one statement AND its `Action` set is exactly `{"ecr:GetAuthorizationToken"}`. Any other literal `"*"` (e.g. a stray `cloudwatch:PutMetricData`) fails the test.
- **VALIDATE**: `PYTHONPATH=src python -m pytest infra/tests/test_runtime_stack.py -q` all pass.

### Task 8: CREATE `infra/tests/test_runtime_server.py` (offline, async contract)
- **ACTION**: Drive the handler in-process (no real socket/AWS):
  - `monkeypatch` `compliance_assistant.main.run` to a fake that writes temp `output/*.md`; stub `boto3` S3 client (fake `upload_file`).
  - **Non-blocking**: `POST /invocations` returns `202` quickly even when the fake `run` sleeps briefly; assert `/ping` reports `HealthyBusy` while the thread is alive and flips to `Healthy` after it joins; assert `run` invoked exactly once and `upload_file` called for each produced artifact.
  - **No-grounding path (F-005)**: fake `run` writes ONLY `output/1-requirements.md` (no `2-report.md`); assert the run completes as success (`grounded=false`, `2xx`, report artifact absent) — NOT an error.
  - **Failure path**: fake `run` raises; assert the error is surfaced (non-success status / error field), never a silent success.
  - Second `POST /invocations` while one is in flight → `409`.
- **VALIDATE**: `PYTHONPATH=src python -m pytest infra/tests/test_runtime_server.py -q` all pass.

### Task 9: UPDATE `infra/README.md`
- **ACTION**: Add **"AgentCore Runtime hosting decision (current-docs verified, 2026-05)"**:
  - **Decision**: AgentCore Runtime (`AWS::BedrockAgentCore::Runtime`) over ECS Fargate.
  - **Current-docs verification** (dated, with the AWS doc URLs): AgentCore GA 2025-10; CloudFormation support 2025-09; L1 `aws_cdk.aws_bedrockagentcore.CfnRuntime` in pinned `aws-cdk-lib>=2.254.0`; **synchronous invocations are bounded (~15 min) — long runs MUST use the documented async pattern (background work + `HealthyBusy` ping), which is supported up to `MaxLifetime` 28800s (8h)**; serverless scale-to-zero (consumption billing, microVM terminated post-session). Conclusion: **AgentCore IaC is mature and async-suitable → not the Fargate fallback.**
  - **Rejected alternative (Fargate fallback, documented)**: run-to-completion Fargate task, arm64, no NAT (public subnet + VPC endpoints), S3-versioned report — why unnecessary given verified maturity (more moving parts, no idle-zero without extra plumbing, duplicates AgentCore session isolation).
  - **Reasoning-Gate justification** (mirror the depth of README:62-77): enumerate the specific runtime-role controls the operator's cfn-guard run checks (no public S3, KMS+TLS+versioned report bucket, KMS rotation, every IAM statement resource-scoped) and name the **single** accepted exception — `ecr:GetAuthorizationToken` `Resource:"*"` (AWS-documented account-scoped token op, no resource form), isolated in its own statement; explicitly state X-Ray/CloudWatch-metrics are intentionally deferred to Phase 5 so no other wildcard exists.
  - Extend **"Deploy runbook (OPERATOR-GATED…)"** with: (1) **required pre-deploy**: the RAG evaluation gate `pytest tests/evals -m gate` MUST pass on the deploying commit before building/pushing the image or `cdk deploy` of `ComplianceRuntimeStack`; (2) **deploy ordering**: `ComplianceAgentStack` MUST be deployed before `ComplianceRuntimeStack` (the crew resolves agent ids from SSM at container start); (3) operator steps: `docker buildx build --platform linux/arm64 -t <ecr-uri>:<tag>` → ECR push → `cdk deploy ComplianceRuntimeStack`.
- **MIRROR**: existing README heading style + the inline `*Reasoning-Gate justification:*` phrasing.
- **VALIDATE**: `rg -n "evals -m gate|RAG eval" infra/README.md` matches in the runbook; `rg -n "Fargate|async|HealthyBusy" infra/README.md` matches in the decision; `rg -n "ComplianceAgentStack MUST be deployed before" infra/README.md` matches.

---

## Testing Strategy

### Unit / synth Tests
| Test File | Test Cases | Validates |
|-----------|-----------|-----------|
| `infra/tests/test_runtime_stack.py` | resource present; HTTP/PUBLIC; context-driven lifetime + out-of-range→`ValueError`; report bucket hardened; 0 NAT/VPC; `bedrock:InvokeAgent` scoped; sole-`ecr:GetAuthorizationToken` wildcard; SSM names | CHECK 2 & 3 (IaC contract, no-wildcard) |
| `infra/tests/test_runtime_server.py` | `/ping` Healthy↔HealthyBusy; `/invocations` non-blocking 202; one run + uploads; **no-grounding = success**; failure surfaced; 409 on concurrent | Async run-to-completion contract, offline |

### Edge Cases Checklist
- [ ] `runtimeMaxLifetimeSeconds` < 60 or > 28800 → synth `ValueError`
- [ ] `agent_runtime_name` only `[a-zA-Z0-9_]`, ≤48 chars
- [ ] report bucket has a deny-non-TLS policy (parity with kb buckets)
- [ ] no `AWS::EC2::NatGateway` / `AWS::EC2::VPC` in the runtime stack
- [ ] exactly one literal `Resource:"*"` statement; its only action is `ecr:GetAuthorizationToken`
- [ ] `bedrock:InvokeAgent` granted, scoped to an `agent-alias` ARN
- [ ] valid no-grounding run (only `1-requirements.md`) → shim returns 2xx success
- [ ] `/invocations` returns before the crew finishes; `/ping` reports `HealthyBusy` meanwhile
- [ ] crew exception → surfaced, never silent success
- [ ] runtime stack `add_dependency(agent_stack)` reflected in synth

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
cd infra && npx aws-cdk@latest synth --all -q                       # CHECK 2 (synth)
cd .. && PYTHONPATH=src python -m pytest infra/tests -q              # CHECK 2 (assertions)
cd infra && cfn-lint -r us-east-1 cdk.out/ComplianceRuntimeStack.template.json   # CHECK 4 (0 errors; region-scoped — E3006 catalog-lag for the GA resource is documented in README)
# CHECK 4 cfn-guard: run cfn-guard against the runtime template with the
# same ruleset Phase 1 uses; pass criterion = COMPLIANT. If the in-loop
# environment cannot stream it (the documented KB-stack limitation),
# the "or justified" branch applies ONLY via the README Reasoning-Gate
# justification + cfn-lint(0) + the test_runtime_stack IAM/security
# assertions enumerated above — this is a reviewed artifact, not a code
# comment, and names the single accepted ecr:GetAuthorizationToken
# exception.
rg -n "Reasoning-Gate|Fargate|current-docs|HealthyBusy" infra/README.md   # CHECK 3
rg -n "evals -m gate|RAG eval" infra/README.md                            # CHECK 5
```
**EXPECT**: every command exits 0 / matches; the synthesized runtime
template contains exactly one `Resource:"*"` statement whose sole action
is `ecr:GetAuthorizationToken` (the README-justified "or justified"
branch of CHECK 4) and no other literal wildcard.

---

## Acceptance Criteria
- [ ] `cd infra && npx aws-cdk@latest synth --all -q` exits 0 and emits `ComplianceRuntimeStack` (depending on the agent stack)
- [ ] `pytest infra/tests` asserts the `AWS::BedrockAgentCore::Runtime` resource present (+ HTTP / PUBLIC / context lifetime / hardened report bucket / 0 NAT / scoped `bedrock:InvokeAgent` / sole justified wildcard)
- [ ] `infra/README.md` records the AgentCore-vs-Fargate decision + dated current-docs verification (sync-15min vs async-8h) + Reasoning-Gate justification naming the single IAM exception
- [ ] cfn-lint 0 errors on the runtime template; cfn-guard COMPLIANT or README-justified; no unjustified IAM `Resource:"*"`
- [ ] the deploy runbook names the RAG eval gate as a required pre-deploy step AND the runtime→agent deploy ordering
- [ ] the async contract holds: `/invocations` non-blocking, `/ping` busy-state, no-grounding run = success
- [ ] no regression: `pytest infra/tests tests` green; `kb_stack.py`/`agent_stack.py`/crew product code byte-unchanged
- [ ] no Docker build / no AWS calls during synth or tests; no new runtime dependency

## Completion Checklist
- [ ] Tasks 1–9 done in order, each validated immediately
- [ ] Phase 4 PRD CHECK regression commands all exit 0
- [ ] Phase-gate panel PASS (codex / mutation+coverage / security / code / regression; test-engineer advisory)
- [ ] HUMAN-GATE (image push + `cdk deploy`) left for the operator — not run

---

## Risks and Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Synchronous invocation killed at ~15 min (the original design flaw) | — | — | RESOLVED: shim uses the AWS-documented async pattern (bg thread + `HealthyBusy` ping); `/invocations` returns immediately; Task 8 asserts non-blocking + busy-state |
| Hosted crew cannot call the Bedrock Agent | — | — | RESOLVED: role grants scoped `bedrock:InvokeAgent` on `agent-alias/*`; Task 7 regression-guards it; deploy ordering documented + `add_dependency` |
| `cloudwatch:PutMetricData` forces a 2nd `Resource:"*"`, breaking the no-wildcard CHECK | — | — | RESOLVED: dropped (Phase 5 observability). Only `ecr:GetAuthorizationToken` wildcard remains; test asserts exactly that set |
| Valid no-grounding run treated as infra failure | — | — | RESOLVED: shim uploads existing artifacts and returns success with `grounded=false`; Task 8 covers it |
| `aws_bedrockagentcore` missing if venv has pre-2.254 `aws-cdk-lib` | MED | HIGH | Task 1 verifies import first; fix is reinstalling to the *already-pinned* range |
| `DockerImageAsset` would force a Docker build in synth | MED | HIGH | Explicitly NOT building: `ecr.Repository` + context tag; build/push is HUMAN-GATE |
| cfn-guard cannot stream the runtime template in-loop (as already true for the KB stack) | MED | LOW | PRD allows "or justified"; reuse the established README Reasoning-Gate justification at the KB-exception depth + cfn-lint(0) + targeted synth IAM/security assertions; full cfn-guard at operator pre-deploy |
| Runtime deployed before the agent stack → every invocation fails (no synth signal) | MED | MED | `rt.add_dependency(agent_stack)` enforces order; runbook states it explicitly |

## Notes
- **Phase-gate deviation (deliberate):** the prp-plan skill's default
  "set PRD Status → in-progress" step is **skipped** — the phase-gate
  orchestrator's hard rule makes the `complete` chokepoint the sole PRD
  authority and forbids hand-editing the Status cell. Gate state already
  tracks Phase 4 (`init` done, base `ab3e739`).
- **Revised after adversarial plan review** (codex REJECT + code-reviewer
  verify): F-001 async redesign, F-002 `bedrock:InvokeAgent` + ordering,
  F-003 drop `cloudwatch:PutMetricData`, F-004 concrete cfn-guard
  justification depth, F-005 conditional-report handling, F-006 import
  shape; plus M-001 deploy-ordering, M-002 typo, M-003 context-driven
  lifetime test. No threshold/CHECK/fixture/gold weakened.
- All Phase 4 CHECK items are synth-time and free; the only billable,
  irreversible work (ECR build/push, `cdk deploy`, `InvokeAgentRuntime`)
  is the HUMAN-GATE and is intentionally out of scope.
- The S3-versioned report bucket is built regardless of host choice —
  durable evidence is required and the microVM filesystem is ephemeral.
- Confidence: **8/10** for one-pass — the async contract, IAM scoping,
  conditional-report outcome, and Docker-free synth are all resolved
  here; residual risk is exact `cfn-guard`/`cfn-lint` behavior on a
  brand-new resource type, mitigated by the PRD-sanctioned, repo-
  precedented justified-exception path.
