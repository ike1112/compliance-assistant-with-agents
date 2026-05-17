"""not-found-honesty is binary and mirrors the exact crew predicate;
requirement-coverage counts expected requirement ids in the answer.
"""
from tests.evals.harness import task_metrics as TM


def test_is_not_found_exact_crew_predicate():
    assert TM.is_not_found("Not found in knowledge base") is True
    assert TM.is_not_found("  not found in knowledge base.  ") is True
    # >= 200 chars must NOT count as not-found (mirrors len < 200)
    assert TM.is_not_found("Not found in knowledge base " + "x" * 200) is False
    assert TM.is_not_found("The answer is X. Not found...") is False


def test_negative_is_honest_rejects_fabricated_requirement():
    assert TM.negative_is_honest("Not found in knowledge base") is True
    assert TM.negative_is_honest(
        "Not found in knowledge base, but see PCI DSS Req 2.2") is False


def test_not_found_honesty_is_one_only_if_all_honest():
    honest = [{"system_answer": "Not found in knowledge base"}]
    assert TM.not_found_honesty(honest) == 1.0
    mixed = honest + [{"system_answer": "Requirement 9.1 says use badges"}]
    assert TM.not_found_honesty(mixed) == 0.5
    assert TM.not_found_honesty([]) == 0.0


def test_covers_requirement_matches_req_or_requirement_spelling():
    # Gold uses the "Req" abbreviation; corpus-grounded answers echo the
    # corpus "Requirement" wording. Both cite the same requirement.
    exp = "PCI DSS v4.0 Req 1.2.7"
    assert TM.covers_requirement(
        "... reviewed every six months. PCI DSS v4.0 Requirement 1.2.7",
        exp) is True
    assert TM.covers_requirement("PCI DSS Req 1.2.7 applies", exp) is True
    # bare number without PCI/requirement context must NOT match
    assert TM.covers_requirement("the value 1.2.7 appears alone", exp) is False
    # wrong / missing number must NOT match
    assert TM.covers_requirement("PCI DSS Requirement 9.9.9", exp) is False


def test_requirement_coverage_counts_expected_ids():
    pos_fx = {
        "pos-a": {"system_answer": "see PCI DSS v4.0 Requirement 3.5.1 here"},
        "pos-b": {"system_answer": "no id present at all"},
    }
    expected = {"pos-a": ("PCI DSS v4.0 Req 3.5.1",),
                "pos-b": ("PCI DSS v4.0 Req 8.2.1",)}
    cov = TM.requirement_coverage(pos_fx, ["pos-a", "pos-b"], expected)
    assert cov == 0.5
    assert TM.requirement_coverage(pos_fx, [], expected) == 0.0
