# 0003 — Resolve Bedrock Agent/KB IDs from SSM at startup, not from `.env`

**Status:** Accepted

## Context

The original AWS sample carried real, account-scoped `AGENT_ID` and
`AGENT_ALIAS_ID` values in a `.env` file that an operator hand-copied from the
console after a click-ops deploy. That is brittle (copy/paste drift),
unauditable (no link from the running crew back to the IaC that created the
resources), and a placeholder like `replace-with-your-id` silently passed
validation, failing only deep inside a Bedrock call.

## Decision

CDK publishes the agent id and alias id to SSM Parameter Store under the exact
names the crew expects. The crew resolves those parameters from SSM at startup
(`agent_ids.py`); `.env` carries only non-resource configuration. Fail-fast
startup validation rejects missing or placeholder values before any Bedrock
call.

## Consequences

- The IDs flow from IaC, not from a human copy step — no drift between deployed
  resources and the running crew.
- One SSM read at startup; the crew refuses to start if the parameters are
  absent or a model/topic value is a placeholder.
- An infra test asserts both SSM parameters exist under the crew-contract
  names, so the contract cannot silently break.

## Alternatives considered

- **`.env` with hand-copied IDs** — rejected: the click-ops baseline this work
  replaced.
- **CDK outputs piped manually into config** — rejected: still a manual step
  that drifts.

## Evidence

`infra/stacks/agent_stack.py` (SSM publish), `src/compliance_assistant/agent_ids.py`,
`src/compliance_assistant/startup.py`, `infra/tests/` (2 SSM parameters with
the contract names), `tests/test_startup.py`, `tests/test_agent_ids.py`.
