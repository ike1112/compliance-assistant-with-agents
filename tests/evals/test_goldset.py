"""Frozen gold loads and conforms to SCHEMA; reads preserve exact bytes
(no newline translation), so the substring invariant holds on a CRLF
checkout.
"""
from tests.evals.harness import goldset


def test_schema_validates():
    goldset.validate()  # raises on any violation


def test_counts_meet_check_minimums():
    assert len(goldset.load_positives()) >= 30
    assert len(goldset.load_negatives()) >= 8


def test_every_index_text_is_exact_substring():
    corpus = goldset.load_corpus()
    for p in goldset.load_index():
        assert p.text in corpus[p.doc_id]


def test_no_newline_translation(tmp_path, monkeypatch):
    # A CRLF-bearing file read via goldset._read_text must keep the \r;
    # a text-mode open would strip it and break the substring rule.
    f = tmp_path / "crlf.txt"
    f.write_bytes(b"alpha\r\nbeta line with CR")
    assert goldset._read_text(f) == "alpha\r\nbeta line with CR"
    assert "\r\n" in goldset._read_text(f)
