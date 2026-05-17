# Feature: RAG Evaluation Harness (interview-grade strict)

> **Revision note (post adversarial review).** Hardened to resolve codex
> BLOCKER1/2 + MAJOR3-7 + MINOR8 and code-reviewer M1 + MINORs:
> raw-artifact (non-circular) fixtures with deterministic recompute and
> hash-binding; deploy-equivalence constraint on the chunking winner;
> pinned metric contract (`k`, denominators, tie-break);
> deterministic citation-correctness on `render_citations`; correct CRLF
> handling; bidirectional gold-frozen guard; per-(item×config) fixtures;
> `report.json` machine contract. The Validation section is byte-identical
> to Phase 3's PRD `CHECK:` items and was not touched by this revision.

## Summary

Build an offline-deterministic RAG evaluation harness that scores the
compliance assistant's grounding layer against the **frozen, codex-authored
gold set** at `tests/evals/gold/`. It measures retrieval quality
(context-recall / context-precision / MRR), generation quality
(faithfulness / citation-correctness / hallucination via a committed
LLM-as-judge whose raw responses are recorded and re-derived
deterministically), and task-level honesty (not-found-honesty /
requirement-coverage); it scores ≥2 **deploy-equivalent** FIXED_SIZE
chunking configs (plus HIERARCHICAL as advisory-only), writes
`tests/evals/report.json` + `tests/evals/report.md`, and propagates the
winning **deployable** chunking values into `infra/cdk.json` with a test
asserting equality. The `-m gate` suite runs deterministically offline by
**recomputing every metric from raw recorded artifacts** (no Bedrock
spend, no trusted precomputed scores); `-m live` (opt-in) is the only
writer of those artifacts. The harness **conforms to
`tests/evals/gold/SCHEMA.md` and never creates, modifies, moves,
normalizes, or writes anything under `tests/evals/gold/`** — that tree is
provenance-frozen ground truth and must not appear in this build's judged
diff.

## User Story

As the owner/reviewer of the compliance assistant
I want every grounding decision measured against a frozen gold set with
interview-grade thresholds and a reproducible, non-circular offline gate
So that the RAG layer's quality is demonstrably defensible and the real
*deployable* chunking value is decided by evidence, not guesswork.

## Problem Statement

The grounding layer has no evals: chunking is an unjustified guess
(`FIXED_SIZE/512/20%` in `infra/cdk.json`), citation fidelity is
unmeasured, and there is no regression gate on retrieval/generation
quality. Testable: there is no command that, run offline with no AWS
spend, deterministically fails when retrieval recall, answer
faithfulness, citation correctness, or not-found honesty regress below
stated bars — and that cannot be passed by committing self-serving
precomputed scores.

## Solution Statement

A pure-Python, dependency-light harness package under `tests/evals/`
(NEVER under `tests/evals/gold/`):

1. **Loader** (`goldset.py`) reads the frozen gold set with **binary
   reads + explicit UTF-8 decode, `newline=""`** (no newline
   translation), validates SCHEMA conformance, and is structurally
   read-only.
2. **Chunkers** (`chunking.py`) split corpus docs under multiple
   strategies. Only **FIXED_SIZE** parameterizations are
   *deploy-equivalent* (the only strategy `kb_stack.py` emits);
   HIERARCHICAL is computed for comparison but flagged
   **advisory / non-deployable**.
3. **Deterministic retriever** (`retriever.py`): hand-rolled BM25, fixed
   constants, **pinned `k`**, deterministic chunk-id tie-break. No
   Bedrock. Fully reproducible from the frozen corpus alone.
4. **Retrieval metrics** (`retrieval_metrics.py`) with a **pinned metric
   contract** (definitions + denominators below), relevance = SCHEMA
   substring-coverage.
5. **Recorded raw artifacts** (`fixtures/`): per **(gold-item ×
   deploy-equivalent config)** and per negative, a JSON record holding
   raw system answer, raw retrieved context (+ its content hash), raw
   trace, raw judge request/response, `prompt_sha256`, `rubric_sha256`,
   `model_id`, `decoding_params`, `harness_version`,
   `recorded_at_commit`. **No precomputed metric scores are trusted.**
6. **Gate recompute** (`-m gate`): retrieval recomputed live-offline from
   the frozen corpus; citation-correctness, requirement-coverage,
   not-found-honesty recomputed deterministically from the recorded
   answer/trace; faithfulness/hallucination read from the recorded raw
   judge response **and** cross-checked by a deterministic groundedness
   lower-bound. The gate **hard-fails** if: a required raw field is
   missing; `prompt_sha256`/`rubric_sha256` ≠ committed judge files; the
   recorded `retrieved_context` hash ≠ the current deterministic
   retriever's output for that (question, config); or any fixture is
   missing for a scored (item, config) pair.
