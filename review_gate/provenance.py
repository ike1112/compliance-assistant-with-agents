"""Phase-3 gold-set bootstrap rule (spec §5).

Mutation cannot protect the gold set on the phase that *creates* it, so
the gate enforces authoring provenance instead: a committed PROVENANCE.md
marker declaring an approved author (owner or codex), present before the
harness diff, and the gold set untouched by the diff being judged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from review_gate.diff import integrity_violations

GOLD_DIR = "tests/evals/gold"
GOLD_MARKER = "tests/evals/gold/PROVENANCE.md"
_APPROVED_AUTHORS = {"owner", "codex"}
_AUTHOR_RE = re.compile(r"^author:\s*(\w+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ProvenanceResult:
    ok: bool
    reason: str


def verify_gold_provenance(repo: Path, base_sha: str) -> ProvenanceResult:
    repo = Path(repo)
    marker = repo / GOLD_MARKER

    if not marker.is_file():
        return ProvenanceResult(False, f"gold-set marker {GOLD_MARKER} missing")

    text = marker.read_text(encoding="utf-8")
    m = _AUTHOR_RE.search(text)
    if not m or m.group(1) not in _APPROVED_AUTHORS:
        return ProvenanceResult(
            False, f"gold-set author must be one of {_APPROVED_AUTHORS}")

    if integrity_violations(repo, base_sha, [GOLD_DIR]):
        return ProvenanceResult(
            False, f"{GOLD_DIR} was modified inside the judged diff")

    return ProvenanceResult(True, "gold-set provenance OK")
