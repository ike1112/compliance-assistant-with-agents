"""Read-only loader for the FROZEN gold set (tests/evals/gold/).

The gold tree is provenance-frozen ground truth. This module only ever
reads it: every file is read as bytes then decoded UTF-8 with NO newline
translation, so the exact corpus characters the SCHEMA calls load-bearing
are preserved (a plain text-mode open would universal-newline-translate
CRLF and break the substring invariant on a Windows checkout). There is
deliberately no write path in this module.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

GOLD_DIR = Path(__file__).resolve().parents[1] / "gold"
CORPUS_DIR = GOLD_DIR / "corpus"


def _read_text(path: Path) -> str:
    # Bytes -> utf-8, no newline translation (SCHEMA defines exact bytes).
    return path.read_bytes().decode("utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    for i, line in enumerate(_read_text(path).split("\n"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:  # pragma: no cover - guard
            raise AssertionError(f"{path.name}:{i} invalid JSON: {e}") from e
    return out


@dataclass(frozen=True)
class Passage:
    passage_id: str
    doc_id: str
    section: str
    text: str


@dataclass(frozen=True)
class Positive:
    id: str
    question: str
    gold_passage_ids: tuple[str, ...]
    reference_answer: str
    expected_requirements: tuple[str, ...]


@dataclass(frozen=True)
class Negative:
    id: str
    question: str


def load_corpus() -> dict[str, str]:
    """doc_id -> exact document text (no newline translation)."""
    return {
        p.stem: _read_text(p)
        for p in sorted(CORPUS_DIR.glob("*.txt"))
    }


def load_index() -> list[Passage]:
    return [
        Passage(r["passage_id"], r["doc_id"], r["section"], r["text"])
        for r in _read_jsonl(GOLD_DIR / "corpus_index.jsonl")
    ]


def index_by_id() -> dict[str, Passage]:
    return {p.passage_id: p for p in load_index()}


def load_positives() -> list[Positive]:
    return [
        Positive(
            r["id"],
            r["question"],
            tuple(r["gold_passage_ids"]),
            r["reference_answer"],
            tuple(r["expected_requirements"]),
        )
        for r in _read_jsonl(GOLD_DIR / "positives.jsonl")
    ]


def load_negatives() -> list[Negative]:
    return [
        Negative(r["id"], r["question"])
        for r in _read_jsonl(GOLD_DIR / "negatives.jsonl")
    ]


def load_labeled_subset() -> dict:
    return json.loads(_read_text(GOLD_DIR / "labeled_subset.json"))


def validate() -> None:
    """Assert SCHEMA conformance. Raises AssertionError on any violation."""
    corpus = load_corpus()
    index = load_index()
    positives = load_positives()
    negatives = load_negatives()
    subset = load_labeled_subset()

    assert len(positives) >= 30, f"need >=30 positives, got {len(positives)}"
    assert len(negatives) >= 8, f"need >=8 negatives, got {len(negatives)}"

    pid = {p.passage_id for p in index}
    assert len(pid) == len(index), "duplicate passage_id in corpus_index"
    for p in index:
        assert p.doc_id in corpus, f"{p.passage_id}: unknown doc {p.doc_id}"
        assert p.text in corpus[p.doc_id], (
            f"{p.passage_id}: text is not an exact substring of "
            f"corpus/{p.doc_id}.txt"
        )

    pos_ids = {p.id for p in positives}
    assert len(pos_ids) == len(positives), "duplicate positive id"
    for p in positives:
        assert p.gold_passage_ids, f"{p.id}: no gold_passage_ids"
        for g in p.gold_passage_ids:
            assert g in pid, f"{p.id}: dangling gold_passage_id {g}"
        assert p.expected_requirements, f"{p.id}: no expected_requirements"
        assert p.reference_answer.strip(), f"{p.id}: empty reference_answer"

    for n in negatives:
        assert n.id and n.question, f"bad negative {n}"

    for sid in subset["requirement_coverage_ids"]:
        assert sid in pos_ids, f"labeled_subset id not a positive: {sid}"
