# 0001 — Aurora Serverless v2 pgvector as the vector store, not OpenSearch Serverless

**Status:** Accepted

## Context

The Bedrock Knowledge Base needs a vector store. The two managed options are
Amazon OpenSearch Serverless and Aurora Serverless v2 with the `pgvector`
extension. This is a single-user, low-and-bursty compliance sample: it runs a
report a few times, then sits idle. Idle cost — not peak throughput — is the
dominant cost driver, and "defensible to a senior reviewer on cost" is an
explicit goal.

## Decision

Use Aurora Serverless v2 with `pgvector` as the KB vector store, configured to
scale to zero (`MinCapacity == 0` ACU). The Knowledge Base `Type` is set
explicitly to `RDS`. A deploy-time bootstrap creates the `vector` extension and
schema via the RDS Data API.

## Consequences

- Near-zero cost while idle; capacity tracks actual report demand.
- A cold-start latency penalty on the first query after the cluster has scaled
  to zero — acceptable for a batch report tool.
- Infra tests assert `MinCapacity == 0`, KB `Type == RDS`, and that the service
  inventory contains **no** OpenSearch, so the decision cannot silently
  regress.

## Alternatives considered

- **OpenSearch Serverless** — rejected: a minimum always-on OCU floor means a
  standing idle bill regardless of traffic, which dominates total cost for this
  workload.

## Evidence

`infra/stacks/kb_stack.py`; `infra/tests/` (OpenSearch count == 0, RDS
`MinCapacity == 0`, KB `Type == RDS`); `docs/analysis/_evidence/analyze-cdk-project.json`
(no OpenSearch in the inventory).
