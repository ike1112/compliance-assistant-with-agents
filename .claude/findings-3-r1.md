# Phase 3 Gate — Round 1 Findings (consolidated, FAIL)

Frozen base `2dd18538b0777c6a3eb8d2d6b1dee659f90aa94c..HEAD`. Panel:
A codex REVISE, B PASS, C security PASS, D code-reviewer REVISE,
F test-engineer ADVISORY. Fix the ROOT CAUSE of each blocking item.
**Do NOT weaken tests, thresholds, fixtures, or the frozen gold set**
(`tests/evals/gold/` is provenance-frozen — never edit/move/normalize
it). Re-recording fixtures is allowed only via the live recorder
(`EVALS_LIVE=1`); the gate must stay offline and deterministic.

## BLOCKERS (must all be resolved)

### B1 — Bind generation scoring to the RECOMPUTED retriever (codex F1)
`report._generation()` scores `fx["retrieved_context"]` after only an
internal self-hash check. A handcrafted fixture with gold-rich context,
a self-consistent `retrieved_context_sha256`, a perfect
`system_answer`, and `judge_raw_response={"faithfulness":1,...}` passes.
Generation is not bound to the deterministic BM25 output → the core
circularity is not closed.
**Fix:** in `_generation`, for each (item, deploy-equivalent config)
recompute `BM25Index(chunk_corpus(...)).search(question, k)` and assert
`fx["retrieved_context"]` is exactly `[{"chunk_id","text"}...]` of that
recomputed top-k; also assert `fx["item_id"]`, `fx["question"]`,
`fx["kind"]`, and `fx["chunking_config"]` match the path/config/gold
item. Honest recorder fixtures (built from the same `search`) match;
forged ones cannot.

### B2 — Gate pass/fail must rest on DETERMINISTIC metrics; judge is
evidence (codex F2)
`faithfulness`/`hallucination` are parsed from the committed
`judge_raw_response`; offline cannot prove an LLM produced it. The
SHA-binding only proves the fixture names the contract.
**Fix:** make the binding faithfulness criterion the **recomputed
deterministic groundedness** (answer-vs-recomputed-context lexical
grounding) — the gate asserts mean deterministic groundedness ≥ 0.95
AND `not any_forged` AND requires the recorded judge faithfulness ≥ 0.95
only as a corroborating cross-check (a fabricated judge JSON cannot pass
unless the answer is deterministically grounded in the recomputed
retrieved context, per B1). State the residual trust explicitly in
`docs/evals.md` and the rubric (offline cannot attest an LLM judge call;
the deterministic floor is what gates).

### B3 — Missing-fixture hard-fail for ALL deploy-equivalent configs
(code-reviewer D-B1)
`_generation()` returns `None` on a missing fixture; `build_report()`
filters `None` out of `eligible` and still finds a winner. Deleting a
non-winning deploy-equivalent config's fixtures still passes, and a
fixture-less config still counts toward "≥2 deploy-equivalent". This is
an anti-gaming hole and contradicts the plan's Edge Case "Missing
fixture for ANY scored (item × deploy-equivalent config) → hard fail".
**Fix:** `_generation` raises `AssertionError` on a missing/!=expected
fixture for a **deploy-equivalent** config (return `None` ONLY for the
advisory HIERARCHICAL config, which has no fixtures by design); the gate
asserts every deploy-equivalent config in `SCORED_CONFIGS` has
`generation is not None`.

### B4 — Silent `render_citations` failure must be loud under the gate
(code-reviewer D-B2)
A swallowed `except Exception` in `citations.py` turns any transient
into a silent `citation_correct=0.0`. (The observed first-run collapse
was the round-1 process artifact of running the mutation leg
concurrently with a suite-executing leg — see "Process" below — but the
silent-zero remains a real robustness hole.)
**Fix:** in `generation_metrics.citation_correct`, if `fx["trace"]` has
references but `render_citations(fx["trace"])` returns the no-sources
placeholder, FAIL loudly (raise `AssertionError`) rather than scoring a
silent 0.0. Add a determinism stress test: `build_report()` ≥10 times,
assert byte-identical canonical JSON each run.

