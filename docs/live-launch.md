# Live launch protocol

The billable, operator-gated path: deploy the stack to real AWS, prove it
works end to end, capture evidence, and tear it down. Everything here is a
**HUMAN-GATE** — the autonomous loop never runs it, because it provisions
Bedrock + Aurora resources that cost money (see the *Engineering posture*
section of [`../README.md`](../README.md)).

The **exact commands** live in the deploy runbook in
[`../infra/README.md`](../infra/README.md). This document is the ordered
protocol, the gates between steps, and the evidence to capture — not a second
copy of the commands (a copy would drift).

## Before you start

- AWS credentials for the deploy account and region (the concrete account/
  region are in [`../infra/README.md`](../infra/README.md)).
- Bedrock **model access enabled** for the embedding and inference models named
  in the infra runbook (`amazon.titan-embed-text-v2:0`,
  `amazon.nova-pro-v1:0`).
- Docker running (the runtime image is `linux/arm64`).
- A clean checkout: the offline gates below should be green *before* you spend
  anything.

## Launch sequence

Each step gates the next. Do not skip ahead.

1. **Offline gates green (free).** Run the quick-start from
   [`../README.md`](../README.md): `cdk synth --all -q`, the full test suite,
   and the RAG eval gate. If any of these fail, stop — do not deploy.
2. **One-time bootstrap.** `cdk bootstrap` for the deploy account/region (infra
   runbook).
3. **Pre-deploy compliance.** Synthesize and run cfn-guard on the templates;
   resolve or justify findings before deploying. The expected posture
   (COMPLIANT + the documented accepted exceptions) is in the infra runbook.
4. **Deploy the infrastructure stacks** — `ComplianceKbStack`,
   `ComplianceAgentStack`, `ComplianceRuntimeEcrStack`. **Never** `deploy --all`:
   that would pull in the runtime stack and bypass its required gate (next
   step).
5. **RAG eval gate — required before the runtime.** `pytest tests/evals -m gate`
   MUST be green on the deploying commit before the runtime image is built or
   the runtime stack is deployed. The runtime hosts the same crew the eval
   harness scores; shipping ungated grounding/citation quality is not
   permitted.
6. **Build + push the `linux/arm64` crew image** to the ECR repo created in
   step 4 (deterministic repo name; see the infra runbook).
7. **Deploy `ComplianceRuntimeStack`** against the pushed image tag. The ECR
   and agent stacks must already exist (the agent stack publishes the agent ids
   to SSM that the crew reads at container start); `app.py` encodes both
   orderings.

## Verify end to end

1. **Ingestion.** Upload a sample regulatory PDF to the corpus bucket; confirm
   the `OBJECT_CREATED` event triggers the ingest Lambda and a Knowledge Base
   ingestion job runs to completion.
2. **A grounded run.** `crewai run` (or `POST /invocations` on the hosted
   runtime, then poll `/ping` until `Healthy`). Confirm the report artifacts
   land in the versioned report bucket under `reports/{run_id}/`:
   `1-requirements.md`, `2-report.md` (each requirement section carrying an
   inline source reference), and `3-solution.md`.
3. **A not-found run (correct negative).** Run a topic the corpus does not
   cover. The expected, correct behavior is that the run uploads
   `1-requirements.md` and reports success **without** `2-report.md` /
   `3-solution.md` — the conditional stages skip rather than fabricate (see
   [ADR 0005](adr/0005-conditional-report-stages.md)).
4. **Observability.** Confirm the CloudWatch dashboard renders and one alarm
   exists per row of [`SLOs.md`](SLOs.md); confirm model-invocation logging is
   on with raw-content delivery disabled.

## Evidence to capture

For a launch record / portfolio artifact, capture:

- the `cdk synth --all` manifest and the cfn-guard COMPLIANT output;
- the green RAG eval gate run (and `tests/evals/report.md`);
- the grounded run's `2-report.md` from the report bucket (with its inline
  source references) **and** the not-found run showing the skipped stages;
- a screenshot of the CloudWatch dashboard + the SLO alarm list.

## Teardown

`cdk destroy --all`. The corpus and access-log buckets are `RETAIN` by design
(evidence preservation) — empty/delete them by hand only if you truly intend
to. **Cost note:** while deployed, Aurora storage + active ACUs, KB ingestion,
embeddings, and inference all bill; 0-ACU idle keeps the floor low but not
zero, so tear down when the launch/evidence run is complete.
