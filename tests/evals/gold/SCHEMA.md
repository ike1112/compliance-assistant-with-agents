# Frozen Gold Schema

This directory is immutable ground truth for the PCI DSS RAG evaluation harness. The harness must implement against these files as written and must not rewrite, normalize, regenerate, or repair the data.

## Files

### `corpus/<doc_id>.txt`

Plain-text source documents containing original, faithful summaries of PCI DSS v4.0 and v4.0.1 requirement areas. Each `doc_id` is lowercase kebab case and corresponds to one corpus file name without the `.txt` suffix.

### `corpus_index.jsonl`

JSON Lines file with one passage object per line:

`{"passage_id": str, "doc_id": str, "section": str, "text": str}`

Fields:

- `passage_id`: Stable unique identifier for the indexed passage.
- `doc_id`: Corpus document id. The referenced file is `corpus/<doc_id>.txt`.
- `section`: Human-readable section label from the corpus document.
- `text`: Exact contiguous substring of the referenced corpus document. The harness must treat this exact substring as load-bearing evidence for retrieval relevance.

Retrieval relevance is measured by substring coverage: a retrieved chunk is relevant to a positive example when it contains, or is contained by, at least one listed gold passage `text` for that example, preserving the exact characters from the corpus. Implementations may add their own chunk identifiers, but relevance must ultimately be judged against these canonical passage substrings.

### `positives.jsonl`

JSON Lines file with one positive question object per line:

`{"id": str, "question": str, "gold_passage_ids": [str, ...], "reference_answer": str, "expected_requirements": [str, ...]}`

Fields:

- `id`: Stable unique positive-example identifier.
- `question`: Realistic compliance question answerable strictly from the listed gold passages.
- `gold_passage_ids`: One or more `passage_id` values from `corpus_index.jsonl` that contain the information needed to answer the question.
- `reference_answer`: Concise answer grounded only in the listed passages. It ends with the relevant PCI DSS requirement citation or citations.
- `expected_requirements`: Canonical PCI DSS requirement identifiers that the answer must cover for requirement-coverage scoring.

### `negatives.jsonl`

JSON Lines file with one negative question object per line:

`{"id": str, "question": str}`

Negative questions are plausible compliance-assistant questions that are out of corpus. Not-found honesty means the correct system behavior is to explicitly state that the answer is not available in the knowledge base or committed corpus and to avoid fabricating citations, requirements, or procedural details.

### `labeled_subset.json`

Single JSON object:

`{"requirement_coverage_ids": [str, ...], "rationale": str}`

Fields:

- `requirement_coverage_ids`: Subset of positive `id` values used for requirement-coverage scoring.
- `rationale`: Explanation of why the selected positives are suitable for coverage scoring.

## Validation Expectations

Every JSONL line must parse as JSON. Every positive `gold_passage_ids` value must resolve to a passage in `corpus_index.jsonl`. Every indexed passage `text` must be an exact contiguous substring of `corpus/<doc_id>.txt`. Negative questions must remain genuinely unanswerable from the committed corpus.
