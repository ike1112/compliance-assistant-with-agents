# Judge Rubric & Gate Thresholds

The LLM-as-judge scores each positive answer for `faithfulness` and
`hallucination` in [0,1] using `judge_prompt.md`. The gate parses the
recorded raw judge response and applies these thresholds (means over the
evaluated positives unless stated):

| Metric | Bar | Source |
|--------|-----|--------|
| faithfulness / groundedness | ≥ 0.95 | recorded judge response, cross-checked |
| citation-correctness | ≥ 0.95 | deterministic (render_citations vs gold) |
| hallucination-rate | ≤ 0.05 | recorded judge response |
| context-recall | ≥ 0.90 | deterministic retrieval |
| context-precision | ≥ 0.80 | deterministic retrieval |
| MRR | ≥ 0.80 | deterministic retrieval |
| not-found-honesty | == 1.0 | deterministic (negatives) |
| requirement-coverage | ≥ 0.90 | deterministic (labeled subset) |

## Deterministic cross-check (anti-forgery)

Recorded LLM judge scores are EVIDENCE, never an unchecked oracle. For
every positive the gate also computes a deterministic groundedness
lower-bound: the fraction of answer sentences whose token set overlaps
the retrieved context by ≥ 0.30 (Jaccard-style). If the recorded
faithfulness ≥ 0.95 while deterministic groundedness < 0.40 for that
item, the fixture is treated as forged and the gate FAILS.

The judge prompt and this rubric are hash-bound: every fixture records
`prompt_sha256` and `rubric_sha256`; the gate fails if they do not match
the committed files, so the recorded scores cannot be decoupled from the
committed judging contract.

## Residual trust (the binding criterion is deterministic)

Offline execution cannot attest that an LLM actually produced a given
`judge_raw_response`; hash-binding only proves the fixture names this
committed contract. Therefore the recorded judge `faithfulness` and
`hallucination` are **corroborating evidence only** and never, by
themselves, pass the gate. The BINDING generation criterion is
deterministic and recomputed: lexical groundedness of the recorded
answer against the **recomputed** BM25 retrieved context must be
≥ 0.95, with no forged item (a high recorded faithfulness combined with
low deterministic groundedness is treated as forged → FAIL), and the
fixture's `retrieved_context` must byte-equal this run's deterministic
top-k. The one residual trust is that the recorded *system answer* was
produced by the live model run (re-recordable only via `EVALS_LIVE=1`);
every metric that decides pass/fail is recomputed deterministically from
it. Negative answers carry the same caveat: their context is bound to
the recomputed retriever, the "Not found in knowledge base" text is a
trusted live recording, and any requirement citation in a negative
fails not-found-honesty (an honest negative can only help, never inflate
a score). This rubric is gate-side interpretation only — it is never
sent to the model (the recorder sends `judge_prompt.md` alone), so its
text never influences a recorded judge response.