## MAJORS (must all be resolved)

### M1 — Strengthen citation-correctness semantics (codex F3)
With B1's binding, require the trace references to be derived from the
recomputed `retrieved_context`; require at least one cited source doc to
equal a gold passage's `doc_id` for that positive; match the gold
passage text presence in the cited reference, not "any early >4-char
word".

### M2 — Tighten requirement matching; fix the substring weakness
(codex F4, code-reviewer MINOR)
`task_metrics`: `num in answer` is unbounded — `11.2.7`/`1.2.70`
satisfy `1.2.7`, and the context word may match in the Sources block.
**Fix:** score the PROSE only (strip the `## Sources` block); match the
canonical dotted number with a bounded pattern
`(?<!\d)<escaped_num>(?!\d|\.\d)` adjacent to `Req|Requirement` (still
accepting both spellings), and add negative tests (`1.2.7` vs `11.2.7`
vs `1.2.70`). The frozen gold and the ≥0.90 bar are unchanged — this is
a correctness tightening, not a weakening.

### M3 — Full report.json recompute parity, not just winner (codex F5)
`test_chunking_decision` compares only `winner`. A stale/hand-edited
`tests/evals/report.json` with false per-config metrics still passes.
**Fix:** assert the FULL committed `report.json` equals
`R.build_report()` under canonical JSON (every config's metrics), and
assert `infra/cdk.json` equals the RECOMPUTED winner directly.

### M4 — Robust offline enforcement for the whole gate (codex F6,
security C-MINOR)
Only `socket.socket` is patched, only in `test_gate.py`.
**Fix:** add `tests/evals/conftest.py` with an autouse fixture for all
`@pytest.mark.gate` tests blocking `socket.socket`,
`socket.create_connection`, `socket.getaddrinfo`, and `subprocess`
(allow only local `git` in the provenance test). Message must match the
guarantee.

## MINOR / NIT (address the cheap, correctness-relevant ones)

- Single source of truth for configs: derive the deploy-equivalent
  entries of `report.SCORED_CONFIGS` from `recorder.DEPLOY_CONFIGS`
  (or a shared constant) so recorder and report cannot drift
  (security/code MINOR; reinforces B1/B3).
- `fixtures_io`: cap fixture size before `json.loads` (security MINOR).
- `recorder._codex_bin`: refuse a non-absolute/missing binary instead of
  bare `"codex"`; resolve inside `record()` not at import (security
  MINOR).
- `recorder._head()`: `check=True`, assert non-empty `recorded_at_commit`
  (security NIT).
- Hoist the function-local `from ...chunking import STRATEGIES` in
  `report.py` (code NIT).
- `kb_stack.py`: reject a non-`FIXED_SIZE` `chunkingStrategy` context
  value (raise) + an infra test, so the deploy code enforces the
  deploy-equivalence invariant the harness assumes (codex F7 MINOR).

## ADVISORY (test-engineer, non-blocking — implement the cheap wins)

- The leg-F "bug headline" (s3 fallback / `break`) was a FALSE POSITIVE:
  `citations.py` is unchanged on HEAD, `test_citations.py` is 19/19
  green and mutation 0.839 against the committed file; the agent ran the
  suite while the concurrent mutation leg had the file transiently
  mutated. No `citations.py` change is warranted or permitted here.
- Add an end-to-end adversarial-fixture test that drives
  `build_report()` to `winner is None` (fabricating answer / forged
  judge JSON / tampered Sources / context != recomputed).
- Add a dishonest-negative fixture-level case exercising
  `not_found_honesty < 1.0` end-to-end.
- Add a CRLF-corpus relevance test (substring invariant under CRLF).

## Process (orchestrator, not a code change)

The round-1 panel ran leg B (mutation, which rewrites `citations.py`
in place) concurrently with suite-executing legs (D code-reviewer first
run, F test-engineer), producing D-B2's one-off non-determinism and
F's false bug. The round-2 panel MUST run the mutation leg in isolation
(no other suite-executing leg active) and only then dispatch the
reviewer legs.
