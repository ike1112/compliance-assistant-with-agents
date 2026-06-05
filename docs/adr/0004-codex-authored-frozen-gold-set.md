# 0004 — The RAG eval gold set is authored by a separate model and frozen against the judged diff

**Status:** Accepted

## Context

A RAG eval is only trustworthy if the answer key is independent of the system
under test. If the same process that builds and changes the crew also writes
the gold set, the evaluation is circular — the system can be "improved" by
quietly relaxing the gold set it is graded against.

## Decision

The eval gold set (positive items with expected source-passage locators, plus
out-of-corpus negatives) is authored by a separate model (codex) and frozen.
A test asserts the judged diff did not modify anything under
`tests/evals/gold/`: the check is bidirectional — the working tree is git-clean
under that path **and** every gold file is byte-identical to its committed
blob. `PROVENANCE.md` records the authorship rule.

## Consequences

- The system cannot grade itself against a gold set it just edited.
- Legitimate gold changes are possible but require an explicit, separate,
  reviewable commit — never bundled into a change being judged.
- Provenance is auditable from the repo.

## Alternatives considered

- **Self-authored gold set** — rejected: circular; the eval would measure
  agreement with itself.
- **No gold set** — rejected: retrieval/generation quality would be unmeasured
  and regressions would ship silently.

## Evidence

`tests/evals/gold/PROVENANCE.md`, `tests/evals/test_gold_frozen.py`.
