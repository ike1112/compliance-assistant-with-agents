# 0005 — Report and solution stages skip when research finds no grounded source

**Status:** Accepted

## Context

The crew is a sequential pipeline: `regulation_researcher` →
`report_writer` → `solution_designer`. If the researcher finds nothing in the
knowledge base, a naive pipeline would still run the writer and designer, which
could fabricate a plausible-looking compliance report from the model's prior
knowledge. For a compliance tool, a confident but ungrounded report is worse
than no report.

## Decision

The reporting and solution tasks are `ConditionalTask`s gated on a
`_has_grounded_findings` predicate. The predicate returns false when the
researcher's output is empty or is the exact "not found in knowledge base"
reply, in which case both downstream stages skip. The task prompts reinforce
this: given empty or not-found input, the response must be exactly
"Not found in knowledge base," with no content written from prior knowledge.

## Consequences

- No fabricated requirements: a report is produced only when there is grounded
  source material to base it on.
- A run may legitimately produce just the research stage output.
- Honesty over completeness — the tool says "not found" rather than inventing
  coverage.

## Alternatives considered

- **Always run all three stages** — rejected: invites hallucinated compliance
  guidance when retrieval is empty.

## Evidence

`src/compliance_assistant/crew.py` (`_has_grounded_findings`, the two
`ConditionalTask`s), `src/compliance_assistant/config/tasks.yaml` (the
explicit "Not found in knowledge base" early-exit prompts).
