# Architecture diagram — review log

Records why `compliance-assistant-v12.drawio` (rendered to
`compliance-assistant-v12.png`) looks the way it does. The diagram was built
with a draft-then-review loop: an initial draft, then rounds of multi-reviewer
critique (a structural pass, a visual pass, and an independent model) until
accuracy and layout converged, followed by owner-driven style iterations.
Intermediate version files were consolidated into the final v12; this log
preserves the decision trail.

## Style reference

Modeled on the AWS reference-architecture style in
[`references/`](./references/) (left-to-right flow bands, a storage row, and a
right-side numbered narrative), matching the sibling trip-tracker diagram.

## Convergence on accuracy + layout

- Early drafts grouped nodes by CDK stack, which read as a zigzag. Rebuilt into
  three horizontal flow bands — request path, ingestion path, observability —
  so the diagram reads left-to-right by lifecycle, not by stack.
- Numbered step markers (1–10) were anchored to their edges (not free-floating
  circles) so they do not drift when nodes move. Several early collisions (a
  marker overlapping the agent caption, a guardrail edge crossing a label) were
  fixed by rerouting edges into clean vertical lanes.
- Added a right-side numbered walkthrough column and a colored edge legend
  (request / ingestion / observability / encryption / utility) to match the
  reference's narrative style.

## Implementation-accuracy corrections

A review against the code corrected five claims so the diagram matches the
as-built system. The same corrections were later applied to the prose docs
(see [`../analysis/2026-06-05-docs-audit-remediation.md`](../analysis/2026-06-05-docs-audit-remediation.md), findings F1/F2):

- The report flow writes three stage files (`output/1-requirements.md`,
  `2-report.md`, `3-solution.md`), all uploaded to `reports/{run_id}/` — not a
  single report file.
- `citations.py` is eval/offline only, not wired into the runtime crew; the
  report carries inline source references from the agent trace.
- The Guardrail is attached to the Bedrock Agent (not a post-knowledge-base
  hop).
- There is no "AgentCore Observability" resource; the runtime writes container
  logs to CloudWatch (`/aws/bedrock-agentcore/runtimes/*`).
- The report and solution stages are conditional and skip when research finds
  no grounded source.

## Reformat (current version)

A manual reorganization left the cloud boundary and the request band stranded,
with the band painting over the request-row icons (a document-order/z-index
issue). The layout was repaired: cloud and bands realigned and stacked, the
request band moved behind its nodes, the report-bucket and report-key nodes
returned to the request band, and the "deploy before" edge rerouted off the
storage icons. Verified by rendering at scale 2 and inspecting every region.

## Status

`compliance-assistant-v12` is the current diagram. The numbered request flow
closes back to the operator (invoke → research → retrieve → report → download).
No internal audit-catalog IDs (R-\*) appear on the diagram by design; the
resource catalog lives in the WA-Lens audit instead.

## 2026-06-12 refresh

- Updated the tracked `.drawio` source to reflect the current launch-proof and
  alerting posture without changing the core request-path layout.
- Added the shared SNS operator-notification topic in the observability band.
- Added the ingest DLQ / failure path so the diagram matches the KB stack's
  async retry and alarm wiring.
- Added the post-deploy `live_agent` conformance harness to the CI/proof area,
  explicitly labeled as launch proof rather than merge CI.
- Clarified the report bucket label to show both `reports/` artifacts and
  durable `runs/` manifests.
