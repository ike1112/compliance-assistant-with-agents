"""Panel verdict aggregation (spec §3 step-6) and the PASS token.

Rule: test_integrity OR regression failing -> FAIL; codex/security/code
reporting BLOCKER or MAJOR -> FAIL; any of the five required legs missing
-> FAIL (a leg that did not run is never an implicit pass). The PASS token
is bound to the exact judged base SHA so `complete` cannot consume a stale
or builder-fabricated pass. Any verdict whose name is not a required leg
(e.g. "test_engineer") is advisory: kept in evidence, never blocking.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_LEGS = {"codex", "test_integrity", "security", "code", "regression"}
_BLOCKING_SEVERITY = {"MAJOR", "BLOCKER"}


@dataclass(frozen=True)
class Verdict:
    name: str
    passed: bool
    severity: str | None
    summary: str


@dataclass
class GateOutcome:
    passed: bool
    blocking: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def aggregate(verdicts: list[Verdict]) -> GateOutcome:
    by_name = {v.name: v for v in verdicts}
    blocking: list[str] = []

    for leg in sorted(REQUIRED_LEGS):
        if leg not in by_name:
            blocking.append(leg)  # missing leg never passes implicitly

    for name in ("test_integrity", "regression"):
        v = by_name.get(name)
        if v is not None and not v.passed:
            blocking.append(name)

    for name in ("codex", "security", "code"):
        v = by_name.get(name)
        if v is not None and v.severity in _BLOCKING_SEVERITY:
            blocking.append(name)

    blocking = sorted(set(blocking))
    evidence = {v.name: {"passed": v.passed, "severity": v.severity,
                          "summary": v.summary} for v in verdicts}
    return GateOutcome(passed=not blocking, blocking=blocking,
                       evidence=evidence)


def write_outcome_token(path: Path, base_sha: str, phase: str,
                        outcome: GateOutcome) -> None:
    Path(path).write_text(json.dumps({
        "base_sha": base_sha,
        "phase": phase,
        "passed": outcome.passed,
        "ts": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")
