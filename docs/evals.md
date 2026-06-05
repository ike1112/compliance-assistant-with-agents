# RAG Evaluation Harness

Offline, deterministic, non-circular evaluation of the compliance
assistant's grounding layer against the frozen, codex-authored gold set
at `tests/evals/gold/` (immutable ground truth; never modified by the
harness).

## What is the "system under test"

There is no deployed Bedrock knowledge base in this environment (Phase 1's
operator deploy is a HUMAN-GATE). The eval's system is therefore:

1. **Retrieval** — deterministic BM25 over the frozen corpus, chunked per
   the config under test. Fully offline, reproducible, no model spend.
2. **Generation** — an LLM (the authenticated `codex` CLI) answers
   strictly from the retrieved context, declining with exactly
   `Not found in knowledge base` when the context is insufficient
   (mirrors `compliance_assistant.crew._has_grounded_findings`).
3. **Judge** — an LLM scores faithfulness/hallucination with the
   committed `tests/evals/judge/judge_prompt.md` + `judge_rubric.md`.

This is exactly the signal a chunking decision needs (retrieval quality
and downstream answer quality). The production crew (Bedrock Agent) is a
separate runtime path; this harness evaluates retrieval + grounded
generation.

## Determinism & anti-gaming

`pytest tests/evals -m gate` is offline (sockets blocked in-test) and
deterministic (recompute twice → identical). It never trusts a stored
score. Each fixture is a RAW recording (system answer, retrieved context
+ its SHA-256, trace, judge request, raw judge response, model id,
harness version, recorded-at commit, and the committed prompt/rubric
SHA-256). The gate:

- recomputes retrieval metrics from the frozen corpus,
- recomputes citation-correctness deterministically against
  `compliance_assistant.citations.render_citations`,
- recomputes not-found-honesty and requirement-coverage from the recorded
  answer text,
- reads faithfulness/hallucination from the raw judge response and
  **cross-checks** them with a deterministic groundedness lower-bound
  (a high judge score with low lexical groundedness is treated as forged
  → FAIL),
- hash-binds every fixture to the committed judge prompt/rubric and to
  its own recorded context (mismatch → FAIL),
- fails if any scored (item × deploy-equivalent config) fixture is
  missing.

## Residual trust (stated explicitly)

The gate's **binding** generation criterion is deterministic: recomputed
lexical groundedness of the recorded answer against the **recomputed**
BM25 retrieved context (the fixture's `retrieved_context` must equal
this run's deterministic top-k or the gate hard-fails), plus
deterministic citation-correctness, requirement-coverage, and
not-found-honesty. The recorded LLM judge `faithfulness`/`hallucination`
are **corroborating evidence only** — offline execution cannot attest
that an LLM actually produced a given `judge_raw_response`; SHA-binding
only proves the fixture names the committed prompt/rubric. A fabricated
judge score therefore cannot pass the gate on its own: the answer must
still be deterministically grounded in the recomputed retrieved context
(groundedness ≥ 0.95) with no forged item. The one residual trust is
that the recorded *system answer* was produced by the live model run
(re-recordable only via `EVALS_LIVE=1`); every metric that decides
pass/fail is recomputed from it deterministically.

## Metrics, thresholds (the pinned contract)

- `k = 5` (fixed before implementation; same k for retrieval scoring,
  generation context, and the report).
- Relevance = SCHEMA substring-coverage (exact characters).
- context-recall ≥ 0.90, context-precision ≥ 0.80 (Ragas-style
  rank-aware), MRR ≥ 0.80.
- faithfulness ≥ 0.95, citation-correctness ≥ 0.95, hallucination ≤ 0.05.
- not-found-honesty == 1.0 (every negative declines, zero fabricated
  requirements), requirement-coverage ≥ 0.90 on the labeled subset.

Judge model: the authenticated `codex` CLI (`model_id: codex-cli`),
recorded once; thresholds in `tests/evals/judge/judge_rubric.md`.

## Chunking decision (Phase 1 ↔ 3 handoff)

`tests/evals/harness/report.py` scores ≥2 deploy-equivalent FIXED_SIZE
configs plus an advisory HIERARCHICAL config. Selection rule: **max
context-recall@k subject to faithfulness ≥ 0.95**, over deploy-equivalent
configs only; deterministic tie-break MRR → precision → config key.
The selection rule, exactly as enforced in `report.py`, is: **max
context-recall@k subject to deterministic groundedness ≥ 0.95 AND
faithfulness ≥ 0.95 AND no forged fixture**, over deploy-equivalent
FIXED_SIZE configs only; tie-break MRR, then precision, then config key.
HIERARCHICAL is non-deployable (`infra/stacks/kb_stack.py` emits only
Bedrock fixed-size chunking, and now rejects a non-FIXED_SIZE context
value at synth) and is never written to `infra/cdk.json`. The negative
fixtures carry the same residual-trust caveat as positives: their
`retrieved_context` is bound to the recomputed retriever, but the
recorded "Not found in knowledge base" answer text itself is trusted as
a live recording (an honest negative can only help, never inflate a
score — it is rejected if it carries any requirement citation).
The winner is written into `infra/cdk.json` `context`; `report.json` is
the machine contract and `report.md` is rendered from it; a gate test
asserts `cdk.json == report.json` winner.

## Running

```bash
# Gate (offline, deterministic, no spend) — what CI / the phase gate runs:
PYTHONPATH=src python -m pytest tests/evals -m gate -q

# Re-record raw fixtures via the real model (opt-in, resumable):
EVALS_LIVE=1 PYTHONPATH=src python -m tests.evals.harness.recorder
# then regenerate report.json / report.md / infra/cdk.json:
PYTHONPATH=src python -m tests.evals.harness.report
```
