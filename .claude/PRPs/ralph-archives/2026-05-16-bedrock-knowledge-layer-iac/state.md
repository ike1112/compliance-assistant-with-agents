---
iteration: 1
max_iterations: 20
plan_path: ".claude/PRPs/plans/bedrock-knowledge-layer-iac.plan.md"
input_type: "plan"
started_at: "2026-05-15T23:36:15Z"
---

# PRP Ralph Loop State

## Codebase Patterns
- uv + hatchling project; runtime deps in `pyproject.toml`, CDK deps kept SEPARATE in `infra/requirements.txt`.
- House comment voice: plain-language, intent + consequence, no roadmap jargon. Commit subjects intent-named.
- No-commit rule: `docs/` untracked (also gitignored now); `infra/`/`src/`/`tests/`/`.claude/PRPs/` ARE tracked, commit per task.
- Autonomous gates are synth-only/free. `cdk bootstrap`/`deploy` (Task 13) is operator-gated — NEVER run in the loop.
- CANONICAL SYNTH: `cd infra && source .venv/Scripts/activate && npx --yes aws-cdk@latest synth <Stack> -q`. Deviation from plan: plan says `aws-cdk@2` but that resolves to an old CLI (schema 49) incompatible with aws-cdk-lib 2.254 (schema 53); MUST use `aws-cdk@latest` (>=2.1122.0). Activate the infra venv first so `python app.py` uses the right interpreter (Windows: `--app` path-override gets shell-mangled — use activate instead).
- S3 access-log target buckets need `ObjectOwnership.OBJECT_WRITER` (not BUCKET_OWNER_ENFORCED) or synth fails on the LogDeliveryWrite ACL. Corpus bucket keeps BUCKET_OWNER_ENFORCED.
- Plan-sequencing deviation: `agent_stack.py` created as a minimal stub in Task 2 (not Task 7) and `kb_stack.knowledge_base=None` placeholder, so `synth --all` is green every iteration. Task 7 fleshes out agent_stack; Task 5 sets knowledge_base.
- DECISION (iter 2, plan Task 4 GOTCHA invoked): `cdklabs.generative_ai_cdk_constructs` Aurora+KB constructs (managed AND `ExistingAmazonAuroraVectorStore`, probed) ALL require a running Docker daemon at synth (they `docker build` the `amazon-aurora-pgvector-custom-resources` lambda). Docker is installed here but daemon not running, and an autonomous loop must not depend on a Docker daemon. Separately the L2 store exposes no Serverless-v2 capacity props so it cannot meet the spec-locked 0-ACU anyway. => Use the plan's documented L1 fallback: self-built `rds.DatabaseCluster` Aurora PostgreSQL Serverless v2 (`serverless_v2_min_capacity=0`), VPC (no NAT), Secrets Manager creds, and a Docker-free pgvector bootstrap via RDS Data API (inline Python Lambda behind a `cr.Provider` CustomResource — no driver, no Docker, no VPC Lambda). KB/data-source/agent/guardrail become raw `aws_cdk.aws_bedrock.Cfn*` (pure CloudFormation, no Docker). gen-ai-cdk-constructs is removed from `infra/requirements.txt`/`pyproject.toml [infra]`.
- Bedrock pgvector table contract (AWS docs): schema `bedrock_integration`, table `bedrock_kb`, cols `id uuid pk default gen_random_uuid()`, `embedding vector(1024)`, `chunks text`, `metadata json`, `custom_metadata jsonb`; hnsw cosine index on embedding, gin fts index on chunks, gin index on custom_metadata.

## Current Task
Execute PRP plan and iterate until all validations pass.

## Plan Reference
.claude/PRPs/plans/bedrock-knowledge-layer-iac.plan.md

## Instructions
1. Read the plan file
2. Implement all incomplete tasks (1-12 autonomously; 13 is operator-gated, leave for human)
3. Run ALL validation commands from the plan
4. If any validation fails: fix and re-validate
5. Update plan file: mark completed tasks, add notes
6. When tasks 1-12 validations pass AND task 13 runbook authored (no deploy): output <promise>COMPLETE</promise>

## Progress Log
(Append learnings after each iteration)

## Iteration 1 - 2026-05-15T23:36Z

### Completed
- Task 1: CDK app skeleton (app.py two-stack wiring, cdk.json context, infra/requirements.txt, isolated infra/.venv). Commit 7dd8070.
- Task 2: ComplianceKbStack — KMS (rotation), access-log bucket, versioned/KMS/TLS/private RETAIN corpus bucket; agent_stack stub. Commit aa31bf2.
- Task 3: pytest config + 6 synth-time assertions (versioning, KMS, rotation, block-public, no-OpenSearch, TLS-deny). Commit 33130f0.

### Validation Status
- Task 1 imports: PASS (aws-cdk-lib 2.254.0, gen-ai-constructs 0.1.317)
- Task 2 synth ComplianceKbStack: PASS (exit 0, template emitted)
- Task 3 pytest infra/tests/test_kb_stack.py: PASS (6/6)

