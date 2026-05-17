"""Load and validate the quality-gate bar file.

The thresholds and the per-phase pure-logic / frozen-fixture path lists
live in a tracked JSON file so any change to the bar shows up in the diff
the gate judges (see review_gate.diff integrity check).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class GateConfigError(Exception):
    """Config file is missing, malformed, or schema-invalid."""


@dataclass(frozen=True)
class PhaseConfig:
    pure_logic_paths: list[str]
    frozen_fixture_paths: list[str]
    # Optional explicit kill-surface test files for the mutation leg.
    # The default discovery assumes the src-layout tests/test_<stem>.py
    # convention; a phase whose pure-logic module lives outside that
    # layout (e.g. an infra-layout module under infra/) declares its
    # test file(s) here so the mutation leg runs the right, fast,
    # importing suite instead of the wrong fallback. Empty => use the
    # tests/test_<stem>.py convention.
    pure_logic_tests: list[str] = field(default_factory=list)
    # Explicit, owner-only mutation exemption. A phase whose only
    # pure-logic module is mutmut-hostile (e.g. a threaded async shim
    # whose deadlocking mutants hang the runner with no reaping on the
    # host OS) can be exempted from the mutation sub-leg. This is NOT a
    # silent skip: it must be declared in the integrity-protected bar
    # file with a rationale, so it shows up in the judged diff and is an
    # owner act, never the builder's. An undeclared phase with no
    # pure_logic_paths still HALTs (anti-gaming invariant preserved).
    mutation_exempt: bool = False
    mutation_exempt_reason: str = ""
    # Optional per-phase overrides of the global floors. A phase whose
    # pure-logic module is defensive I/O glue (equivalent-mutant heavy)
    # can carry a lower, owner-set mutation bar without weakening the
    # global default. None => use the global floor.
    mutation_floor: float | None = None
    coverage_floor: float | None = None

    def mutation_bar(self, default: float) -> float:
        return self.mutation_floor if self.mutation_floor is not None else default

    def coverage_bar(self, default: float) -> float:
        return self.coverage_floor if self.coverage_floor is not None else default


@dataclass(frozen=True)
class GateConfig:
    mutation_floor: float
    coverage_floor: float
    phases: dict[str, PhaseConfig]


def _float_in_unit(obj: dict, key: str) -> float:
    if key not in obj or not isinstance(obj[key], (int, float)):
        raise GateConfigError(f"missing or non-numeric '{key}'")
    val = float(obj[key])
    if not 0.0 <= val <= 1.0:
        raise GateConfigError(f"'{key}' must be within [0.0, 1.0], got {val}")
    return val


def load_config(path: Path) -> GateConfig:
    path = Path(path)
    if not path.is_file():
        raise GateConfigError(f"config file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise GateConfigError(f"cannot parse {path}: {exc}") from exc

    mutation_floor = _float_in_unit(raw, "mutation_floor")
    coverage_floor = _float_in_unit(raw, "coverage_floor")

    phases_raw = raw.get("phases")
    if not isinstance(phases_raw, dict):
        raise GateConfigError("'phases' must be an object")

    phases: dict[str, PhaseConfig] = {}
    for phase_id, pc in phases_raw.items():
        if not isinstance(pc, dict) or "pure_logic_paths" not in pc \
                or "frozen_fixture_paths" not in pc:
            raise GateConfigError(
                f"phase '{phase_id}' needs pure_logic_paths and frozen_fixture_paths"
            )
        if not isinstance(pc["pure_logic_paths"], list) \
                or not isinstance(pc["frozen_fixture_paths"], list):
            raise GateConfigError(f"phase '{phase_id}' path entries must be lists")
        plt = pc.get("pure_logic_tests", [])
        if not isinstance(plt, list):
            raise GateConfigError(
                f"phase '{phase_id}' pure_logic_tests must be a list"
            )
        mut_exempt = pc.get("mutation_exempt", False)
        if not isinstance(mut_exempt, bool):
            raise GateConfigError(
                f"phase '{phase_id}' mutation_exempt must be a boolean"
            )
        mut_exempt_reason = pc.get("mutation_exempt_reason", "")
        if mut_exempt and not str(mut_exempt_reason).strip():
            raise GateConfigError(
                f"phase '{phase_id}' mutation_exempt requires a non-empty "
                f"mutation_exempt_reason"
            )

        def _opt_floor(key: str) -> float | None:
            if key not in pc:
                return None
            return _float_in_unit(pc, key)  # validated in [0,1] or raises

        phases[str(phase_id)] = PhaseConfig(
            pure_logic_paths=[str(x) for x in pc["pure_logic_paths"]],
            frozen_fixture_paths=[str(x) for x in pc["frozen_fixture_paths"]],
            pure_logic_tests=[str(x) for x in plt],
            mutation_exempt=mut_exempt,
            mutation_exempt_reason=str(mut_exempt_reason),
            mutation_floor=_opt_floor("mutation_floor"),
            coverage_floor=_opt_floor("coverage_floor"),
        )

    return GateConfig(mutation_floor, coverage_floor, phases)
