# 0007 — A contested quality-gate FAIL may be closed by a recorded owner-acceptance override

**Status:** Accepted

## Context

Every phase boundary is gated by a six-leg review panel (an adversarial leg, a
security leg, a code-reviewer leg, a test-engineer leg, a regression leg, and a
mutation/coverage floor). A gate that can never be overridden turns a single
contested finding into a hard stop — even when an independent majority of the
panel disagrees with it. A real production practice needs a defensible way to
adjudicate that case without erasing the dissent.

## Decision

A contested gate FAIL may be closed by an **explicit, recorded
owner-acceptance override**, but only when the override is:

- **Traceable** — the gate state, both sets of findings, and the written
  rationale all live in the repo, in one commit;
- **Bounded** — the override applies to that one phase; it adds no new
  precedent rule;
- **Adjudicated** — the other legs independently refuted the dissenting finding
  before acceptance;
- **Preserved as dissent** — the dissenting record is kept, not deleted.

The gate's automatic PASS token is **not** minted in this path: the machine
state stays `passed=false`, and the human override is what closes the phase.

## Consequences

- The audit phase closed this way: five legs refuted the dissenting adversarial
  finding; the owner accepted on the evidence with a written defense.
- The gate's recorded state remains honest (`passed=false`); the override is
  visible, not hidden.
- The mechanism is auditable and sets no automatic precedent.

## Alternatives considered

- **Force the gate to PASS** — rejected: erases the dissent and corrupts the
  gate's record.
- **Block indefinitely on a refuted finding** — rejected: lets a single
  false-positive finding override an independent majority forever.

## Evidence

`ARCHITECTURE.md` §5, `.claude/review-gate.verdicts.json` (preserved dissent),
the PRD Progress Log entry recording the override rationale.