### Learnings
- `aws-cdk@2` npx tag is too old (CLI schema 49 vs lib schema 53). MUST use `aws-cdk@latest` (2.1122.0+). Recorded in Codebase Patterns.
- S3 log-target bucket needs OBJECT_WRITER ownership (LogDeliveryWrite ACL vs bucket-owner-enforced).
- Added `[tool.hatch.build.targets.wheel] packages=["src/compliance_assistant"]` so Task 11's `pip install -e .` works with the src layout.
- agent_stack.py + kb_stack.knowledge_base=None stubbed early (deviation) so `synth --all` is green throughout.

### Next Steps
- Task 4: Aurora Serverless v2 pgvector via cdklabs.generative_ai_cdk_constructs.amazonaurora (HIGH RISK — issue #695; L1 rds.DatabaseCluster + bootstrap-trigger fallback documented in plan Task 4 GOTCHA).
- Then Tasks 5-12 (KB, data source+ingest Lambda, agent stack, lint/guard/cost gates, crew.py rewire, citations), Task 13 runbook (NO deploy).

## Iteration 2 - 2026-05-15T23:55Z

### Completed
- Task 4 (via documented L1 fallback): VPC (no NAT), Aurora PostgreSQL Serverless v2 MinCapacity=0/Max=4, storage encrypted with corpus KMS key, Data API on, generated secret; Docker-free pgvector bootstrap (inline-code triggers.TriggerFunction over RDS Data API, idempotent DDL matching Bedrock's table contract). Removed gen-ai-cdk-constructs dep. Commit 01bc10c.

### Validation Status
- synth ComplianceKbStack: PASS (exit 0; DBCluster ServerlessV2 MinCapacity=0, EnableHttpEndpoint=True; OpenSearch count 0; Docker-free)
- pytest infra/tests/test_kb_stack.py: PASS (9/9, added Serverless-v2-zero / Data-API / storage-encrypted assertions)

### Learnings
- gen-ai-cdk-constructs Aurora+KB is Docker-bound at synth for ALL store variants (managed + Existing) — confirmed by probe. Fully removed from deps; rest of KB/Agent/Guardrail will be raw aws_cdk.aws_bedrock.Cfn* (no Docker).
- `rds.DatabaseCluster` with `serverless_v2_min_capacity=0` + `writer=ClusterInstance.serverless_v2(...)` + `enable_data_api=True` renders the spec-locked 0-ACU cleanly in aws-cdk-lib 2.254. `AuroraPostgresEngineVersion.VER_16_6` is valid.
- `triggers.TriggerFunction` + `Code.from_inline` + `cluster.grant_data_api_access(fn)` = Docker-free, driver-free, no-VPC pgvector bootstrap. Pattern reusable for any post-deploy SQL.

### Next Steps
- Task 5: raw `aws_cdk.aws_bedrock.CfnKnowledgeBase` with rdsConfiguration pointing at db_cluster (arn/secret/db, table=PGVECTOR_* constants, fieldMapping), embeddingModelArn from context (Titan v2). Set self.knowledge_base.
- Task 6: CfnDataSource S3 + chunking from context + ingest Lambda (S3 event → StartIngestionJob, scoped IAM).
- Tasks 7-12 then Task 13 runbook (NO deploy).

## Iteration 3 - 2026-05-16T00:05Z

### Completed
- Task 5: CfnKnowledgeBase (VECTOR, RDS storage) bound to the Aurora cluster; scoped KB IAM service role (InvokeModel on embedding arn, rds-data on cluster, secret read, corpus read+kms decrypt, SourceAccount confused-deputy guard); embedding model from CDK context; explicit dependency KB->cluster+bootstrap. Commit (task5).

### Validation Status
- synth ComplianceKbStack: PASS (exit 0)
- pytest infra/tests/test_kb_stack.py: PASS (11/11; added KB-is-RDS-backed + KB-role-no-wildcard assertions)

### Learnings
- aws_bedrock.CfnKnowledgeBase L1 shape: knowledge_base_configuration{type:VECTOR, vector_knowledge_base_configuration{embedding_model_arn}} + storage_configuration{type:RDS, rds_configuration{resource_arn,credentials_secret_arn,database_name,table_name="schema.table",field_mapping{primary_key_field,vector_field,text_field,metadata_field}}}. Embedding arn = arn:aws:bedrock:{region}::foundation-model/{model}.
- KB role trust: ServicePrincipal bedrock.amazonaws.com + StringEquals aws:SourceAccount={account} (confused-deputy). secret.grant_read / bucket.grant_read / key.grant_decrypt keep policies resource-scoped (no wildcard) — test asserts this for the upcoming cfn-guard gate.

### Next Steps
- Task 6: CfnDataSource (S3 type, bucket arn=corpus, chunking from context FIXED_SIZE/maxTokens/overlap) + ingest Lambda (inline, S3 ObjectCreated -> bedrock-agent:StartIngestionJob scoped to KB arn) + s3 notification + manual resync path.
- Tasks 7 (agent_stack: Guardrail+Agent+alias+SSM), 8 cfn-lint, 9 cfn-guard, 10 best-practices+cost, 11 crew.py SSM+trace, 12 citations, 13 runbook (NO deploy).

---
