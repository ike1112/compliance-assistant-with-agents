# Feature: Bedrock Knowledge-Layer IaC

## Summary

Stand up the first production-hardening subsystem for the compliance-assistant: a new AWS CDK v2 (Python) app under `infra/` that codifies the currently click-ops Bedrock stack — an S3 regulatory-PDF corpus (versioned, customer-KMS-encrypted, access-logged), an Aurora Serverless v2 PostgreSQL + pgvector vector store that scales to zero ACU when idle, a Bedrock Knowledge Base with an S3 data source and a configurable chunking strategy, and a Bedrock Agent + alias + Guardrail associated with that KB. Agent/alias IDs are published to SSM Parameter Store, and the existing CrewAI app is rewired to read them from SSM and to enable agent trace so source citations appear in the generated report. The entire subsystem is validated by a fast, free, autonomous loop (`cdk synth` → cfn-lint → cfn-guard → cdk best-practices → cost check → CDK assertion tests); the only billable, irreversible step (`cdk deploy`) is gated behind explicit operator approval and excluded from the autonomous loop.

## User Story

As a reviewer/operator of the compliance assistant
I want the Bedrock Knowledge Base, vector store, Agent, and Guardrail defined as reviewable, reproducible infrastructure with citations enabled
So that every generated compliance requirement is traceable to a versioned source PDF and the whole grounding layer can be recreated, audited, and cost-controlled instead of living as un-auditable console state.

## Problem Statement

Today the grounding layer is invisible click-ops: `src/compliance_assistant/crew.py:40-41` reads `AGENT_ID`/`AGENT_ALIAS_ID` from unchecked env vars pointing at a hand-built Agent (`XU3CNA2FY7`) + KB (`7VVXQQUZJI`) + Guardrail (`k505is5ekool`); the KB is fed by a non-reproducible web crawler; and `analysis/a.md` confirms the generated `output/2-report.md` contains **zero citations**. None of this is version-controlled, reviewable, or reproducible, and the corpus has no provenance — disqualifying for a compliance system whose output users treat as authoritative. This implements spec §3.1 and the citations portion of §3.4, closing backlog gaps GAP-OPS-01, GAP-SEC-01, GAP-SEC-02, GAP-GENAI-01.

## Solution Statement

A new `infra/` CDK v2 Python app with two stacks split by blast radius. `ComplianceKbStack`: a customer-managed KMS key (rotation on); an S3 corpus bucket (versioning, SSE-KMS, TLS-only, block-public-access) plus a separate S3 server-access-log bucket; an Aurora Serverless v2 PostgreSQL cluster with pgvector (min capacity 0 ACU / auto-pause, private subnets, Secrets Manager credentials); a Bedrock Knowledge Base bound to the Aurora vector store with an S3 data source pointed at the corpus bucket and a chunking strategy supplied via CDK context (default fixed-size, **not** a hardcoded final choice — the RAG-eval sub-project decides the real value later); and an S3-event-driven ingestion Lambda that calls `StartIngestionJob`, with a manually-invokable resync path. `ComplianceAgentStack`: a Bedrock Guardrail + version, a Bedrock Agent associated with the KB, and an Agent alias; the agent id and alias id are written to SSM Parameter Store. Finally, `crew.py` is rewired to resolve the agent ids from SSM (env-var fallback for local dev) and to enable agent trace, and a small `citations` module renders the returned source attributions into the report output. Higher-level `cdklabs.generative-ai-cdk-constructs` are used for the KB/Aurora/Agent (they auto-bootstrap the pgvector extension/schema/roles/tables); raw L1 `Cfn*` is the documented fallback.

## Metadata

| Field            | Value                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------- |
| Type             | NEW_CAPABILITY                                                                         |
| Complexity       | HIGH                                                                                   |
| Systems Affected | new `infra/` CDK app; `src/compliance_assistant/crew.py`; `pyproject.toml`; `.gitignore`; `.env.example` |
| Dependencies     | `aws-cdk-lib>=2.150.0`, `constructs>=10.3`, `cdklabs.generative-ai-cdk-constructs>=0.1.290`, `boto3>=1.37.6` (present), Node CDK CLI `aws-cdk@2` (via `npx`) |
| Estimated Tasks  | 13                                                                                     |

---

## UX Design

### Before State

```
╔════════════════════════════════════════════════════════════════════════════╗
║                              BEFORE STATE                                    ║
╠════════════════════════════════════════════════════════════════════════════╣
║  ┌──────────┐   reads env    ┌───────────────────┐                           ║
║  │ crew.py  │ ─────────────► │ AGENT_ID (unchecked)│                          ║
║  │  :40-41  │                │ from .env          │                          ║
║  └────┬─────┘                └─────────┬──────────┘                          ║
║       │ BedrockInvokeAgentTool          │ points at                          ║
║       ▼ (no enableTrace)                ▼                                     ║
║  ┌──────────┐            ┌──────────────────────────────────┐                ║
║  │  report  │ ◄───────── │ Click-ops Agent XU3CNA2FY7        │                ║
║  │ NO cites │            │  └─ KB 7VVXQQUZJI ◄─ WEB CRAWLER  │                ║
║  └──────────┘            │  └─ Guardrail k505is5ekool        │                ║
║                          └──────────────────────────────────┘                ║
║  USER_FLOW: run crew → report with zero source attribution                   ║
║  PAIN_POINT: corpus non-reproducible; infra un-auditable; no provenance      ║
║  DATA_FLOW: web → KB (unknown vector store) → agent → uncited report          ║
╚════════════════════════════════════════════════════════════════════════════╝
```

### After State

