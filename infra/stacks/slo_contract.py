"""The SLO contract: parse `docs/SLOs.md` into structured records.

`docs/SLOs.md` is the single source of truth. The observability stack
derives exactly one CloudWatch alarm per SLO, bound to the SLO's real
metric, and the synth-contract test re-parses the same file and
cross-checks the synthesized template against these records. The parse
is deterministic and fail-closed: a malformed, empty, or
duplicate-id table raises `ValueError` at synth (mirrors the kb_stack
fail-closed-on-bad-context pattern) rather than silently shipping a
mismatched alarm set.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Repo root, anchored to this module (not the process cwd), so `cdk`
# (run from infra/) and pytest (run from the repo root) both resolve
# docs/SLOs.md identically — mirrors how kb_stack anchors asset paths.
_REPO_ROOT = Path(__file__).resolve().parents[2]
SLOS_MD = _REPO_ROOT / "docs" / "SLOs.md"

# The comparator vocabulary the table may use → CDK ComparisonOperator
# names. Kept here so the stack and the test agree on one mapping.
COMPARATORS = {
    "gt": "GreaterThanThreshold",
    "gte": "GreaterThanOrEqualToThreshold",
    "lt": "LessThanThreshold",
    "lte": "LessThanOrEqualToThreshold",
}

_COLUMNS = (
    "slo_id", "description", "namespace", "metric", "statistic",
    "period_s", "eval_periods", "comparator", "threshold",
    "error_budget_30d",
)


@dataclass(frozen=True)
class SLO:
    slo_id: str
    description: str
    namespace: str
    metric: str
    statistic: str
    period_s: int
    eval_periods: int
    comparator: str          # one of COMPARATORS keys
    threshold: float
    error_budget_30d: str

    @property
    def comparison_operator(self) -> str:
        return COMPARATORS[self.comparator]


def _split_row(line: str) -> list[str]:
    # A markdown table row: leading/trailing pipe, cells pipe-separated.
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return cells


def parse_slos(path: str | Path = SLOS_MD) -> list[SLO]:
    """Parse the SLO table. Fail-closed on anything ambiguous."""
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"SLOs contract not found: {p}")
    rows: list[list[str]] = []
    header_seen = False
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = _split_row(line)
        if not header_seen:
            if [c.lower() for c in cells] == list(_COLUMNS):
                header_seen = True
            continue
        if set(cells) <= {"", *("-" * n for n in range(1, 40))} or all(
            set(c) <= {"-", ":"} for c in cells
        ):
            continue  # the |---|---| separator row
        rows.append(cells)
    if not header_seen:
        raise ValueError(
            f"{p}: SLO table header not found; expected columns {_COLUMNS}"
        )
    if not rows:
        raise ValueError(f"{p}: SLO table has no data rows")

    slos: list[SLO] = []
    seen: set[str] = set()
    for cells in rows:
        if len(cells) != len(_COLUMNS):
            raise ValueError(
                f"{p}: SLO row has {len(cells)} cells, expected "
                f"{len(_COLUMNS)}: {cells}"
            )
        rec = dict(zip(_COLUMNS, cells))
        sid = rec["slo_id"]
        if not sid or sid in seen:
            raise ValueError(f"{p}: missing or duplicate slo_id {sid!r}")
        seen.add(sid)
        if rec["comparator"] not in COMPARATORS:
            raise ValueError(
                f"{p}: slo {sid}: comparator {rec['comparator']!r} not in "
                f"{sorted(COMPARATORS)}"
            )
        try:
            period_s = int(rec["period_s"])
            eval_periods = int(rec["eval_periods"])
            threshold = float(rec["threshold"])
        except ValueError as exc:
            raise ValueError(f"{p}: slo {sid}: non-numeric field ({exc})")
        if not (rec["namespace"] and rec["metric"] and rec["statistic"]):
            raise ValueError(
                f"{p}: slo {sid}: namespace/metric/statistic required"
            )
        if not rec["error_budget_30d"]:
            raise ValueError(f"{p}: slo {sid}: error_budget_30d required")
        slos.append(
            SLO(
                slo_id=sid,
                description=rec["description"],
                namespace=rec["namespace"],
                metric=rec["metric"],
                statistic=rec["statistic"],
                period_s=period_s,
                eval_periods=eval_periods,
                comparator=rec["comparator"],
                threshold=threshold,
                error_budget_30d=rec["error_budget_30d"],
            )
        )
    return slos
