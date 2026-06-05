# Architecture Decision Records

Each ADR captures one decision: its context, the choice made, the
alternatives rejected, and the consequences accepted. They are the durable
"why" behind the architecture; the end-to-end narrative is in
[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md).

| ADR | Decision |
|-----|----------|
| [0001](0001-aurora-pgvector-over-opensearch.md) | Aurora Serverless v2 pgvector as the vector store, not OpenSearch Serverless |
| [0002](0002-agentcore-runtime-with-fargate-fallback.md) | AgentCore Runtime as the primary host, with a documented Fargate fallback |
| [0003](0003-agent-ids-via-ssm-not-env.md) | Resolve Bedrock Agent/KB IDs from SSM at startup, not from `.env` |
| [0004](0004-codex-authored-frozen-gold-set.md) | The RAG eval gold set is authored by a separate model and frozen against the judged diff |
| [0005](0005-conditional-report-stages.md) | Report and solution stages skip when research finds no grounded source |
| [0006](0006-slos-md-single-source.md) | `docs/SLOs.md` is the single source the observability stack parses for alarms |
| [0007](0007-owner-acceptance-override.md) | A contested quality-gate FAIL may be closed by a recorded owner-acceptance override |

Format: **Status · Context · Decision · Consequences · Alternatives considered.**
