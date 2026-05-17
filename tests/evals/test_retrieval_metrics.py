"""Retrieval metric math on a tiny hand-built corpus with hand-computed
expected values (the pinned contract)."""
from tests.evals.harness.chunking import Chunk
from tests.evals.harness import retrieval_metrics as M


def _c(cid, text):
    return Chunk("d", cid, text)


def test_recall_full_and_partial():
    gold = ["alpha", "beta"]
    retrieved = [_c("1", "xx alpha xx"), _c("2", "yy beta yy")]
    assert M.recall(retrieved, gold) == 1.0
    assert M.recall([_c("1", "xx alpha xx")], gold) == 0.5
    assert M.recall([_c("1", "nothing")], gold) == 0.0


def test_precision_rank_aware_relevant_first():
    # 1 gold passage, relevant chunk at rank 1 → precision contribution
    # = (1/1)/1 = 1.0
    gold = ["alpha"]
    assert M.precision([_c("1", "alpha"), _c("2", "no")], gold) == 1.0


def test_precision_relevant_at_rank_two():
    # rel at rank 2 only: precision@2 = 1/2; /1 gold = 0.5
    gold = ["alpha"]
    assert M.precision([_c("1", "no"), _c("2", "alpha")], gold) == 0.5


def test_precision_capped_at_one():
    gold = ["a"]
    # two relevant chunks, one gold → uncapped 1.0 + 1.0 = 2.0 → capped 1.0
    assert M.precision([_c("1", "a"), _c("2", "a")], gold) == 1.0


def test_mrr_first_relevant_rank():
    gold = ["alpha"]
    assert M.mrr([_c("1", "no"), _c("2", "no"), _c("3", "alpha")], gold) == 1 / 3
    assert M.mrr([_c("1", "no")], gold) == 0.0


def test_contained_by_relevance_direction():
    # chunk text contained by a longer gold passage is still relevant.
    gold = ["the full long gold passage text"]
    assert M.recall([_c("1", "long gold passage")], gold) == 1.0


def test_mean_retrieval_aggregates():
    gold = ["alpha"]
    per = [([_c("1", "alpha")], gold), ([_c("1", "no")], gold)]
    out = M.mean_retrieval(per)
    assert out["context_recall"] == 0.5
    assert out["mrr"] == 0.5
