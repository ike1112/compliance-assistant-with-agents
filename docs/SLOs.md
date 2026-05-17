# Service-Level Objectives — compliance-assistant crew

This file is the **single source of truth** for the crew's reliability
contract. `ComplianceObservabilityStack` parses the table below and
creates exactly one CloudWatch alarm per row, bound to that row's
metric with that row's threshold; `infra/tests/test_observability_stack.py`
re-parses the same table and cross-checks the synthesized template, so
the alarms cannot drift from this document and cannot watch the wrong
metric.

Each SLO has a **30-day error budget**: the amount of breach tolerated
in a rolling 30 days before the objective is considered missed. Latency
SLOs alarm when the percentile exceeds the target; quality and
availability SLOs alarm when the value drops below the target.

- **Per-stage + end-to-end latency (p50/p95)** — how long each agent
  stage and the whole run take. Emitted by the tracing module
  (`ComplianceAssistant/Crew`) as one datapoint per run.
- **Quality** — reuses the Phase-3 bars verbatim: faithfulness ≥ 0.95
  and citation-correctness ≥ 0.95 (`ComplianceAssistant/Quality`,
  produced by the eval harness on scored runs).
- **Availability** — run-success-rate: the fraction of kicked-off runs
  that complete without an unhandled error.

The `comparator` column is `gt`/`gte`/`lt`/`lte` and maps to the
CloudWatch comparison operator; `period_s` and `eval_periods` define
the alarm window; `statistic` is the CloudWatch statistic (`p50`/`p95`
percentile, or `Average`).

## SLO contract (machine-parsed)

| slo_id | description | namespace | metric | statistic | period_s | eval_periods | comparator | threshold | error_budget_30d |
|--------|-------------|-----------|--------|-----------|----------|--------------|------------|-----------|------------------|
| researcher_latency_p50 | Researcher stage latency p50 (s) | ComplianceAssistant/Crew | ResearcherLatencySeconds | p50 | 300 | 1 | gt | 120 | 5% of runs may exceed |
| researcher_latency_p95 | Researcher stage latency p95 (s) | ComplianceAssistant/Crew | ResearcherLatencySeconds | p95 | 300 | 1 | gt | 300 | 5% of runs may exceed |
| writer_latency_p50 | Writer stage latency p50 (s) | ComplianceAssistant/Crew | WriterLatencySeconds | p50 | 300 | 1 | gt | 90 | 5% of runs may exceed |
| writer_latency_p95 | Writer stage latency p95 (s) | ComplianceAssistant/Crew | WriterLatencySeconds | p95 | 300 | 1 | gt | 240 | 5% of runs may exceed |
| designer_latency_p50 | Designer stage latency p50 (s) | ComplianceAssistant/Crew | DesignerLatencySeconds | p50 | 300 | 1 | gt | 90 | 5% of runs may exceed |
| designer_latency_p95 | Designer stage latency p95 (s) | ComplianceAssistant/Crew | DesignerLatencySeconds | p95 | 300 | 1 | gt | 240 | 5% of runs may exceed |
| end_to_end_latency_p50 | End-to-end run latency p50 (s) | ComplianceAssistant/Crew | RunLatencySeconds | p50 | 300 | 1 | gt | 300 | 5% of runs may exceed |
| end_to_end_latency_p95 | End-to-end run latency p95 (s) | ComplianceAssistant/Crew | RunLatencySeconds | p95 | 300 | 1 | gt | 780 | 5% of runs may exceed |
| quality_faithfulness | Generation faithfulness (reuses the Phase-3 bar) | ComplianceAssistant/Quality | Faithfulness | Average | 86400 | 1 | lt | 0.95 | 0 breaching evaluation windows |
| quality_citation_correctness | Citation correctness (reuses the Phase-3 bar) | ComplianceAssistant/Quality | CitationCorrectness | Average | 86400 | 1 | lt | 0.95 | 0 breaching evaluation windows |
| run_success_rate | Run-success-rate availability (%) | ComplianceAssistant/Crew | RunSuccessRate | Average | 86400 | 1 | lt | 99.0 | 1% of runs (≈7.2h-equivalent of failed runs) |

## Operating the SLOs

Update an SLO by editing its row here; the alarm and its threshold
change on the next `cdk deploy` of `ComplianceObservabilityStack`, and
`infra/tests/test_observability_stack.py` enforces that the deployed
alarms match this table exactly (count, metric binding, and threshold).
Adding or removing a row changes the alarm count; the test will fail
until the synthesized stack matches, by construction.
