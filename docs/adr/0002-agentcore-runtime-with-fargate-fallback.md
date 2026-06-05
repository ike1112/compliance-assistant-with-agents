# 0002 — AgentCore Runtime as the primary host, with a documented Fargate fallback

**Status:** Accepted

## Context

The crew is a batch job: long-running, idempotent, and run infrequently. It
needs a host that scales to zero between invocations rather than an always-on
service. Bedrock AgentCore Runtime is a managed option for exactly this shape,
but it is relatively new, so betting the deliverable solely on it carries
maturity risk.

## Decision

Target AgentCore Runtime as the primary host: it serves the agent over the
AgentCore HTTP contract (`POST /invocations`), scales to zero, and has an 8-hour
session TTL. An async pre-start shim satisfies the HTTP contract without
blocking the cold-start path. The runtime container image lives in its own
stack so image lifecycle is decoupled from runtime config. A Fargate
run-to-completion fallback (arm64, no NAT, S3-versioned report output) is
documented so the maturity question never blocks the deliverable.

## Consequences

- Scale-to-zero hosting that matches the batch workload's cost profile.
- Maturity risk is bounded: if AgentCore is unsuitable, the documented Fargate
  path is a known migration, not a redesign.
- Two stacks for the runtime (image + runtime) instead of one.

## Alternatives considered

- **Always-on ECS/Fargate service** — rejected as primary: idle cost for an
  infrequent batch job; kept as the run-to-completion fallback.
- **AWS Lambda** — rejected: the full crew run can exceed Lambda's execution
  ceiling.

## Evidence

`infra/stacks/runtime_stack.py`, `infra/stacks/runtime_ecr_stack.py`,
`infra/runtime/server.py`; the AgentCore-vs-Fargate discussion and operator
runbook in `infra/README.md`.
