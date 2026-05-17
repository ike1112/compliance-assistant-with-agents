"""Retrieval metrics — the pinned contract (plan §Pinned Metric Contract).

Relevance (SCHEMA §corpus_index): a retrieved chunk is relevant to a
positive iff it contains, or is contained by, at least one of that item's
gold-passage `text` values, comparing exact characters (no
normalization).

- context_recall = fraction of the item's gold passages whose text is
  covered by >=1 of the top-k retrieved chunks (mean over positives).
- context_precision = Ragas-style rank-aware average precision:
  sum_i (precision@i * rel_i) / (#gold passages), capped at 1.0.
- mrr = mean of 1/rank_of_first_relevant within top-k, else 0.
"""
from __future__ import annotations

from tests.evals.harness.chunking import Chunk


def _covers(chunk_text: str, gold_text: str) -> bool:
    return gold_text in chunk_text or chunk_text in gold_text


def _relevant(chunk: Chunk, gold_texts: list[str]) -> bool:
    return any(_covers(chunk.text, gt) for gt in gold_texts)


def recall(retrieved: list[Chunk], gold_texts: list[str]) -> float:
    if not gold_texts:
        return 0.0
    covered = sum(
        1 for gt in gold_texts
        if any(_covers(c.text, gt) for c in retrieved)
    )
    return covered / len(gold_texts)


def precision(retrieved: list[Chunk], gold_texts: list[str]) -> float:
    if not gold_texts:
        return 0.0
    hits = 0
    acc = 0.0
    for i, c in enumerate(retrieved, 1):
        if _relevant(c, gold_texts):
            hits += 1
            acc += hits / i
    return min(1.0, acc / len(gold_texts))


def mrr(retrieved: list[Chunk], gold_texts: list[str]) -> float:
    for i, c in enumerate(retrieved, 1):
        if _relevant(c, gold_texts):
            return 1.0 / i
    return 0.0


def mean_retrieval(per_item: list[tuple[list[Chunk], list[str]]]) -> dict:
    """per_item: list of (top_k_retrieved_chunks, gold_passage_texts)."""
    if not per_item:
        return {"context_recall": 0.0, "context_precision": 0.0, "mrr": 0.0}
    n = len(per_item)
    return {
        "context_recall": sum(recall(r, g) for r, g in per_item) / n,
        "context_precision": sum(precision(r, g) for r, g in per_item) / n,
        "mrr": sum(mrr(r, g) for r, g in per_item) / n,
    }
