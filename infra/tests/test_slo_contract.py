"""Fail-closed contract for the SLO parser.

`parse_slos` is the single-source-of-truth reader the observability
stack and its synth-contract test both depend on. It must reject every
ambiguous table shape with `ValueError` at synth (mirrors kb_stack's
fail-closed-on-bad-context), never silently ship a mismatched alarm set.
Each guard is exercised here so a regression that softens one is caught.
"""
import textwrap

import pytest

from stacks.slo_contract import COMPARATORS, SLO, SLOS_MD, parse_slos


@pytest.mark.parametrize("key,expected", sorted(COMPARATORS.items()))
def test_every_comparator_maps_to_its_cdk_operator(key, expected):
    # The real SLOs.md uses only gt/lt; assert ALL four keys map
    # correctly so a gte/lte mapping regression cannot stay dark.
    slo = SLO(
        slo_id="s", description="d", namespace="n", metric="m",
        statistic="Average", period_s=300, eval_periods=1,
        comparator=key, threshold=1.0, error_budget_30d="1%",
    )
    assert slo.comparison_operator == expected
    assert expected in {
        "GreaterThanThreshold", "GreaterThanOrEqualToThreshold",
        "LessThanThreshold", "LessThanOrEqualToThreshold",
    }

_HEADER = (
    "| slo_id | description | namespace | metric | statistic | "
    "period_s | eval_periods | comparator | threshold | error_budget_30d |"
)
_SEP = "|---|---|---|---|---|---|---|---|---|---|"
_GOOD = (
    "| s1 | d | ComplianceAssistant/Crew | M | Average | 300 | 1 | lt "
    "| 0.95 | 1% |"
)


def _md(*rows: str) -> str:
    return "\n".join(("# SLOs", "", _HEADER, _SEP, *rows)) + "\n"


def _write(tmp_path, text: str):
    p = tmp_path / "SLOs.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_the_real_contract_parses():
    slos = parse_slos(SLOS_MD)
    assert len(slos) >= 6
    s = slos[0]
    assert s.namespace and s.metric and s.error_budget_30d
    assert 0 <= s.period_s and s.eval_periods >= 1
    assert s.comparison_operator in {
        "GreaterThanThreshold", "GreaterThanOrEqualToThreshold",
        "LessThanThreshold", "LessThanOrEqualToThreshold",
    }


def test_missing_file_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        parse_slos(tmp_path / "nope.md")


def test_no_header_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="header not found"):
        parse_slos(_write(tmp_path, "# SLOs\n\njust prose, no table\n"))


def test_no_data_rows_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="no data rows"):
        parse_slos(_write(tmp_path, _md()))


def test_wrong_cell_count_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="expected"):
        parse_slos(_write(tmp_path, _md("| s1 | only | three |")))


def test_duplicate_slo_id_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        parse_slos(_write(tmp_path, _md(_GOOD, _GOOD)))


def test_unknown_comparator_fails_closed(tmp_path):
    bad = _GOOD.replace("| lt |", "| approx |")
    with pytest.raises(ValueError, match="comparator"):
        parse_slos(_write(tmp_path, _md(bad)))


def test_non_numeric_field_fails_closed(tmp_path):
    bad = _GOOD.replace("| 300 |", "| soon |")
    with pytest.raises(ValueError, match="non-numeric"):
        parse_slos(_write(tmp_path, _md(bad)))


def test_missing_metric_fields_fail_closed(tmp_path):
    bad = (
        "| s1 | d |  |  | Average | 300 | 1 | lt | 0.95 | 1% |"
    )
    with pytest.raises(ValueError, match="namespace/metric/statistic"):
        parse_slos(_write(tmp_path, _md(bad)))


def test_missing_error_budget_fails_closed(tmp_path):
    bad = (
        "| s1 | d | ComplianceAssistant/Crew | M | Average | 300 | 1 "
        "| lt | 0.95 |  |"
    )
    with pytest.raises(ValueError, match="error_budget_30d"):
        parse_slos(_write(tmp_path, _md(bad)))


def test_empty_slo_id_fails_closed(tmp_path):
    bad = (
        "|  | d | ComplianceAssistant/Crew | M | Average | 300 | 1 | lt "
        "| 0.95 | 1% |"
    )
    with pytest.raises(ValueError, match="missing or duplicate"):
        parse_slos(_write(tmp_path, _md(bad)))