```
╔════════════════════════════════════════════════════════════════════════════╗
║                               AFTER STATE                                    ║
╠════════════════════════════════════════════════════════════════════════════╣
║  upload PDFs            ┌──────────────────────── infra/ (CDK) ────────────┐ ║
║  ┌────────┐  put obj    │ S3 corpus (versioned, SSE-KMS, access-logged)    │ ║
║  │ user   │ ──────────► │   │ S3:ObjectCreated → ingest Lambda → Ingestion │ ║
║  └────────┘             │   ▼                                              │ ║
║                         │ Bedrock KB ── Aurora Serverless v2 pgvector (0ACU)│ ║
║                         │   │  chunking = CDK context (configurable)        │ ║
║                         │ Bedrock Agent ── Guardrail+version ── Alias       │ ║
║                         │   └─ agentId / aliasId ─► SSM Parameter Store     │ ║
║                         └───────────────────────────┬──────────────────────┘ ║
║  ┌──────────┐  reads SSM (env fallback)             │                        ║
║  │ crew.py  │ ◄───────────────────────────────────────                       ║
║  │          │  BedrockInvokeAgentTool(enable_trace=True)                     ║
║  └────┬─────┘                                                                ║
║       ▼ citations.py renders source attributions                             ║
║  ┌──────────────┐                                                            ║
║  │ report WITH  │  every requirement → cited source PDF + location           ║
║  │  citations   │                                                            ║
║  └──────────────┘                                                            ║
║  VALUE_ADD: reproducible, auditable grounding; provenance in every report    ║
║  DATA_FLOW: versioned PDF → KB → agent(trace) → cited report                 ║
╚════════════════════════════════════════════════════════════════════════════╝
```

### Interaction Changes

| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| `crew.py:39-42` | `BedrockInvokeAgentTool(agent_id=env, agent_alias_id=env)` | ids from SSM (env fallback) + `enable_trace=True` | Agent identity is reproducible; trace data available |
| `output/2-report.md` | zero citations | source attributions appended per requirement | Output is auditable for compliance |
| Corpus | web crawler | upload PDF to S3 corpus bucket → auto re-ingest | Controlled, versioned, provenance-traceable corpus |
| Whole grounding layer | console click-ops | `cdk synth` / reviewable code in `infra/` | Infra is diff-able and recreatable |

---

## Mandatory Reading

**The implementation agent MUST read these before starting Task 1:**

| Priority | File | Lines | Why Read This |
|----------|------|-------|---------------|
| P0 | `docs/superpowers/specs/2026-05-15-compliance-prod-hardening-design.md` | §3.1, §3.4, §6, §8 | Locked decisions: Aurora pgvector (OpenSearch rejected — DO NOT relitigate), S3 PDF corpus, citations on, chunking configurable, AgentCore OUT of scope here |
| P0 | `src/compliance_assistant/crew.py` | 1-117 | Exact integration point; preserve plain-language comment voice and the `ConditionalTask`/`_has_grounded_findings` structure |
| P0 | `src/compliance_assistant/main.py` | 1-67 | Entry points; how env config is read; do not break `crewai run` |
| P1 | `pyproject.toml` | all | uv + hatchling, Python `>=3.10,<3.13`; where to add CDK deps and a `[tool.pytest.ini_options]` |
| P1 | `.gitignore` | all | `.env` already ignored, `!.env.example` kept; add `infra/cdk.out/` and CDK cruft here |
| P1 | `.env.example` | all | AWS region env names already present (`AWS_REGION`, `AWS_DEFAULT_REGION`); add SSM-path vars here |
| P2 | `analysis/a.md` | all | Confirms the zero-citations gap and live ids KB `7VVXQQUZJI` / Guardrail `k505is5ekool` |
| P2 | `docs/analysis/2026-05-15-compliance-hardening-backlog.md` | §3.1, §4 | `R-*` id scheme and the four gaps this closes (if file absent, rely on the spec) |

**External Documentation:**

