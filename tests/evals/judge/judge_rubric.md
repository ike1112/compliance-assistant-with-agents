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
