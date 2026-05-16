"""flip_phase_complete: the single chokepoint that marks a phase done."""
import pytest

from review_gate.prd import PrdError, flip_phase_complete

_PRD = """\
## Implementation Phases

| # | Phase (intent) | Depends on | Status | PRP Plan | Closes gaps |
|---|----------------|-----------|--------|----------|-------------|
| 1 | Bedrock layer | — | in-progress | `p1` | GAP-X |
| 2 | Config harden | — | pending | _(none)_ | GAP-Y |

## Progress Log

- 2026-05-15 — PRD created.

## Success Criteria (per phase, machine-checkable)
"""


def test_flips_status_and_appends_log(tmp_path):
    p = tmp_path / "prd.md"
    p.write_text(_PRD, encoding="utf-8")
    flip_phase_complete(p, phase="2",
                         evidence={"mutation": "0.91", "codex": "PASS"})
    out = p.read_text(encoding="utf-8")
    assert "| 2 | Config harden | — | complete | _(none)_ | GAP-Y |" in out
    # untouched row stays intact
    assert "| 1 | Bedrock layer | — | in-progress | `p1` | GAP-X |" in out
    # one appended progress line carrying evidence, under Progress Log
    log_idx = out.index("## Progress Log")
    crit_idx = out.index("## Success Criteria")
    block = out[log_idx:crit_idx]
    assert "phase 2 -> complete" in block
    assert "mutation=0.91" in block and "codex=PASS" in block


def test_unknown_phase_raises(tmp_path):
    p = tmp_path / "prd.md"
    p.write_text(_PRD, encoding="utf-8")
    with pytest.raises(PrdError):
        flip_phase_complete(p, phase="9", evidence={})


def test_already_complete_is_idempotent_raise(tmp_path):
    p = tmp_path / "prd.md"
    p.write_text(_PRD.replace("| 2 | Config harden | — | pending",
                              "| 2 | Config harden | — | complete"),
                 encoding="utf-8")
    with pytest.raises(PrdError):
        flip_phase_complete(p, phase="2", evidence={})
