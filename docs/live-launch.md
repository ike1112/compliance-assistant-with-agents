# Live launch protocol

The billable, operator-gated path: deploy the stack to real AWS, prove it
works end to end, capture evidence, and tear it down. Nothing in this document
is part of CI.

The exact deploy commands live in [`../infra/README.md`](../infra/README.md).
This file is the proof sequence and evidence checklist.

## Before you start

- AWS credentials for the deploy account and region named in the infra runbook
- Bedrock model access enabled for the embedding and inference models
- Docker running for the `linux/arm64` runtime image
- A clean checkout with the offline gates already green
- An operator email ready to subscribe to the shared SNS alarm topic

## Required proof sequence

Run these in order. Do not skip ahead.

1. **Offline gates green.** Run synth, pytest, the offline eval gate, and
   cfn-lint. If any fail, stop.
2. **Bootstrap if needed.** Run the one-time `cdk bootstrap`.
3. **Deploy infra stacks.** Deploy `ComplianceObservabilityStack`,
   `ComplianceKbStack`, `ComplianceAgentStack`, and
   `ComplianceRuntimeEcrStack`.
4. **Subscribe alarm email.** Confirm the shared SNS topic has the operator
   email subscription you expect.
5. **Push runtime image.** Build and push the `linux/arm64` image.
6. **Deploy runtime stack.** Deploy `ComplianceRuntimeStack` against the pushed
   tag.
7. **Verify ingestion.** Upload a sample regulatory PDF. Confirm the S3 event
   triggers the ingest Lambda and the Bedrock ingestion job completes. If it
   fails, confirm the EventBridge/SNS path and Lambda/DLQ alarms notify.
8. **Run one grounded report.** Execute a topic that the corpus covers and
   confirm `1-requirements.md`, `2-report.md`, and `3-solution.md` land under
   `reports/{run_id}/`.
9. **Run one correct negative.** Execute a topic outside the corpus and confirm
   the run succeeds with `1-requirements.md` only.
10. **Run live conformance.** Execute
    `PYTHONPATH=src python -m tests.evals.harness.live_agent` and require the
    resulting `tests/evals/live_report.json` to pass.
11. **Confirm observability receipt.** Verify at least one
    `ComplianceAssistant/Crew` metric datapoint appears in CloudWatch from the
    deployed run and that the dashboard/alarm set renders as expected.
12. **Capture evidence.** Save the artifacts below before teardown.

## Evidence to capture

- green synth, pytest, offline eval, and cfn-lint outputs
- a screenshot of the SNS subscription confirmation and CloudWatch alarm list
- ingestion success, or if you force a failure, one delivered failure
  notification
- one grounded run artifact set and one correct negative artifact set
- `tests/evals/live_report.json`
- one CloudWatch metric receipt for `ComplianceAssistant/Crew`
- one dashboard screenshot showing the deployed metric namespace

## Truth in wording

Before this sequence is completed, describe the repo as:

`verified in code and tests, not yet proven in production`

After this sequence is completed and the evidence is captured, you can describe
the hardened path as deployed and validated.

## Zombie KB cleanup

After the hardened proof run succeeds, clean up the old click-ops zombie
knowledge base by following AWS's documented remediation:

1. Set the old data source deletion policy to `RETAIN`.
2. Retry the delete for the zombie knowledge base.
3. Record the cleanup result in the launch notes.

This is an operator runbook step, not an application code path.

## Teardown

Destroy the stacks when you are done. The retained evidence buckets remain
manual cleanup by design. Tear down promptly; Aurora storage, ingestion,
embeddings, and inference all bill while deployed.