7. **Decision driver** (`report.py`): scores all configs, writes
   `tests/evals/report.json` (machine contract) and a `report.md`
   rendered *from* it; selection rule applied **only over
   deploy-equivalent configs**; writes the winning deployable values into
   `infra/cdk.json`; a test asserts `cdk.json` == `report.json` winner.
8. `docs/evals.md` documents metrics, thresholds, judge model, run steps.

## Metadata

| Field            | Value |
| ---------------- | ----- |
| Type             | NEW_CAPABILITY |
| Complexity       | HIGH |
| Systems Affected | `tests/evals/`, `infra/cdk.json`, `pyproject.toml`, `tests/test_citations.py`, `docs/evals.md` |
| Dependencies     | stdlib only for the harness; `pytest>=8` (present). NO new runtime deps; NO Bedrock at gate time. |
| Estimated Tasks  | 11 |

---

## Pinned Metric Contract (fixed BEFORE implementation — builder may not change after seeing scores; only the owner may move a bar)

- **k = 5.** The same `k` is used for retrieval scoring, for the context
  handed to generation, and for the report. Changing `k` is a bar move
  (owner-only); the builder may not re-tune it post-hoc.
- **Relevance** (per SCHEMA §`corpus_index.jsonl`): a retrieved chunk is
  relevant to a positive iff it contains, or is contained by, at least
  one of that item's gold-passage `text` values, comparing exact
  characters from the corpus (no normalization).
