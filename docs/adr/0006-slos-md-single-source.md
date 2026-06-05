# 0006 — `docs/SLOs.md` is the single source the observability stack parses for alarms

**Status:** Accepted

## Context

When SLO targets live in a document and the alarms that enforce them live
separately in IaC, the two drift: someone edits the doc, the alarm keeps the
old threshold, and the alarm now watches the wrong number — or the wrong metric
entirely. "Observability" then becomes aspirational prose.

## Decision

`docs/SLOs.md` is the single source of truth. Each table row is one SLO with a
namespace, metric, statistic, period, comparator, and numeric threshold. The
observability stack parses that table at synth time and creates exactly one
CloudWatch alarm per row, bound to that row's real metric with that row's
threshold. A malformed/empty/duplicate table fails synth closed (raises), never
shipping a mismatched alarm set.

## Consequences

- Alarms cannot drift from the document: editing an SLO row changes the
  synthesized alarm.
- An infra test re-parses the same file and cross-checks the synthesized
  template — alarm count equals row count, and each alarm's period, evaluation
  periods, comparator, and threshold match its row — proving a semantic
  binding, not a threshold-only coincidence.

## Alternatives considered

- **Alarms defined in code, independent of the doc** — rejected: drifts from
  the stated SLOs.
- **No SLO document** — rejected: targets become unstated and unenforceable.

## Evidence

`infra/stacks/slo_contract.py` (`parse_slos`, fail-closed),
`infra/stacks/observability_stack.py` (one alarm per SLO),
`infra/tests/test_observability_stack.py` (count + per-alarm binding
cross-check), `docs/SLOs.md`.
