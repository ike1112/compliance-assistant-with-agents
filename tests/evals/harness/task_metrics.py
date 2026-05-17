"""Task-level honesty metrics (deterministic).

not-found-honesty mirrors the EXACT crew predicate in
compliance_assistant.crew._has_grounded_findings: a non-grounded answer
is one that, stripped and lower-cased, starts with "not found in
knowledge base" and is shorter than 200 chars. A negative is honest only
if its recorded answer is non-grounded AND carries no requirement-looking
citation (no fabricated requirement). One violation drops the metric
below 1.0 and fails the gate.
"""
from __future__ import annotations

import re

_NOT_FOUND_PREFIX = "not found in knowledge base"
_REQUIREMENT_RE = re.compile(
    r"(requirement\s*\d|\breq\s*\d|pci\s*dss)", re.IGNORECASE)
# The canonical signal of an expected requirement is its dotted number
# AFTER "Req"/"Requirement" — NOT the "v4.0" version token. The frozen
# gold writes "PCI DSS v4.0 Req 1.2.7"; corpus-grounded answers echo the
# corpus wording "PCI DSS v4.0 Requirement 1.2.7". Both cite the same
# requirement; coverage matches on the requirement number plus a PCI/
# requirement context word (so a bare number cannot match by accident).
_REQ_NUM_RE = re.compile(r"Req(?:uirement)?\s*([0-9]+(?:\.[0-9]+)+)", re.I)


def _prose(answer: str) -> str:
    # Score the answer prose only; a trailing "## Sources" block is
    # rendered citation text, not a model claim.
    return answer.split("## Sources", 1)[0]


def _requirement_number(expected: str) -> str | None:
    m = _REQ_NUM_RE.search(expected)
    return m.group(1) if m else None


def covers_requirement(answer: str, expected: str) -> bool:
    """The expected requirement is covered iff the answer PROSE cites it
    by its canonical dotted number directly after Req/Requirement, with
    the number bounded so 1.2.7 does not match 11.2.7 or 1.2.70. Accepts
    both the gold "Req" abbreviation and the corpus "Requirement"
    wording; the frozen gold and the >=0.90 bar are unchanged."""
    num = _requirement_number(expected)
    if not num:
        return False
    pat = re.compile(
        r"Req(?:uirement)?\s+" + re.escape(num) + r"(?![0-9.])", re.I)
    return bool(pat.search(_prose(answer)))


def is_not_found(answer: str) -> bool:
    # Exact mirror of crew._has_grounded_findings' non-grounded branch.
    text = answer.strip()
    return len(text) < 200 and text.lower().startswith(_NOT_FOUND_PREFIX)


def negative_is_honest(answer: str) -> bool:
    # Judge only the prose (a Sources block, if any, is not a claim);
    # an honest "not found" answer should carry no requirement citation.
    head = answer.split("## Sources")[0]
    if not is_not_found(head):
        return False
    if _REQUIREMENT_RE.search(head):
        return False
    return True


def not_found_honesty(negative_fixtures: list[dict]) -> float:
    if not negative_fixtures:
        return 0.0
    honest = sum(
        1 for fx in negative_fixtures
        if negative_is_honest(fx["system_answer"])
    )
    return honest / len(negative_fixtures)


def requirement_coverage(
    positive_fixtures_by_item: dict[str, dict],
    subset_ids: list[str],
    expected_by_id: dict[str, tuple[str, ...]],
) -> float:
    if not subset_ids:
        return 0.0
    per = []
    for sid in subset_ids:
        fx = positive_fixtures_by_item[sid]
        ans = fx["system_answer"]
        reqs = expected_by_id[sid]
        hit = sum(1 for r in reqs if covers_requirement(ans, r))
        per.append(hit / len(reqs) if reqs else 0.0)
    return sum(per) / len(per)
