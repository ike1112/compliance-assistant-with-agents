"""Objective test-integrity leg: mutation kill-rate vs a configured floor.

Parsing is isolated from running so the anti-gaming core is unit-tested
with captured `mutmut results` text. mutmut==2.5.1 is pinned so this
line contract is stable. Any deviation raises (FAIL closed) — the gate
never reads ambiguous mutation output as a pass.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_LINE = re.compile(r"^\s*\d+:\s*(killed|timeout|suspicious|survived|skipped)\s*$")
_CAUGHT = {"killed", "timeout", "suspicious"}


@dataclass(frozen=True)
class MutationResult:
    killed: int
    survived: int
    skipped: int
    total: int        # killed + survived (skipped excluded)
    kill_rate: float


def parse_mutmut_results(text: str) -> MutationResult:
    killed = survived = skipped = 0
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        status = m.group(1)
        if status in _CAUGHT:
            killed += 1
        elif status == "survived":
            survived += 1
        else:
            skipped += 1

    total = killed + survived
    if total == 0:
        raise ValueError(
            "no scored mutants parsed from mutmut output; refusing to "
            "treat as a pass"
        )
    return MutationResult(
        killed=killed, survived=survived, skipped=skipped,
        total=total, kill_rate=killed / total,
    )


def meets_floor(result: MutationResult, floor: float) -> bool:
    return result.kill_rate >= floor


def run_mutation(repo: Path, paths: list[str], runner: str) -> MutationResult:
    """Integration seam (not in the gate's own unit suite). Runs mutmut on
    the declared pure-logic paths and parses the result. A missing declared
    path or a mutmut crash raises -> caller treats as gate FAIL."""
    repo = Path(repo)
    for p in paths:
        if not (repo / p).exists():
            raise FileNotFoundError(
                f"declared pure-logic path missing, cannot gate: {p}"
            )
    subprocess.run(
        ["mutmut", "run", "--paths-to-mutate", ",".join(paths),
         "--runner", runner],
        cwd=str(repo), check=False, capture_output=True, text=True,
    )
    results = subprocess.run(
        ["mutmut", "results"], cwd=str(repo), check=True,
        capture_output=True, text=True,
    ).stdout
    return parse_mutmut_results(results)
