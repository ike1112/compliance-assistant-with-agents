"""Gate loop state: atomic, resumable, single source of loop truth."""
import pytest

from review_gate.state import GateState, init_state, load_state, save_state


def test_load_missing_returns_none(tmp_path):
    assert load_state(tmp_path / "s.json") is None


def test_init_then_load_roundtrips(tmp_path):
    p = tmp_path / "s.json"
    st = init_state(p, phase="3", base_sha="abc123")
    assert st == GateState("3", "abc123", 1, "building", None)
    assert load_state(p) == st


def test_save_overwrites_atomically(tmp_path):
    p = tmp_path / "s.json"
    init_state(p, phase="3", base_sha="abc123")
    st = GateState("3", "abc123", 2, "remediating", ".claude/findings-3.md")
    save_state(p, st)
    assert load_state(p) == st
    assert not list(tmp_path.glob("*.tmp"))  # temp file cleaned up


def test_rejects_unknown_status(tmp_path):
    with pytest.raises(ValueError):
        save_state(tmp_path / "s.json", GateState("3", "a", 1, "bogus", None))
