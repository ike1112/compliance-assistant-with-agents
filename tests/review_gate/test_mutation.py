"""parse_mutmut_results: objective kill-rate from `mutmut run`'s
summary counters (mutmut 2.5.1). The live runner is the integration
seam; this parser is the unit-tested anti-gaming core (a weakened
assertion lowers kill-rate -> hard fail). Fixtures are real 2.5.1
summary lines: `<done>/<planned>  🎉 k  ⏰ t  🤔 s  🙁 su  🔇 sk`
(killed/timeout/suspicious are caught; skipped excluded)."""
import pytest

from review_gate.mutation import (
    MutationResult,
    meets_floor,
    parse_mutmut_results,
)

# Repainted via CR mid-run; the final done==planned line is authoritative.
_RUN = (
    "⢹ 2/6  \U0001F389 1  \U000023F0 0  \U0001F914 0  "
    "\U0001F641 1  \U0001F507 0\r"
    "⢹ 6/6  \U0001F389 3  \U000023F0 1  \U0001F914 0  "
    "\U0001F641 1  \U0001F507 1\r\n"
)


def test_parses_counts_and_rate():
    r = parse_mutmut_results(_RUN)
    assert isinstance(r, MutationResult)
    assert r.killed == 4          # killed + timeout + suspicious (3+1+0)
    assert r.survived == 1
    assert r.skipped == 1
    assert r.total == 5           # skipped excluded from denominator
    assert r.kill_rate == pytest.approx(0.8)


def test_all_killed_is_rate_one():
    r = parse_mutmut_results(
        "2/2  \U0001F389 2  \U000023F0 0  \U0001F914 0  "
        "\U0001F641 0  \U0001F507 0"
    )
    assert r.kill_rate == 1.0


def test_no_summary_raises_not_silent_pass():
    with pytest.raises(ValueError):
        parse_mutmut_results("\nNo mutants found\n")


def test_unparseable_raises():
    with pytest.raises(ValueError):
        parse_mutmut_results("totally unexpected output")


def test_incomplete_run_raises_not_silent_pass():
    # done != planned: a crashed/partial run must never read as a pass.
    with pytest.raises(ValueError):
        parse_mutmut_results(
            "3/6  \U0001F389 3  \U000023F0 0  \U0001F914 0  "
            "\U0001F641 0  \U0001F507 0"
        )


def test_all_skipped_raises():
    with pytest.raises(ValueError):
        parse_mutmut_results(
            "2/2  \U0001F389 0  \U000023F0 0  \U0001F914 0  "
            "\U0001F641 0  \U0001F507 2"
        )


def test_meets_floor_boundary():
    r = parse_mutmut_results(
        "4/4  \U0001F389 3  \U000023F0 0  \U0001F914 0  "
        "\U0001F641 1  \U0001F507 0"
    )
    assert r.kill_rate == pytest.approx(0.75)
    assert meets_floor(r, 0.75) is True
    assert meets_floor(r, 0.7500001) is False
