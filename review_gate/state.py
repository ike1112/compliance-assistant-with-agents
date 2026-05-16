"""Loop state persisted at .claude/review-gate.state.json.

Survives restarts so the orchestrator loop is resumable: re-running
re-gates the current frozen diff rather than starting over.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

VALID_STATUS = {"building", "reviewing", "remediating", "passed", "halted"}


@dataclass
class GateState:
    phase: str
    base_sha: str
    round: int
    status: str
    findings_path: str | None


def load_state(path: Path) -> GateState | None:
    path = Path(path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return GateState(
        phase=str(data["phase"]),
        base_sha=str(data["base_sha"]),
        round=int(data["round"]),
        status=str(data["status"]),
        findings_path=data.get("findings_path"),
    )


def save_state(path: Path, state: GateState) -> None:
    if state.status not in VALID_STATUS:
        raise ValueError(f"unknown status {state.status!r}; expected {VALID_STATUS}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem


def init_state(path: Path, phase: str, base_sha: str) -> GateState:
    state = GateState(phase=phase, base_sha=base_sha, round=1,
                       status="building", findings_path=None)
    save_state(path, state)
    return state