- **context-recall** (mean over positives) = (# of the item's
  `gold_passage_ids` whose `text` is covered by ≥1 of the top-`k`
  retrieved chunks) / (# of the item's `gold_passage_ids`).
- **context-precision** (mean over positives) = Ragas-style rank-aware
  average precision: `Σ_{i=1..k} [precision@i · rel_i] / (#gold passages
  for the item)`, capped at 1.0, where `rel_i` is 1 iff the chunk at
  rank `i` is relevant. (A retriever that ranks the relevant chunk first
  yields 1.0; this is the standard, feasible definition — not raw
  precision@k.)
- **MRR** (mean over positives) = mean of `1 / rank_of_first_relevant`
  within top-`k`, else 0.
- **Tie-break**: equal BM25 scores ordered by `chunk_id` ascending
  (deterministic; mirrors the `seen.sort()` determinism rule in
  `citations.py`).
- **faithfulness / hallucination-rate**: from the recorded raw judge
  response parsed per the committed rubric; **plus** a deterministic
  groundedness lower-bound (sentence-level lexical overlap of the
  answer's claims vs the top-`k` retrieved context). The gate fails if
  the judge reports high faithfulness while deterministic groundedness is
  implausibly low (catches a forged judge response). Recorded LLM scores
  are **evidence cross-checked deterministically**, never an unchecked
  oracle.
- **citation-correctness** (deterministic): parse the recorded answer's
  `## Sources` block; render the expected block from the recorded trace
  via `compliance_assistant.citations.render_citations`; an answer is
  citation-correct iff its cited entries match the rendered entries
  (normalized) **and** each cited source's text overlaps the item's
  retrieved/gold context. LLM judge commentary is secondary only.
- **not-found-honesty** (deterministic, binary, == 1.0): for every
  negative, the recorded answer satisfies the crew's exact predicate
  `answer.strip().lower().startswith("not found in knowledge base")`
  (mirroring `crew.py:_has_grounded_findings`, which also bounds it
  `len < 200`), **and** contains no requirement-looking citation (regex
  for `Req\s*\d`/`Requirement \d`/`PCI DSS`), **and** no non-empty
  unsupported grounded claim. Any single violation → < 1.0 → FAIL.
- **requirement-coverage** (deterministic, mean over `labeled_subset`'s
  `requirement_coverage_ids`) = fraction of the item's
  `expected_requirements` whose canonical id string appears in the
  recorded answer.

---

## UX Design

### Before State
```
┌────────────┐   ┌──────────────────┐   ┌─────────────────┐
│ infra/     │──►│ chunking = guess │──►│ KB ingest (live)│
│ cdk.json   │   │ FIXED_SIZE/512   │   │ no eval, no gate│
└────────────┘   └──────────────────┘   └─────────────────┘
PAIN_POINT: no offline measurement; citation fidelity unverified;
            chunking unjustified; no anti-gaming gate.
```

### After State
```
┌──────────────────────┐   ┌─────────────────────────────────────┐
│ tests/evals/gold/    │   │ tests/evals/ harness                │
│ (FROZEN ground truth)│──►│ loader→chunkers→BM25(k=5)→metrics    │
└──────────────────────┘   │ + recorded RAW artifacts (fixtures) │
                           │ gate RECOMPUTES + hash-binds        │
                           └─────────────────────────────────────┘
                                       │
        ┌──────────────────────────────┼───────────────────────────┐
        ▼                              ▼                            ▼
┌─────────────────┐      ┌──────────────────────────┐   ┌────────────────────┐
│ pytest -m gate  │      │ report.json (machine)    │   │ infra/cdk.json     │
│ offline, no AWS │      │ + report.md (rendered)   │──►│ deployable winner  │
│ recompute+verify│      │ winner ∈ deploy-equiv    │   │ test asserts ==    │
└─────────────────┘      └──────────────────────────┘   └────────────────────┘
VALUE_ADD: reproducible, non-circular, zero-spend gate; the chunking
           decision is evidence-backed AND actually deployable.
```

### Interaction Changes
| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| `pytest tests/evals -m gate` | n/a | offline, recomputed, hash-verified pass/fail | trustworthy gate, no AWS spend, not gameable by committed scores |
| `infra/cdk.json` context | hand-guessed | harness-selected **deployable** winner | evidence-backed AND deploy-correct; test enforces parity |
| `tests/evals/report.json` / `.md` | n/a | machine contract + human render; deploy-equivalence labeled | auditable, binary CDK check |
| `docs/evals.md` | n/a | metrics/thresholds/judge/run docs | reviewer can reproduce |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|----------|------|-------|-----|
| P0 | `tests/evals/gold/SCHEMA.md` | all | The contract. Substring-coverage relevance + not-found definitions are load-bearing. Conform; never edit gold. |
| P0 | `src/compliance_assistant/citations.py` | 1-68 | `render_citations` is the mutation-leg pure-logic target AND the structural basis of deterministic citation-correctness. |
| P0 | `tests/test_citations.py` | 1-51 | Mutation runner executes ONLY this file vs `citations.py` at floor 0.80. |
| P0 | `src/compliance_assistant/crew.py` | 23-34 | `_has_grounded_findings`: the EXACT not-found predicate to mirror (`.lower().startswith("not found in knowledge base")`, `len<200`). |
| P0 | `infra/stacks/kb_stack.py` | 312-345 | Proves only `chunkingStrategy`/`chunkMaxTokens`/`chunkOverlapPercent` are read and ALWAYS emitted as `fixed_size_chunking_configuration` → deploy-equivalence constraint. |
| P1 | `infra/cdk.json` | all | Exact context keys/format/types for the winner write. |
| P1 | `tests/test_startup.py` | all | Project pytest style: stdlib + monkeypatch, deterministic, docstring-first. |
| P2 | `pyproject.toml` | 40-46 | `[tool.pytest.ini_options]`; add `gate`/`live` markers. |
| P2 | `.claude/review-gate.config.json` | phase "3" | `pure_logic_paths=citations.py`; `frozen_fixture_paths` includes `tests/evals/gold/`. |

**External Documentation:** none — stdlib-only, offline. Metric
definitions are pinned above; do not import a RAG-eval library.

---

## Patterns to Mirror

**PURE_DETERMINISTIC (every metric/chunker/retriever module):**
```python
# SOURCE: src/compliance_assistant/citations.py:38-55
seen.sort()                 # input order must never matter
# total functions; no timestamps; no set-iteration ordering
```

**EXACT NOT-FOUND PREDICATE (mirror, do not invent):**
```python
# SOURCE: src/compliance_assistant/crew.py:28-33
text = (getattr(previous_output, "raw", "") or "").strip()
if len(text) < 200 and text.lower().startswith("not found in knowledge base"):
    return False
```

**TEST_STYLE:** `tests/test_citations.py` / `tests/test_startup.py` —
stdlib + `pytest` + `monkeypatch`; explicit value/`match=` asserts; no
network.

**PYTEST CONFIG (extend the existing block):**
```toml
# SOURCE: pyproject.toml:42-43
[tool.pytest.ini_options]
testpaths = ["tests", "infra/tests"]
```

---

## Files to Change

| File | Action | Justification |
|------|--------|---------------|
| `pyproject.toml` | UPDATE | Register `gate`/`live` markers (markers only — not a bar change). |
| `tests/evals/__init__.py` | CREATE | Package marker (sibling of `tests/review_gate`). |
| `tests/evals/harness/__init__.py` | CREATE | Harness package root. |
| `tests/evals/harness/goldset.py` | CREATE | Read-only loader; binary read + utf-8 decode `newline=""`; SCHEMA validate. |
| `tests/evals/harness/chunking.py` | CREATE | FIXED_SIZE (deploy-equivalent) + HIERARCHICAL (advisory). |
| `tests/evals/harness/retriever.py` | CREATE | Deterministic BM25, pinned `k`, chunk-id tie-break. |
| `tests/evals/harness/retrieval_metrics.py` | CREATE | recall/precision/MRR per the pinned contract. |
| `tests/evals/harness/fixtures_io.py` | CREATE | Load/validate raw-artifact fixtures; hash-binding checks; the ONLY writer is the live recorder. |
| `tests/evals/harness/generation_metrics.py` | CREATE | deterministic citation-correctness (uses `render_citations`); faithfulness/hallucination from raw judge response + deterministic groundedness cross-check. |
| `tests/evals/harness/task_metrics.py` | CREATE | not-found-honesty (exact crew predicate) / requirement-coverage. |
| `tests/evals/harness/recorder.py` | CREATE | LIVE-only: runs the real answer+judge path, writes raw-artifact fixtures. Imported nowhere by the gate. |
| `tests/evals/harness/report.py` | CREATE | report.json (contract) + report.md (rendered); deploy-equivalence labelling; selection over deployable configs; cdk.json writer. |
| `tests/evals/judge/judge_prompt.md` | CREATE | Committed judge prompt (hash-bound). |
| `tests/evals/judge/judge_rubric.md` | CREATE | Committed rubric + thresholds (hash-bound). |
| `tests/evals/fixtures/<item>__<config>.json` | CREATE | Recorded RAW artifacts per (gold-item × deploy-equivalent config) + per negative. |
| `tests/evals/fixtures/recording_manifest.json` | CREATE | model id, prompt/rubric hashes, harness version, recorded-at commit; no timestamps. |
| `tests/evals/test_goldset.py` | CREATE | Loader/SCHEMA + CRLF-preservation unit tests. |
| `tests/evals/test_chunking.py` | CREATE | Both strategies deterministic; deploy-equivalence flag correct. |
| `tests/evals/test_retriever.py` | CREATE | BM25 determinism + tie-break + pinned `k`. |
| `tests/evals/test_retrieval_metrics.py` | CREATE | metric math on a tiny hand-built corpus (exact expected values). |
| `tests/evals/test_generation_metrics.py` | CREATE | deterministic citation-correctness + groundedness cross-check. |
| `tests/evals/test_task_metrics.py` | CREATE | not-found-honesty binary; requirement-coverage. |
| `tests/evals/test_gate.py` | CREATE | `-m gate`: recompute all bars; cardinality (≥30/≥8); determinism re-run; offline; hash-binding. |
| `tests/evals/test_live.py` | CREATE | `-m live`: re-records via real model; skipped without `EVALS_LIVE=1`. |
| `tests/evals/test_chunking_decision.py` | CREATE | ≥2 deploy-equivalent configs scored; report.json/md present; `cdk.json` == report.json winner (exact keys + int types). |
| `tests/evals/test_gold_frozen.py` | CREATE | Bidirectional provenance guard (porcelain + ls-tree parity + per-blob byte compare). |
| `tests/test_citations.py` | UPDATE | Strengthen to kill ≥ `mutation_floor` (0.80) of `citations.py` mutants. |
| `infra/cdk.json` | UPDATE | Written with the winning DEPLOYABLE (FIXED_SIZE) values only. |
| `docs/evals.md` | CREATE | Metrics/thresholds/judge/run/decision rule (untracked OK; must exist). |

---

## NOT Building (Scope Limits)

- **No edits/additions/moves/normalization anywhere under
  `tests/evals/gold/`.** Provenance-frozen; the judged diff must not
  touch it. Read-only by construction; never repaired/regenerated.
- **No live Bedrock/AWS in `-m gate`.** Zero spend. Live is `-m live`,
  opt-in via `EVALS_LIVE=1`, skipped by default; `recorder.py` is the
  only code that ever calls the real model and is never imported by the
  gate.
- **No trusting precomputed metric scores.** Fixtures hold raw artifacts;
  the gate recomputes deterministic metrics and hash-binds artifacts to
  the deterministic retriever and the committed judge prompt/rubric.
- **No non-deployable chunking winner.** Only FIXED_SIZE configs (the
  three keys `kb_stack.py` actually emits) are eligible for
  `infra/cdk.json`. HIERARCHICAL is advisory-only, labelled
  non-deployable in the report. Extending Bedrock hierarchical-chunking
  CDK semantics is a separate infra concern, explicitly out of scope here
  (it would require changing Phase 1's `kb_stack.py` + its infra tests).
- **No new third-party dependency** (no `ragas`/`sklearn`/embeddings).
- **No change to `mutation_floor`/`coverage_floor`, the CHECK set, the
  pinned metric contract, or the gold set** — owner-only. An unreachable
  bar is surfaced to the owner as a finding, never silently weakened.
- No UI, no CI YAML, no multi-judge ensembling.

---

## Step-by-Step Tasks

> STATUS: Tasks 1–11 COMPLETE (build commit `67aec7a`). Gate 8/8 offline
> + deterministic; regression 184; mutation 0.839 ≥ 0.80; gold frozen;
> cdk.json == report.json winner. See the implementation report.

Execute in order. Each task is atomic and independently verifiable.

### Task 1: UPDATE `pyproject.toml` — register markers
- **IMPLEMENT**: add to `[tool.pytest.ini_options]`:
  ```toml
  markers = [
      "gate: deterministic offline RAG eval gate (no AWS spend)",
      "live: opt-in; re-records raw fixtures via the real model",
  ]
  ```
- **GOTCHA**: markers only; do not alter `testpaths`. Not a bar change.
- **VALIDATE**: `PYTHONPATH=src python -m pytest tests/evals -m gate --co -q` → no `PytestUnknownMarkWarning`.

### Task 2: CREATE package markers
- `tests/evals/__init__.py`, `tests/evals/harness/__init__.py` (empty,
  mirror `tests/review_gate/__init__.py`). **No `__init__.py` under
  `tests/evals/gold/`.**
- **VALIDATE**: `PYTHONPATH=src python -m pytest tests/evals --co -q` exits 0.

### Task 3: CREATE `goldset.py` — read-only loader (CRLF-correct)
- **IMPLEMENT**: `load_corpus/index/positives/negatives/labeled_subset`,
  `validate()`. Read every gold file as **bytes** then
  `.decode("utf-8")` (or `open(..., "rb")`); if text mode is used it
  MUST pass `newline=""`. **Never** translate/strip newlines before the
  substring check — the SCHEMA defines exact corpus bytes. Resolve the
  gold dir relative to this file (not CWD). No write API exists in this
  module.
- **VALIDATE**: `tests/evals/test_goldset.py` — SCHEMA conformance; a
  CRLF-bearing synthetic passage round-trips and the substring invariant
  holds (proves no newline translation).

### Task 4: CREATE `chunking.py` — strategies + deploy-equivalence flag
- **IMPLEMENT**: `chunk(doc_text, strategy, max_tokens, overlap_pct) ->
  list[Chunk]`. `FIXED_SIZE` = word-window + overlap (deploy-equivalent
  = True). `HIERARCHICAL` = split on the corpus docs' own section-header
  lines, sub-split oversized sections by the fixed rule
  (deploy-equivalent = **False**). `Chunk` carries `doc_id`, `chunk_id`
  (stable, deterministic), `text`. Token proxy = whitespace words
  (documented).
- **GOTCHA**: detect headers from each doc's own structure; never
  hardcode per-doc. The deploy-equivalent flag is a property of the
  strategy and is consumed by `report.py`.
- **VALIDATE**: `tests/evals/test_chunking.py` — both strategies
  deterministic and non-empty; FIXED vs HIERARCHICAL differ on a
  multi-section doc; `deploy_equivalent` flag correct per strategy.

### Task 5: CREATE `retriever.py` — deterministic BM25, pinned k
- **IMPLEMENT**: `BM25Index(chunks)`, `.search(query, k=5)`; k1=1.5,
  b=0.75 (documented); lowercase + simple word tokenization; **tie-break
  by `chunk_id` ascending**. `k` default is the pinned contract value;
  it is not a tunable the builder may change after seeing scores.
- **VALIDATE**: `tests/evals/test_retriever.py` — identical query →
  identical ranking across runs; tie-break deterministic; a known
  question surfaces its gold passage's chunk within top-`k`.

### Task 6: CREATE `retrieval_metrics.py` — pinned contract
- **IMPLEMENT** `context_recall`, `context_precision` (Ragas-style
  rank-aware, per contract), `mrr` exactly as defined in **Pinned Metric
  Contract**. Relevance = SCHEMA substring-coverage on exact characters.
  Pure functions; mean over positives.
- **VALIDATE**: `tests/evals/test_retrieval_metrics.py` — tiny
  hand-built corpus with hand-computed expected recall/precision/MRR;
  assert exact equality.

### Task 7: CREATE judge assets + `fixtures_io.py` + `recorder.py`
- **IMPLEMENT**:
  - `tests/evals/judge/judge_prompt.md`, `judge_rubric.md` — committed;
    their SHA-256 are the hash-binding anchors.
  - Fixture schema (one JSON per **(gold-item × deploy-equivalent
    config)** and per negative): `item_id`, `chunking_config`
    (strategy+params), `question`, `retrieved_context` (ordered list of
    `{chunk_id,text}`), `retrieved_context_sha256`, `system_answer`
    (raw), `trace` (raw, shaped as `render_citations` consumes),
    `judge_request`, `judge_raw_response`, `prompt_sha256`,
    `rubric_sha256`, `model_id`, `decoding_params`, `harness_version`,
    `recorded_at_commit`. **No metric scores stored.**
  - `fixtures_io.py`: load + structurally validate fixtures; expose the
    hash-binding asserts (prompt/rubric SHA == committed; presence of all
    required fields). It has **no write path**.
  - `recorder.py`: LIVE-only. Runs the real answer path (the crew /
    Bedrock agent) then the real judge for **every (gold-item ×
    deploy-equivalent config) and every negative**, writing the raw
    fixtures + `recording_manifest.json`. Guarded by `EVALS_LIVE=1`;
    imported by `test_live.py` only — never by the gate.
- **GOTCHA**: fixtures are recorded **system behavior**, never ground
  truth; they live OUTSIDE `tests/evals/gold/`. The recorder must cover
  the full (item × deploy-equivalent config) product so the gate has a
  fixture for every scored pair (resolves the per-config gap).
- **VALIDATE**: `fixtures_io` unit test: a fixture with a wrong
  `prompt_sha256` or a missing field is rejected.

### Task 8: CREATE `generation_metrics.py` + `task_metrics.py`
- **IMPLEMENT**:
  - citation-correctness (deterministic): parse the recorded answer's
    `## Sources`; compute the expected block via
    `compliance_assistant.citations.render_citations(fixture.trace)`;
    correct iff normalized cited entries match AND each cited source's
    text overlaps the item's retrieved/gold context. (Genuine structural
    dependency on `render_citations` — protected by the mutation leg.)
  - faithfulness / hallucination-rate: parse the recorded
    `judge_raw_response` per the committed rubric; additionally compute a
    deterministic groundedness lower-bound (answer-sentence vs top-`k`
    context lexical overlap); FAIL if judge-faithfulness is high while
    deterministic groundedness is implausibly low.
  - not-found-honesty (binary == 1.0): for each negative the recorded
    answer must satisfy the **exact** crew predicate
    (`crew.py:_has_grounded_findings`: `.strip().lower().startswith(
    "not found in knowledge base")`, `len < 200`), contain no
    requirement-looking citation (`Req\s*\d` / `Requirement \d` /
    `PCI DSS`), and no non-empty unsupported grounded claim.
  - requirement-coverage: fraction of `expected_requirements` present in
    the recorded answer, mean over `labeled_subset`'s
    `requirement_coverage_ids`.
- **VALIDATE**: `tests/evals/test_generation_metrics.py` &
  `tests/evals/test_task_metrics.py` — a fabricated requirement on a
  negative → honesty < 1.0; a forged high judge score with low
  groundedness → FAIL; a clean grounded answer → pass.

### Task 9: CREATE `report.py` — report.json contract + cdk.json write
- **IMPLEMENT**: score every config end-to-end (recompute, not replay
  scores). Emit `tests/evals/report.json`:
  `{ "k":5, "configs":[ {strategy,params,deploy_equivalent,metrics...} ],
  "winner": {chunkingStrategy,chunkMaxTokens,chunkOverlapPercent} }`.
  Render `tests/evals/report.md` **from** `report.json` (md is for
  humans; json is the machine contract). **Selection rule = max
  context-recall@k subject to faithfulness ≥ 0.95, evaluated ONLY over
  `deploy_equivalent == true` configs.** Write the winner's three keys
  into `infra/cdk.json` `context` with exact key names
  (`chunkingStrategy` str; `chunkMaxTokens` int; `chunkOverlapPercent`
  int), preserving the other context keys and order, 2-space indent,
  trailing newline. HIERARCHICAL appears in report.json labelled
  `deploy_equivalent:false` and is never the winner.
- **GOTCHA**: never write under `tests/evals/gold/`. cdk.json keys must
  match `kb_stack.py` exactly.
- **VALIDATE**: `tests/evals/test_chunking_decision.py` — ≥2
  `deploy_equivalent` configs in report.json; report.md exists;
  `infra/cdk.json` chunking == `report.json` winner (parse JSON both
  sides; assert exact str/int equality, not markdown parsing).

### Task 10: Strengthen `tests/test_citations.py` (mutation leg)
- **IMPLEMENT**: add cases killing every mutant class in `citations.py`:
  the `len>200` / `[:197]` truncation boundary; dedup identity
  (`entry not in seen`); the `s3 or loc.get("type") or "unknown source"`
  fallback chain; `" ".join(snippet.split())` whitespace collapse;
  `seen.sort()` ordering; the exact `_NO_SOURCES` string; **and the
  `_iter_references` guard cluster** — `if not isinstance(trace, dict):
  return`, the two `if not isinstance(...): continue` (mutated to
  `break` or negated `isinstance`), and the `... or [] ` fallbacks.
- **GOTCHA**: the mutation runner executes ONLY `tests/test_citations.py`
  vs `citations.py`; target ≥ global `mutation_floor` (0.80).
- **VALIDATE**: `PYTHONPATH=src python -m pytest tests/test_citations.py -q`
  green; (gate run will measure the kill-rate).

### Task 11: gate suite, live suite, frozen guard, docs
- **IMPLEMENT**:
  - `tests/evals/test_gate.py` (`@pytest.mark.gate`): assert
    `len(positives) >= 30 and len(negatives) >= 8` (the cardinality
    CHECK, mechanically); recompute and assert retrieval recall ≥0.90 /
    precision ≥0.80 / MRR ≥0.80; faithfulness ≥0.95 /
    citation-correctness ≥0.95 / hallucination ≤0.05;
    not-found-honesty ==1.0 / requirement-coverage ≥0.90; assert
    hash-binding (prompt/rubric SHA, retrieved_context hash ==
    recomputed; missing fixture for any scored (item,config) → fail);
    determinism (run the aggregate twice → identical numbers); no network
    import.
  - `tests/evals/test_live.py` (`@pytest.mark.live`): re-records via
    `recorder.py`; `pytest.skip` unless `EVALS_LIVE=1`.
  - `tests/evals/test_gold_frozen.py`: FAIL if
    `git status --porcelain -- tests/evals/gold` is non-empty; assert the
    working-tree file set under `tests/evals/gold` == `git ls-tree -r
    HEAD -- tests/evals/gold`; byte-compare every tracked blob
    (`git cat-file blob` vs disk bytes). Bidirectional — catches added,
    moved, modified, or normalized files.
  - `docs/evals.md`: metrics, the pinned contract (k, definitions),
    thresholds, judge model + prompt/rubric location + hashes, how to run
    `-m gate` and re-record `-m live`, the deploy-equivalence rule and
    selection rule.
- **GOTCHA**: `docs/` is gitignored — file must exist, must NOT be
  staged.
- **VALIDATE**: full validation commands below.

---

## Testing Strategy

### Unit / suite tests
| Test File | Validates |
|-----------|-----------|
| `tests/evals/test_goldset.py` | SCHEMA conformance; CRLF preserved (no newline translation) |
| `tests/evals/test_chunking.py` | strategy determinism; deploy-equivalence flag |
| `tests/evals/test_retriever.py` | BM25 determinism; tie-break; pinned k |
| `tests/evals/test_retrieval_metrics.py` | recall/precision/MRR exact math |
| `tests/evals/test_generation_metrics.py` | deterministic citation-correctness; judge-vs-groundedness cross-check |
| `tests/evals/test_task_metrics.py` | not-found-honesty binary; requirement-coverage |
| `tests/evals/test_gate.py` | all PRD bars recomputed; cardinality; determinism; hash-binding; offline |
| `tests/evals/test_chunking_decision.py` | ≥2 deployable configs; cdk.json == report.json winner |
| `tests/evals/test_gold_frozen.py` | bidirectional provenance guard |
| `tests/evals/test_live.py` | skipped w/o `EVALS_LIVE`; re-records when set |
| `tests/test_citations.py` | mutation-killing cases incl. `_iter_references` guards |

### Edge Cases Checklist
- [ ] Negative answered with a fabricated requirement → honesty < 1.0
- [ ] Forged high judge faithfulness + low deterministic groundedness → FAIL
- [ ] Identical query retrieved twice → identical ranking (tie-break stable)
- [ ] Missing fixture for ANY scored (item × deploy-equivalent config) → hard fail
- [ ] Fixture `prompt_sha256`/`rubric_sha256` ≠ committed judge files → hard fail
- [ ] Recorded `retrieved_context` hash ≠ recomputed by current retriever → hard fail
- [ ] CRLF in corpus read → substring invariant holds (newline="" / bytes)
- [ ] HIERARCHICAL scores best but is never written to cdk.json (advisory)
- [ ] `cdk.json` other context keys + types preserved after winner write
- [ ] Added/moved/untracked file under `tests/evals/gold/` → frozen guard FAIL
- [ ] `-m live` without `EVALS_LIVE` → skipped, zero network

---

## Validation Commands

**The following are Phase 3's PRD `CHECK:` items, verbatim. A phase flips
to `complete` only when every one exits 0 (realized as
`pytest tests/evals -m gate` assertions where the CHECK states a
threshold). This section is the plan's contract and must match the PRD
exactly.**

- GATE: panel PASS required — same panel as Phase 2, PLUS the gold-set provenance rule: `tests/evals/gold/PROVENANCE.md` declares an `owner` or `codex` author and the gold set is unmodified by the judged diff (ralph may not author its own ground truth).
- CHECK: gold set committed at `tests/evals/gold/` — ≥ 30 positive items across the in-scope regulations (each: question + ≥1 expected source-passage locator) **and** ≥ 8 out-of-corpus negative questions.
- CHECK: `pytest tests/evals -m gate` exits 0 **deterministically offline** (recorded retrieval/generation fixtures, no live Bedrock spend); same suite runnable `-m live` (opt-in).
- CHECK (retrieval, mean over gold set): context-recall ≥ 0.90, context-precision ≥ 0.80, MRR ≥ 0.80.
- CHECK (generation, LLM-as-judge; judge prompt+rubric committed): faithfulness/groundedness ≥ 0.95, citation-correctness ≥ 0.95, hallucination-rate ≤ 0.05.
- CHECK (task-level): not-found-honesty == 1.0 (every out-of-corpus question answered with an explicit "not in knowledge base"; **zero** fabricated requirements); requirement-coverage ≥ 0.90 on the labeled subset.
- CHECK (chunking decision = the Phase 1↔3 handoff): harness scores ≥ 2 chunking configs (FIXED_SIZE baseline + ≥1 of HIERARCHICAL/SEMANTIC), writes `tests/evals/report.md`; selection rule = max context-recall@k subject to faithfulness ≥ 0.95; the winning chunking values are written into `infra/cdk.json` context and a test asserts `cdk.json` == the report's winner.
- CHECK: `docs/evals.md` documents metrics, thresholds, judge model, run instructions (untracked is fine; file must exist).

> Note on the chunking-decision CHECK: HIERARCHICAL is *scored* (so "≥2
> configs, FIXED_SIZE + ≥1 of HIERARCHICAL/SEMANTIC" is satisfied) but,
> because `kb_stack.py` only emits `fixed_size_chunking_configuration`,
> the *selection rule* and the cdk.json write apply only over
> deploy-equivalent FIXED_SIZE configs (≥2 of them). The report labels
> deploy-equivalence. `cdk.json == report.json winner` is the binary
> machine check (not markdown parsing).

**Baseline (PRD rule, also enforced by the gate's regression leg):** prior
phases' checks still green — `PYTHONPATH=src python -m pytest tests infra/tests -q`
all pass — and nothing under `docs/` is staged.

### Local run order (for the builder)
```bash
PYTHONPATH=src python -m pytest tests/evals -m gate --co -q     # collection + markers
PYTHONPATH=src python -m pytest tests/evals -m gate -q          # the gate (offline, recomputed)
PYTHONPATH=src python -m pytest tests/evals -m gate -q          # run twice → identical aggregate
PYTHONPATH=src python -m pytest tests infra/tests -q            # no regression in prior phases
git status --porcelain tests/evals/gold                          # MUST be empty
git diff --cached --name-only | grep '^docs/' && echo FAIL || echo ok
```

---

## Acceptance Criteria
- [ ] All seven Phase 3 `CHECK:` items pass (verbatim contract).
- [ ] `pytest tests/evals -m gate` is offline, deterministic (run-twice
      identical), zero AWS spend, and **recomputes** metrics (no trusted
      precomputed scores; hash-binding enforced).
- [ ] Nothing under `tests/evals/gold/` created/modified/moved (frozen
      guard test + git porcelain empty).
- [ ] `infra/cdk.json` chunking == `tests/evals/report.json` winner, and
      the winner is a deploy-equivalent FIXED_SIZE config.
- [ ] `tests/test_citations.py` kills ≥ `mutation_floor` (0.80) of
      `citations.py` mutants.
- [ ] No new third-party dependency; no `docs/` staged.
- [ ] No regression: `pytest tests infra/tests -q` all green.

---

## Risks and Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Builder writes/normalizes a gold file → provenance FAIL | MED | HIGH | read-only loader; bidirectional `test_gold_frozen.py`; restated NOT-building; `git status` gate. |
| Circular fixtures (committed passing scores) | — | HIGH | RESOLVED: fixtures store raw artifacts only; gate recomputes deterministic metrics + hash-binds to retriever & committed judge prompt/rubric; `-m live` is the sole writer. |
| Non-deployable chunking winner | — | HIGH | RESOLVED: selection restricted to deploy-equivalent FIXED_SIZE; HIERARCHICAL advisory-only, never written. |
| precision/recall vs `k` gaming or infeasibility | MED | HIGH | `k` and metric denominators pinned BEFORE build; Ragas-style rank-aware precision (feasible when the relevant chunk ranks first); owner-only to move. If still infeasible → owner finding, never a silent weakening. |
| Citation-correctness not truly on `render_citations` | — | MED | RESOLVED: deterministic structural comparison to `render_citations(trace)`; mutation leg protects it. |
| CRLF newline translation breaks substring invariant | — | MED | RESOLVED: bytes / `newline=""`; explicit CRLF test. |
| Forged judge response | MED | HIGH | deterministic groundedness lower-bound cross-check; prompt/rubric hash-binding; context-hash binding to the deterministic retriever. |
| Mutation leg < 0.80 on `citations.py` | MED | HIGH | Task 10 enumerates every mutant class incl. `_iter_references` guards; citation-correctness genuinely exercises the function. |

## Notes
- The gold set is frozen ground truth, committed before the gate base was
  pinned — so the judged diff is harness-only and the provenance leg
  passes iff the build never touches `tests/evals/gold/`. Every task
  restates this.
- HIERARCHICAL is implemented and scored to satisfy the "+≥1 of
  HIERARCHICAL/SEMANTIC" scoring clause, but is honestly labelled
  non-deployable because Phase 1's `kb_stack.py` emits only
  `fixed_size_chunking_configuration`; deciding "the real chunking value"
  means deciding a *deployable* value. Extending Bedrock
  hierarchical-chunking CDK support is deferred (separate infra concern).
- The judge is an LLM (PRD "LLM-as-judge"); offline determinism comes
  from recorded **raw** judge responses replayed and re-derived per the
  committed rubric, cross-checked deterministically — not a faked judge
  and not an unchecked oracle. Re-recording is opt-in `-m live` only.
- Confidence: 8/10 one-pass. Residual risk is threshold feasibility under
  the now-pinned honest metric contract — a legitimate tuning problem on
  chunking/retriever levers (never on the frozen gold or the tests),
  surfaced to the owner if a bar proves unreachable.