| Source | Section | Why Needed |
|--------|---------|------------|
| [generative-ai-cdk-constructs — Bedrock KnowledgeBase (Python)](https://awslabs.github.io/generative-ai-cdk-constructs/apidocs/namespaces/bedrock/classes/KnowledgeBase.html) | KnowledgeBase, ChunkingStrategy | L2 API for KB + chunking; method/prop names to mirror |
| [generative-ai-cdk-constructs — Amazon Aurora Vector Store](https://awslabs.github.io/generative-ai-cdk-constructs/src/cdk-lib/amazonaurora/) | AmazonAuroraVectorStore, Serverless v2 0-ACU | Auto-bootstraps pgvector ext/schema/roles/tables; scale-to-zero confirms spec cost rationale |
| [awslabs/generative-ai-cdk-constructs KB README](https://github.com/awslabs/generative-ai-cdk-constructs/blob/main/src/cdk-lib/bedrock/knowledge-bases/README.md) | S3 data source, Agent, Guardrail | Data-source + Agent + Guardrail wiring patterns |
| [awslabs issue #695](https://github.com/awslabs/generative-ai-cdk-constructs/issues/695) | Aurora-pgvector-KB pitfalls | GOTCHA: known rough edges → pin construct version, keep L1 fallback |
| [build-on-aws/rag-postgresql-agent-bedrock](https://github.com/build-on-aws/rag-postgresql-agent-bedrock) | CDK Python staged Aurora→KB→Agent | Working Python mirror of the exact topology |
| [AWS — KB now supports Aurora PostgreSQL](https://aws.amazon.com/blogs/aws/knowledge-bases-for-amazon-bedrock-now-supports-amazon-aurora-postgresql-and-cohere-embedding-models/) | Aurora as KB store | Authoritative confirmation of the supported pattern |

---

## Patterns to Mirror

**COMMENT_VOICE (plain-language, intent + consequence, no jargon — house style):**

```python
# SOURCE: src/compliance_assistant/crew.py:33-35
# COPY THIS VOICE in infra/ comments and the crew.py edits:
# No agent below sets a model. CrewAI falls back to the MODEL
# env var from .env (bedrock/us.amazon.nova-pro-v1:0), so all
# three share the same one. Change it there to change all three.
```

**CONFIG_READ (current pattern being replaced — keep an env fallback so local `crewai run` still works):**

```python
# SOURCE: src/compliance_assistant/crew.py:39-42
agent_tool = BedrockInvokeAgentTool(
    agent_id=os.environ.get('AGENT_ID'),
    agent_alias_id=os.environ.get('AGENT_ALIAS_ID')
)
```

**FAIL-FAST AT IMPORT (mirror this guard style for the new config resolver):**

```python
# SOURCE: src/compliance_assistant/main.py:20-22
topic = os.environ.get('TOPIC')
if topic is None:
    raise Exception("TOPIC is not defined. Please add the topic as an argument")
```

**DOCSTRING style (short, triple-quoted, plain):**

```python
# SOURCE: src/compliance_assistant/crew.py:105
"""Creates the Compliance Automation crew"""
```

There is **no existing test pattern** in this repo (no `tests/`, no pytest config). Task 3 establishes the canonical CDK-assertion test pattern; later test tasks mirror Task 3.

---

## Files to Change

| File | Action | Justification |
|------|--------|---------------|
| `infra/app.py` | CREATE | CDK app entry; instantiates both stacks with env/account |
| `infra/cdk.json` | CREATE | `app = "python app.py"`; default context (chunking, embedding model) |
| `infra/requirements.txt` | CREATE | CDK Python deps pinned (kept separate from app runtime deps) |
| `infra/stacks/__init__.py` | CREATE | Package marker |
| `infra/stacks/kb_stack.py` | CREATE | R-KMS, R-S3-CORPUS, S3 access-log bucket, R-AURORA-VEC, R-KB, R-KB-DS, ingestion Lambda |
| `infra/stacks/agent_stack.py` | CREATE | R-GUARDRAIL (+version), R-BR-AGENT (KB-associated), R-BR-ALIAS, SSM params |
| `infra/lambdas/ingest/handler.py` | CREATE | S3:ObjectCreated → `bedrock-agent:StartIngestionJob`; manual resync entrypoint |
| `infra/tests/__init__.py` | CREATE | Package marker |
| `infra/tests/test_kb_stack.py` | CREATE | `Template.from_stack` assertions for KB stack security/cost invariants |
| `infra/tests/test_agent_stack.py` | CREATE | Assertions for Agent/Guardrail/SSM |
| `infra/README.md` | CREATE | Deploy/destroy runbook, context flags, L1 fallback note, cost note |
| `src/compliance_assistant/config.py` | CREATE | SSM-first agent-id resolver with env fallback + placeholder rejection |
| `src/compliance_assistant/citations.py` | CREATE | Render Bedrock agent trace attributions into report text |
| `src/compliance_assistant/crew.py` | UPDATE | Use `config.py` resolver; `enable_trace=True`; pipe citations into output |
| `tests/__init__.py` | CREATE | Package marker for app-side tests |
| `tests/test_config.py` | CREATE | Unit tests for the resolver (SSM hit, env fallback, placeholder reject) |
| `tests/test_citations.py` | CREATE | Unit tests for citation rendering from a sample trace payload |
| `pyproject.toml` | UPDATE | Add `[tool.pytest.ini_options]`; add `pytest`+`aws-cdk-lib`+constructs+gen-ai-constructs to a `dev`/`infra` optional-dependency group |
| `.gitignore` | UPDATE | Add `infra/cdk.out/`, `.cdk.staging/`, `cdk.context.json` |
| `.env.example` | UPDATE | Add `AGENT_ID_SSM_PATH`, `AGENT_ALIAS_ID_SSM_PATH` (keep existing keys) |

---

## NOT Building (Scope Limits)

- **AgentCore Runtime / Fargate** — spec §3.3, separate sub-project (GAP-REL-01). The crew still runs locally via `crewai run`; only its id source + trace change here.
- **RAG eval harness** — spec §3.2, separate sub-project (GAP-GENAI-02/03). The chunking value stays a configurable default; we do **not** tune or evaluate retrieval here.
- **Observability / SLOs / model-invocation logging** — spec §3.4 observability portion, separate sub-project (GAP-OPS-02/03). Only agent *trace for citations* is in scope, not dashboards/alarms.
- **Config & secrets hardening** — spec §3.5, separate sub-project (GAP-SEC-04/OPS-04). `.env` is already gitignored; we do not build the full startup-validation framework, only the narrow id resolver this feature needs.
- **`cdk deploy` to the live account inside the autonomous loop** — billable/irreversible; operator-gated only (Task 13).
- Migrating the existing live KB `7VVXQQUZJI` data or decommissioning the click-ops agent — out of scope; this stands up the new reproducible stack alongside.

---

## Step-by-Step Tasks

> No-commit rule: `docs/` stays untracked working notes — do not stage anything under `docs/`. All `infra/`, `src/`, `tests/`, `pyproject.toml`, `.gitignore`, `.env.example` changes ARE normal tracked code: commit each task. Commit subjects describe intent/outcome (per the repo's global comment/commit rule) — never roadmap-position labels.

### Task 1: Scaffold the CDK app skeleton

- **ACTION**: CREATE `infra/app.py`, `infra/cdk.json`, `infra/requirements.txt`, `infra/stacks/__init__.py`, `infra/tests/__init__.py`; UPDATE `.gitignore`.
- **IMPLEMENT**:
  - `.gitignore` — append on new lines: `infra/cdk.out/`, `.cdk.staging/`, `infra/cdk.context.json`.
  - `infra/requirements.txt`:
    ```
    aws-cdk-lib>=2.150.0,<3.0.0
    constructs>=10.3.0,<11.0.0
    cdklabs.generative-ai-cdk-constructs>=0.1.290
    ```
  - `infra/cdk.json`:
    ```json
    {
      "app": "python app.py",
      "context": {
        "chunkingStrategy": "FIXED_SIZE",
        "chunkMaxTokens": 512,
        "chunkOverlapPercent": 20,
        "embeddingModel": "amazon.titan-embed-text-v2:0",
        "@aws-cdk/core:bootstrapQualifier": "complianceha"
      }
    }
    ```
  - `infra/app.py` — `aws_cdk.App()`, read account/region from `CDK_DEFAULT_ACCOUNT`/`CDK_DEFAULT_REGION` (fallback region `us-east-1`), instantiate `ComplianceKbStack` then `ComplianceAgentStack(kb=...)`, `app.synth()`. Plain-language module docstring explaining the two-stack split by blast radius.
- **MIRROR**: comment voice from `crew.py:33-35`.
- **GOTCHA**: keep `infra/requirements.txt` separate from `pyproject.toml` runtime deps — CDK libs must not enter the crew runtime closure.
- **VALIDATE**:
  ```bash
  cd infra && python -m pip install -r requirements.txt -q && npx --yes aws-cdk@2 synth --app "python app.py" >/dev/null 2>&1; echo "synth-exit=$?"
  ```
  Expected: `synth-exit=0` once stacks exist (Task 2). For this task, instead assert files exist and `python -c "import aws_cdk"` works: `python -c "import aws_cdk, cdklabs.generative_ai_cdk_constructs; print('ok')"` → prints `ok`.
- **COMMIT**: `git add infra/app.py infra/cdk.json infra/requirements.txt infra/stacks/__init__.py infra/tests/__init__.py .gitignore && git commit -m "add CDK app skeleton for the Bedrock knowledge layer"`

### Task 2: Implement `ComplianceKbStack` — KMS + S3 corpus + access-log bucket

- **ACTION**: CREATE `infra/stacks/kb_stack.py` with the KMS key, log bucket, and corpus bucket only (Aurora/KB/ingestion added in Tasks 4-6).
- **IMPLEMENT**:
  - `kms.Key(self, "CorpusKey", enable_key_rotation=True, alias="alias/compliance-corpus")` — comment: this is `R-KMS`.
  - `s3.Bucket(self, "AccessLogs", encryption=S3_MANAGED, block_public_access=BLOCK_ALL, enforce_ssl=True, removal_policy=RETAIN, object_ownership=BUCKET_OWNER_ENFORCED)`.
  - `s3.Bucket(self, "Corpus", versioned=True, encryption=KMS, encryption_key=corpus_key, block_public_access=BLOCK_ALL, enforce_ssl=True, server_access_logs_bucket=access_logs, server_access_logs_prefix="corpus/", removal_policy=RETAIN)` — comment: `R-S3-CORPUS`, the bucket *is* the compliance evidence trail (cite spec §3.1).
  - Expose `self.corpus_bucket` and `self.corpus_key` as attributes.
- **MIRROR**: plain-language comments; one short docstring per class like `crew.py:105`.
- **GOTCHA**: `enforce_ssl=True` adds the TLS-only bucket policy cfn-guard expects; `BUCKET_OWNER_ENFORCED` avoids ACL findings; `RETAIN` so a stack delete never destroys regulatory evidence.
- **VALIDATE**: `cd infra && npx --yes aws-cdk@2 synth ComplianceKbStack --app "python app.py" -q` → exit 0, template emitted.
- **COMMIT**: `git commit -am "encrypt and version the S3 regulatory-PDF corpus with access logging"`

### Task 3: Establish the CDK-assertion test pattern for the KB stack

- **ACTION**: CREATE `infra/tests/test_kb_stack.py`; UPDATE `pyproject.toml` with pytest config + an `infra` optional-dependency group.
- **IMPLEMENT**:
  - `pyproject.toml`: add
    ```toml
    [project.optional-dependencies]
    infra = ["aws-cdk-lib>=2.150.0,<3.0.0", "constructs>=10.3.0,<11.0.0", "cdklabs.generative-ai-cdk-constructs>=0.1.290", "pytest>=8.0"]

    [tool.pytest.ini_options]
    testpaths = ["tests", "infra/tests"]
    ```
  - `test_kb_stack.py` using `aws_cdk.assertions.Template`:
    - `template.has_resource_properties("AWS::S3::Bucket", {"VersioningConfiguration": {"Status": "Enabled"}})`
    - corpus bucket `BucketEncryption` uses `aws:kms`
    - `template.has_resource_properties("AWS::KMS::Key", {"EnableKeyRotation": True})`
    - `template.resource_count_is("AWS::OpenSearchServerless::Collection", 0)` — **regression guard: OpenSearch Serverless was rejected in spec §3.1; its presence is a failure.**
    - every `AWS::S3::Bucket` has `PublicAccessBlockConfiguration` all-true
- **MIRROR**: this IS the canonical test pattern; Tasks 7/11/12 mirror its structure.
- **GOTCHA**: `Template.from_stack(stack)` forces synth — import the app's stack objects directly, do not shell out.
- **VALIDATE**: `python -m pip install -e ".[infra]" -q && python -m pytest infra/tests/test_kb_stack.py -q` → all pass.
- **COMMIT**: `git commit -am "add synth-time security assertions for the corpus stack"`

### Task 4: Add Aurora Serverless v2 pgvector vector store

- **ACTION**: UPDATE `infra/stacks/kb_stack.py` — add VPC + Aurora.
- **IMPLEMENT**:
  - `ec2.Vpc(self, "KbVpc", max_azs=2, nat_gateways=0)` with isolated/private subnets only (no NAT — cost; KB→Aurora is in-VPC).
  - Use `cdklabs.generative_ai_cdk_constructs.amazonaurora.AmazonAuroraVectorStore` (auto-bootstraps the pgvector extension, schema, roles, tables) configured for **Aurora Serverless v2 with min capacity 0 ACU / auto-pause**; credentials in Secrets Manager; cluster in isolated subnets; `embeddings_model_vector_dimension` matching the context `embeddingModel` (Titan v2 = 1024).
  - Expose `self.vector_store`.
- **MIRROR**: comment voice; cite spec §3.1 in a comment ("Aurora chosen over OpenSearch Serverless for 0-ACU idle — see spec §3.1; do not relitigate").
- **GOTCHA (issue #695)**: the construct's Aurora-pgvector path has had rough edges. Pin `cdklabs.generative-ai-cdk-constructs>=0.1.290`. If `synth` fails on the L2, fall back to: `rds.DatabaseCluster` Aurora-PostgreSQL Serverless v2 (`serverless_v2_min_capacity=0`, `serverless_v2_max_capacity=4`) + a `triggers.Trigger` Lambda that runs `CREATE EXTENSION vector; CREATE SCHEMA bedrock_integration; CREATE TABLE ...` per the KB README, then raw `bedrock.CfnKnowledgeBase` with `rdsConfiguration` in Task 5. Record which path was used in `infra/README.md`.
- **VALIDATE**: `cd infra && npx --yes aws-cdk@2 synth ComplianceKbStack --app "python app.py" -q` → exit 0; then extend `test_kb_stack.py`: assert an `AWS::RDS::DBCluster` exists with `ServerlessV2ScalingConfiguration.MinCapacity` == 0 and `resource_count_is("AWS::OpenSearchServerless::Collection", 0)` still holds. `python -m pytest infra/tests/test_kb_stack.py -q` → pass.
- **COMMIT**: `git commit -am "add Aurora Serverless v2 pgvector store (0-ACU idle)"`

### Task 5: Add the Bedrock Knowledge Base bound to Aurora

- **ACTION**: UPDATE `infra/stacks/kb_stack.py` — add the KB.
- **IMPLEMENT**: `bedrock.KnowledgeBase` (gen-ai-constructs) with `vector_store=self.vector_store`, `embeddings_model` from context (`amazon.titan-embed-text-v2:0`), instruction string describing the regulatory-grounding role. Expose `self.knowledge_base`.
- **MIRROR**: comment voice.
- **GOTCHA**: the embedding model must be enabled in the target region (`us-east-1`); model access is an account setting, surfaced at deploy (Task 13), not synth. Do not hardcode an embedding model arn — derive from context so the RAG-eval sub-project can change it.
- **VALIDATE**: `cd infra && npx --yes aws-cdk@2 synth ComplianceKbStack --app "python app.py" -q` → exit 0; assertion: `template.resource_count_is("AWS::Bedrock::KnowledgeBase", 1)`. `python -m pytest infra/tests -q` → pass.
- **COMMIT**: `git commit -am "create the Bedrock Knowledge Base on the Aurora vector store"`

### Task 6: Add the S3 data source + configurable chunking + ingestion Lambda

- **ACTION**: UPDATE `infra/stacks/kb_stack.py`; CREATE `infra/lambdas/ingest/handler.py`.
- **IMPLEMENT**:
  - Data source: `bedrock.S3DataSource` (or `addS3DataSource`) on `self.knowledge_base` pointing at `self.corpus_bucket`, with chunking built from CDK context: `FIXED_SIZE` → `max_tokens=context.chunkMaxTokens`, `overlap_percentage=context.chunkOverlapPercent`. Read context via `self.node.try_get_context(...)`. Comment: "chunking is a configurable default; the RAG-eval sub-project decides the real value (spec §3.1) — do not hardcode."
  - `infra/lambdas/ingest/handler.py`: boto3 `bedrock-agent` client; on S3 `ObjectCreated` event call `start_ingestion_job(knowledgeBaseId=..., dataSourceId=...)`; also runnable manually (handler treats an empty/`{"resync": true}` event as "ingest now"). KB id + DS id passed via Lambda env.
  - Wire `corpus_bucket.add_event_notification(s3.EventType.OBJECT_CREATED, s3n.LambdaDestination(ingest_fn))`. Grant the Lambda `bedrock:StartIngestionJob` scoped to the KB arn only (no wildcard).
- **MIRROR**: plain-language comments; fail-fast env read like `main.py:20-22` inside the handler.
- **GOTCHA**: scope the IAM action to the KB resource arn — a `Resource: "*"` here is the #1 cfn-guard finding. Lambda needs no VPC (control-plane API only).
- **VALIDATE**: `cd infra && npx --yes aws-cdk@2 synth ComplianceKbStack --app "python app.py" -q` → exit 0; assertion: a `AWS::Lambda::Function` exists and its execution-role policy for `bedrock:StartIngestionJob` has a non-`*` `Resource`. `python -m pytest infra/tests -q` → pass.
- **COMMIT**: `git commit -am "ingest corpus PDFs into the KB on upload with configurable chunking"`

### Task 7: Implement `ComplianceAgentStack` — Guardrail + Agent + alias + SSM

- **ACTION**: CREATE `infra/stacks/agent_stack.py`; CREATE `infra/tests/test_agent_stack.py`; UPDATE `infra/app.py` to pass the KB across stacks.
- **IMPLEMENT**:
  - `bedrock.Guardrail` + explicit version; content filters suitable for a compliance assistant (a sensible default set — comment that tuning is out of scope here).
  - `bedrock.Agent` with `knowledge_bases=[kb]`, foundation model `amazon.nova-pro-v1:0` (matches the crew's model), guardrail attached, instruction text mirroring the live agent's "answer using the provided sources" intent (cite `analysis/a.md`).
  - `bedrock.AgentAlias` for the agent.
  - `ssm.StringParameter(self, "AgentIdParam", parameter_name="/compliance-assistant/agent-id", string_value=agent.agent_id)` and `/compliance-assistant/agent-alias-id`. These replace the env placeholders.
  - `CfnOutput` for both ids too (human-visible).
  - `test_agent_stack.py`: assert 1 `AWS::Bedrock::Agent`, guardrail association present, 2 `AWS::SSM::Parameter` with the exact names.
- **MIRROR**: Task 3 test structure exactly.
- **GOTCHA**: cross-stack ref — pass the KB construct (or its id) via constructor; do not duplicate the KB. Agent foundation-model id must be the inference-profile-compatible id; keep it a stack parameter/context value, not a buried literal.
- **VALIDATE**: `cd infra && npx --yes aws-cdk@2 synth --all --app "python app.py" -q` → exit 0 for BOTH stacks. `python -m pytest infra/tests -q` → pass.
- **COMMIT**: `git commit -am "define the Guardrail-attached Bedrock Agent and publish ids to SSM"`

### Task 8: Autonomous validation gate — cfn-lint on every template

- **ACTION**: No file changes; run the lint gate and record results.
- **IMPLEMENT**: synth all, then for each file in `infra/cdk.out/*.template.json` call `mcp__aws-iac__validate_cloudformation_template` with the absolute template path.
- **VALIDATE**: zero `error`-severity findings across both templates. Any error → fix the offending construct in the relevant stack file, re-synth, re-lint until clean. Warnings: triage — fix or write a one-line justification into `infra/README.md` under "Lint exceptions".
- **GOTCHA**: if the aws-iac MCP is unavailable (it returned a server-side `'url'` error during planning), fall back to `npx --yes cfn-lint infra/cdk.out/*.template.json` and treat its exit code as the gate.
- **COMMIT**: `git commit -am "resolve cfn-lint findings in the knowledge-layer templates" --allow-empty` (empty allowed only if zero findings required no change; otherwise it carries the fixes).

### Task 9: Autonomous validation gate — cfn-guard compliance

- **ACTION**: run the compliance gate; fix or justify every finding via the Reasoning Gate.
- **IMPLEMENT**: for each `infra/cdk.out/*.template.json` call `mcp__aws-iac__check_cloudformation_template_compliance`. For every FAIL: either fix it in code, or record a Reasoning-Gate justification block (Risk / Why-not-applicable / Source) in `infra/README.md` under "Accepted cfn-guard exceptions". Re-synth after fixes.
- **VALIDATE**: every cfn-guard rule is PASS or has a written justification. Re-run until that invariant holds.
- **GOTCHA**: expected likely findings — S3 access logging (already done Task 2), KMS rotation (done Task 2), RDS storage encryption (set `storage_encrypted=True` + the corpus key on the cluster), IAM wildcards (scoped in Task 6/7). Fix in code, do not justify-away security findings.
- **COMMIT**: `git commit -am "harden templates against cfn-guard policy findings"`

### Task 10: Autonomous validation gate — CDK best-practices + cost regression

- **ACTION**: run best-practices scan and the cost check.
- **IMPLEMENT**:
  - `mcp__aws-iac__cdk_best_practices` — scan stacks; for each unmet item fix or justify in `infra/README.md`.
  - `mcp__aws-pricing-mcp-server__analyze_cdk_project` with `project_path` = absolute `infra/`. Assert: (a) no OpenSearch Serverless line item; (b) Aurora appears with a near-zero idle figure (0-ACU). Append the estimate to `infra/README.md` under "Cost snapshot".
- **VALIDATE**: OpenSearch absent (spec §3.1 regression guard) AND Aurora idle ≈ \$0 AND a cost snapshot is recorded. If OpenSearch appears → a wrong vector store was wired; revert to the Aurora construct.
- **GOTCHA**: if `analyze_cdk_project` MCP is down, fall back to a manual note: Aurora Sv2 @0 ACU bills storage + I/O only; record that and the assumption.
- **COMMIT**: `git commit -am "record cost snapshot and confirm no OpenSearch regression"`

### Task 11: Rewire `crew.py` to resolve agent ids from SSM with env fallback

- **ACTION**: CREATE `src/compliance_assistant/config.py`; UPDATE `src/compliance_assistant/crew.py`; CREATE `tests/__init__.py`, `tests/test_config.py`; UPDATE `.env.example`.
- **IMPLEMENT**:
  - `config.py` — `resolve_agent_ids() -> tuple[str, str]`: read SSM param names from `AGENT_ID_SSM_PATH` / `AGENT_ALIAS_ID_SSM_PATH` (defaults `/compliance-assistant/agent-id`, `/compliance-assistant/agent-alias-id`); try `boto3.client("ssm").get_parameter`; on failure fall back to `AGENT_ID`/`AGENT_ALIAS_ID` env. **Reject** values that are empty or start with `replace-with-` (raise a clear `RuntimeError`) — mirror the fail-fast voice of `main.py:20-22`.
  - `crew.py:39-42` — replace the two `os.environ.get` calls with `agent_id, agent_alias_id = resolve_agent_ids()` and pass `enable_trace=True` to `BedrockInvokeAgentTool`. Preserve every existing plain-language comment and the `ConditionalTask`/`_has_grounded_findings` logic untouched.
  - `.env.example` — add `AGENT_ID_SSM_PATH=/compliance-assistant/agent-id` and `AGENT_ALIAS_ID_SSM_PATH=/compliance-assistant/agent-alias-id`; keep all existing keys.
  - `tests/test_config.py` — monkeypatch boto3: (a) SSM returns ids → used; (b) SSM raises → env used; (c) env is `replace-with-...` → `RuntimeError`.
- **MIRROR**: fail-fast guard `main.py:20-22`; comment voice `crew.py:33-35`.
- **GOTCHA**: project memory — `uv run` does not strip `.env` quotes; do NOT wrap example values in quotes. `BedrockInvokeAgentTool`'s trace kwarg name may differ across `crewai[tools]` versions: before coding, `python -c "import inspect,crewai_tools.aws.bedrock.agents.invoke_agent_tool as m; print(inspect.signature(m.BedrockInvokeAgentTool.__init__))"` and use the actual parameter that enables trace; if none exists, document in `citations.py` that trace must be obtained via a direct `boto3 bedrock-agent-runtime invoke_agent(enableTrace=True)` wrapper and implement that wrapper instead.
- **VALIDATE**: `python -m pytest tests/test_config.py -q` → pass; `python -c "import compliance_assistant.crew"` → no error (import-clean).
- **COMMIT**: `git commit -am "resolve Bedrock agent ids from SSM and enable agent trace"`

### Task 12: Surface citations into the report output

- **ACTION**: CREATE `src/compliance_assistant/citations.py`, `tests/test_citations.py`; UPDATE `src/compliance_assistant/crew.py` to append rendered citations to the report task output.
- **IMPLEMENT**:
  - `citations.py` — `render_citations(trace: dict) -> str`: walk the Bedrock agent trace/`citations` structure, extract `retrievedReferences` (S3 uri + page/section span + text snippet), return a deterministic Markdown `## Sources` block (stable ordering, de-duplicated). Empty/malformed trace → returns `"## Sources\n\n_No grounded sources returned._"` (never raises — a missing trace must not break the run).
  - `crew.py` — after the reporting task produces output, append `render_citations(...)` to `output/2-report.md` (and `3-solution.md`). Keep the `_has_grounded_findings` gate intact: if the reporting task was skipped, do not write an empty sources block. Preserve comment voice.
  - `tests/test_citations.py` — feed a representative trace dict (one with `retrievedReferences`, one empty, one malformed) and assert the rendered block is correct, stable, and never raises.
- **MIRROR**: Task 3/Task 11 test style; docstring style `crew.py:105`.
- **GOTCHA**: citation rendering must be pure/deterministic for the future RAG-eval sub-project to assert on it — no timestamps, no set iteration order.
- **VALIDATE**: `python -m pytest tests/test_citations.py -q` → pass; full app-side suite `python -m pytest tests -q` → pass; `python -c "import compliance_assistant.crew"` → clean.
- **COMMIT**: `git commit -am "render grounded source citations into the compliance report"`

### Task 13: OPERATOR-GATED deploy runbook (excluded from the autonomous loop)

- **ACTION**: CREATE/finish `infra/README.md`. **Do NOT run `cdk bootstrap`/`cdk deploy` autonomously.**
- **IMPLEMENT**: `infra/README.md` runbook:
  - Prereqs: AWS creds for account `083340857999`, region `us-east-1` (per project memory); Bedrock model access enabled for `amazon.titan-embed-text-v2:0` and `amazon.nova-pro-v1:0`.
  - One-time: `npx --yes aws-cdk@2 bootstrap aws://083340857999/us-east-1 --qualifier complianceha`.
  - Deploy: `cd infra && npx --yes aws-cdk@2 deploy --all --require-approval any-change`.
  - Post-deploy: upload a sample regulatory PDF to the corpus bucket; confirm an ingestion job runs; run `crewai run` and confirm `output/2-report.md` ends with a populated `## Sources` block.
  - Destroy: `npx --yes aws-cdk@2 destroy --all` (note: corpus + log buckets are `RETAIN` by design — manual emptying required; this is intentional for evidence preservation).
  - **Cost note**: Aurora Serverless v2 bills storage/IO even at 0 ACU and ~\$0.12/ACU-hr while active; KB ingestion + Titan embeddings + Nova-Pro inference are usage-billed. State that deploy incurs real, ongoing charges and is operator-approved only.
  - "Accepted cfn-guard exceptions", "Lint exceptions", "Cost snapshot", and which Aurora path (L2 vs L1 fallback) was used — sections finalized here.
- **VALIDATE**: `test -f infra/README.md && grep -q "operator-approved" infra/README.md && grep -q "Cost note" infra/README.md` → all true. **No deploy executed.**
- **COMMIT**: `git commit -am "add operator-gated deploy/destroy runbook with cost note"`

---

## Testing Strategy

### Unit / synth tests to write

| Test File | Test Cases | Validates |
|-----------|-----------|-----------|
| `infra/tests/test_kb_stack.py` | versioning on; SSE-KMS; KMS rotation; all buckets block-public; OpenSearch count == 0; Aurora MinCapacity == 0; KB count == 1; ingest-Lambda IAM non-`*` | Security + cost invariants of the KB stack |
| `infra/tests/test_agent_stack.py` | Agent count == 1; guardrail associated; 2 SSM params with exact names | Agent stack contract |
| `tests/test_config.py` | SSM hit; SSM-miss→env; placeholder→RuntimeError | Id resolver |
| `tests/test_citations.py` | populated trace; empty trace; malformed trace | Deterministic, non-raising citation rendering |

### Edge Cases Checklist

- [ ] Empty/malformed agent trace → `## Sources` fallback line, no exception
- [ ] SSM unreachable (no creds / param absent) → env fallback path
- [ ] `replace-with-...` placeholder still in env → hard fail with clear message
- [ ] Reporting task skipped by `_has_grounded_findings` → no empty sources block written
- [ ] `cdk synth` with non-default `--context chunkingStrategy=...` still synths
- [ ] Stack delete does not destroy corpus/log buckets (RETAIN)

---

## Validation Commands

### Level 1: STATIC_ANALYSIS / SYNTH

```bash
cd infra && npx --yes aws-cdk@2 synth --all --app "python app.py" -q
```
**EXPECT**: exit 0; `infra/cdk.out/ComplianceKbStack.template.json` and `ComplianceAgentStack.template.json` emitted.

### Level 2: UNIT + SYNTH TESTS

```bash
python -m pip install -e ".[infra]" -q && python -m pytest tests infra/tests -q
```
**EXPECT**: all pass.

### Level 3: TEMPLATE COMPLIANCE (autonomous gate)

For each `infra/cdk.out/*.template.json`:
- `mcp__aws-iac__validate_cloudformation_template` → 0 errors
- `mcp__aws-iac__check_cloudformation_template_compliance` → all PASS or justified in `infra/README.md`
- `mcp__aws-iac__cdk_best_practices` → addressed or justified
- `mcp__aws-pricing-mcp-server__analyze_cdk_project` (path = `infra/`) → no OpenSearch; Aurora idle ≈ \$0

(Fallbacks if any MCP is down are specified per task.)

### Level 4: DATABASE_VALIDATION

N/A at synth/loop time — Aurora/pgvector schema is created by the construct/trigger only on real deploy (Task 13, operator-gated).

### Level 5: BROWSER_VALIDATION

N/A — no UI.

### Level 6: MANUAL_VALIDATION (operator, post-deploy only)

Upload a sample PDF → confirm ingestion job → `crewai run` → `output/2-report.md` ends with a populated `## Sources` block citing that PDF.

---

## Acceptance Criteria

- [ ] `infra/` CDK app synths both stacks (exit 0) with the documented context flags
- [ ] All Level-2 tests pass; OpenSearch-count-0 and Aurora-MinCapacity-0 assertions present and green
- [ ] cfn-lint: 0 errors; cfn-guard: all PASS or Reasoning-Gate-justified in `infra/README.md`
- [ ] Cost snapshot recorded; no OpenSearch Serverless in the estimate
- [ ] `crew.py` resolves ids from SSM with env fallback, rejects placeholders, and enables trace — `import compliance_assistant.crew` is clean
- [ ] Citation rendering is deterministic and never raises on bad input
- [ ] `infra/README.md` runbook exists with operator-approved deploy + cost note; **no deploy was executed autonomously**
- [ ] Existing `crewai run` path and the `ConditionalTask` logic remain intact (no regression)
- [ ] Nothing under `docs/` was staged/committed

## Completion Checklist

- [ ] Tasks 1-13 completed in order, each committed with an intent-named subject
- [ ] Level 1 synth passes
- [ ] Level 2 tests pass
- [ ] Level 3 compliance gates pass or justified
- [ ] Level 4/5 correctly N/A
- [ ] Acceptance criteria all met
- [ ] Spec §3.1 + §3.4-citations satisfied; gaps GAP-OPS-01/SEC-01/SEC-02/GENAI-01 addressed

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| gen-ai-cdk-constructs Aurora-pgvector path broken (issue #695) | MED | HIGH | Pinned version `>=0.1.290`; documented raw-L1 `CfnKnowledgeBase` + `rds.DatabaseCluster` + bootstrap-trigger fallback in Task 4; synth gate catches it immediately |
| aws-iac/aws-pricing MCP server-side errors (seen during planning) | MED | MED | Per-gate CLI fallbacks (`npx cfn-lint`, manual cost note) specified in Tasks 8-10 |
| `BedrockInvokeAgentTool` trace kwarg differs by version | MED | MED | Task 11 inspects the actual `__init__` signature first; if absent, implement a direct `bedrock-agent-runtime invoke_agent(enableTrace=True)` wrapper |
| Autonomous loop attempts a billable deploy | LOW | HIGH | `cdk deploy`/`bootstrap` are Task 13 operator-gated only; every other task's VALIDATE is free/synth-only; explicit "do NOT run deploy" guard |
| Embedding/foundation model not enabled in `us-east-1` | MED | MED | Surfaced as a deploy-time prereq in the runbook (Task 13); not a synth/loop blocker |
| Cross-stack KB reference duplicates the KB | LOW | MED | KB construct passed by reference into `ComplianceAgentStack` ctor; `--all` synth + agent-stack assertions verify single KB |

---

## Notes

- **Locked, do not relitigate**: Aurora Serverless v2 pgvector over OpenSearch Serverless (spec §3.1) — the OpenSearch-count-0 test is a deliberate regression guard, not an open question.
- **No-commit rule** applies only to `docs/` (untracked working notes). `infra/`/`src/`/`tests/` are normal tracked code committed per task with intent-named subjects (never roadmap-position labels), per the repo's global commit-message rule.
- **Why two stacks**: corpus+vector+KB (data-bearing, RETAIN, slow to recreate) are isolated from Agent+Guardrail+alias (cheap, fast to iterate) so agent-prompt iteration never risks the corpus.
- **Chunking is intentionally a default, not a decision** — the RAG-eval sub-project owns tuning it (spec §3.1/§3.2); exposing it as CDK context is what makes that later work a config change, not a refactor.
- **Confidence**: 8/10 for one-pass autonomous success. The −2 is concentrated in the gen-ai-cdk-constructs Aurora path (#695) and the `crewai[tools]` trace-kwarg variance; both have explicit, synth/inspect-verified fallbacks so the loop converges rather than stalls.
```
