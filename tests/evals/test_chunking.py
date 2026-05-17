"""Chunkers are deterministic; deploy-equivalence flag is correct;
FIXED_SIZE and HIERARCHICAL differ on a multi-section document.
"""
from tests.evals.harness import chunking
from tests.evals.harness.goldset import load_corpus

_DOC = "req-03-protect-stored-data"


def test_strategy_deploy_equivalence_flags():
    assert chunking.STRATEGIES["FIXED_SIZE"] is True
    assert chunking.STRATEGIES["HIERARCHICAL"] is False


def test_fixed_size_deterministic_and_nonempty():
    corpus = load_corpus()
    a = chunking.chunk(_DOC, corpus[_DOC], "FIXED_SIZE", 120, 20)
    b = chunking.chunk(_DOC, corpus[_DOC], "FIXED_SIZE", 120, 20)
    assert a and a == b
    assert all(c.chunk_id for c in a)
    assert len({c.chunk_id for c in a}) == len(a)


def test_hierarchical_deterministic_and_section_aware():
    corpus = load_corpus()
    h = chunking.chunk(_DOC, corpus[_DOC], "HIERARCHICAL", 250, 20)
    assert h and h == chunking.chunk(_DOC, corpus[_DOC],
                                     "HIERARCHICAL", 250, 20)


def test_fixed_vs_hierarchical_differ():
    corpus = load_corpus()
    fs = chunking.chunk(_DOC, corpus[_DOC], "FIXED_SIZE", 120, 20)
    hi = chunking.chunk(_DOC, corpus[_DOC], "HIERARCHICAL", 120, 20)
    assert [c.text for c in fs] != [c.text for c in hi]


def test_unknown_strategy_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown chunking strategy"):
        chunking.chunk("d", "text", "SEMANTIC", 100, 10)
