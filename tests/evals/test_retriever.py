"""BM25 is deterministic, tie-breaks by chunk_id, honours k, and surfaces
a known gold passage's chunk within top-k.
"""
from tests.evals.harness.chunking import Chunk, chunk_corpus
from tests.evals.harness.goldset import index_by_id, load_corpus, load_positives
from tests.evals.harness.retriever import BM25Index, tokenize


def test_tokenize_lowercases_and_splits():
    assert tokenize("PCI DSS 3.5.1, MFA!") == ["pci", "dss", "3", "5", "1", "mfa"]


def test_search_is_deterministic():
    corpus = load_corpus()
    chunks = chunk_corpus(corpus, "FIXED_SIZE", 120, 20)
    idx = BM25Index(chunks)
    q = "audit log retention period"
    r1 = [(c.chunk_id, s) for c, s in idx.search(q, 5)]
    r2 = [(c.chunk_id, s) for c, s in idx.search(q, 5)]
    assert r1 == r2 and len(r1) == 5


def test_tie_break_by_chunk_id():
    # Two identical-text chunks → equal score → ordered by chunk_id asc.
    chunks = [Chunk("d", "d#b", "same words here"),
              Chunk("d", "d#a", "same words here")]
    idx = BM25Index(chunks)
    ranked = [c.chunk_id for c, _ in idx.search("same words here", 2)]
    assert ranked == ["d#a", "d#b"]


def test_known_question_retrieves_its_gold_chunk():
    corpus = load_corpus()
    chunks = chunk_corpus(corpus, "FIXED_SIZE", 180, 20)
    idx = BM25Index(chunks)
    by_id = index_by_id()
    pos = load_positives()[0]
    gold_texts = [by_id[g].text for g in pos.gold_passage_ids]
    top = idx.search(pos.question, 5)
    assert any(
        any(gt in c.text or c.text in gt for gt in gold_texts)
        for c, _ in top
    )
