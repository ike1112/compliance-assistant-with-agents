# Implementation Report — RAG Evaluation Harness

**Plan**: `.claude/PRPs/plans/phase-rag-evaluation-harness.plan.md`
**Completed**: 2026-05-17T00:09:49Z
**Iterations**: 1
**Build commit**: `67aec7a` (base `2dd1853`)

## Summary

Built an offline-deterministic, non-circular RAG evaluation harness under
`tests/evals/` that scores the grounding layer against the frozen,
codex-authored gold set. Deterministic BM25 retrieval over the frozen
corpus (pinned k=5); an LLM (codex CLI) answers strictly from retrieved
context; a committed LLM-as-judge scores faithfulness. Raw artifacts are
recorded once (`-m live`, resumable); the gate RECOMPUTES every
deterministic metric and hash-binds each fixture to the committed judge
prompt/rubric and to the deterministic retriever, with a groundedness
cross-check on the judge. The frozen gold tree was never modified.

## Tasks Completed

1–11 all done: pytest markers; `goldset`/`chunking`/`retriever`/
`retrieval_metrics`/`fixtures_io`/`generation_metrics`/`task_metrics`/
`recorder`/`report`; committed judge prompt+rubric; hardened
`tests/test_citations.py`; unit + gate + decision + frozen + live test
suites; `docs/evals.md`; `report.json`/`report.md`; `infra/cdk.json`
winner write.

## Validation Results

| Check | Result |
|-------|--------|
| `pytest tests/evals -m gate` (offline, deterministic) | PASS 8/8 |
| Full regression `pytest tests infra/tests` (not gate/live) | PASS 184 |
| Gold-frozen provenance guard | PASS (gold byte-identical, no adds) |
| Mutation leg (`citations.py` via `test_citations.py`) | PASS 0.839 ≥ 0.80 |
| `infra/cdk.json` == `report.json` winner | MATCH (FIXED_SIZE 512/20) |
| `docs/` not staged | OK (gitignored) |

### Metrics (winning deployable config FIXED_SIZE 512/20)
- context-recall 1.000, context-precision 0.960, MRR 0.972
- faithfulness 1.000, hallucination 0.000, citation-correctness 1.000
- not-found-honesty 1.000, requirement-coverage 1.000, no forged fixtures

### Chunking decision
Scored FIXED_SIZE-512-20 (deploy), FIXED_SIZE-256-15 (deploy),
HIERARCHICAL-250-20 (advisory/non-deployable). Winner FIXED_SIZE 512/20
(max recall, tie-break MRR/precision). HIERARCHICAL excluded from the
winner because `infra/stacks/kb_stack.py` emits only fixed-size chunking.

## Deviations from Plan

- No deployed Bedrock KB in this environment (Phase 1 HUMAN-GATE): the
  recorder uses the authenticated `codex` CLI as answerer + judge over
  the harness's deterministic retrieval. Documented in `docs/evals.md`.
  Anti-gaming holds because the gate recomputes deterministic metrics and
  hash-binds fixtures to the frozen-corpus retriever and committed judge
  assets.
- `requirement_coverage` matches a cited requirement by its NUMBER (plus
  a PCI/requirement context word) so the gold's `Req` abbreviation and
  the corpus-grounded `Requirement` wording are recognised as the same
  citation. Root-cause fix; the frozen gold and the ≥0.90 bar were not
  changed.

## Learnings

- Windows: a `codex` subprocess needs `codex.cmd` (resolve via
  `shutil.which`); `codex exec -o <file>`/`--output-schema` give clean,
  parseable model I/O.
- Frozen-gold reads must be bytes→utf-8 with no newline translation or
  the exact-substring relevance invariant breaks on a CRLF checkout.
- The mutation leg runs only `tests/test_citations.py`; pinning each
  truncation/dedup/fallback/`_iter_references`-guard behaviour with
  exact-value asserts reached 0.839.
