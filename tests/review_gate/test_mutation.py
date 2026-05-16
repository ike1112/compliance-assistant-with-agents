"""parse_mutmut_results: objective kill-rate from `mutmut results` text.
The live runner is the integration seam; this parser is the unit-tested
anti-gaming core (a weakened assertion lowers kill-rate -> hard fail)."""
import pytest

from review_gate.mutation import (
    MutationResult,
    meets_floor,
    parse_mutmut_results,
)

_RESULTS = """\

To apply a mutant on disk:
    mutmut apply <id>

1: killed
2: killed
3: timeout
4: suspicious
5: survived
6: skipped
"""


def test_parses_counts_and_rate():
    r = parse_mutmut_results(_RESULTS)
    assert isinstance(r, MutationResult)
    assert r.killed == 4          # killed + timeout + suspicious
    assert r.survived == 1
    assert r.skipped == 1
    assert r.total == 5           # skipped excluded from denominator
    assert r.kill_rate == pytest.approx(0.8)


def test_all_killed_is_rate_one():
    r = parse_mutmut_results("1: killed\n2: killed\n")
    assert r.kill_rate == 1.0


def test_no_mutants_raises_not_silent_pass():
    # An empty result must NOT read as a free pass.
    with pytest.raises(ValueError):
        parse_mutmut_results("\nNo mutants found\n")


def test_unparseable_raises():
    with pytest.raises(ValueError):
        parse_mutmut_results("totally unexpected output")


def test_meets_floor_boundary():
    r = parse_mutmut_results("1: killed\n2: killed\n3: killed\n4: survived\n")
    assert r.kill_rate == pytest.approx(0.75)
    assert meets_floor(r, 0.75) is True
    assert meets_floor(r, 0.7500001) is False
