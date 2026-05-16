"""Load and validate the quality-gate bar file.

The thresholds and the per-phase pure-logic / frozen-fixture path lists
live in a tracked JSON file so any change to the bar shows up in the diff
the gate judges (see review_gate.diff integrity check).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class GateConfigError(Exception):
    """Config file is missing, malformed, or schema-invalid."""


@dataclass(frozen=True)
class PhaseConfig:
    pure_logic_paths: list[str]
    frozen_fixture_paths: list[str]
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

        def _opt_floor(key: str) -> float | None:
            if key not in pc:
                return None
            return _float_in_unit(pc, key)  # validated in [0,1] or raises

        phases[str(phase_id)] = PhaseConfig(
            pure_logic_paths=[str(x) for x in pc["pure_logic_paths"]],
            frozen_fixture_paths=[str(x) for x in pc["frozen_fixture_paths"]],
            mutation_floor=_opt_floor("mutation_floor"),
            coverage_floor=_opt_floor("coverage_floor"),
        )

    return GateConfig(mutation_floor, coverage_floor, phases)
