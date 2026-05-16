"""CLI exit-code contract: 0 ok/PASS, 1 gate-FAIL, 2 usage/IO.
The `complete` chokepoint refuses to flip the PRD without an independent
PASS token bound to the current state's base SHA."""
import json
import subprocess
import sys

import pytest

from review_gate import cli
from review_gate.state import init_state, load_state


def _git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True,
                    capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".claude").mkdir()
    (tmp_path / "seed.txt").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def _run(repo, *argv) -> int:
    return cli.main([*argv, "--repo", str(repo)])


def test_init_pins_sha_and_writes_state(repo):
    assert _run(repo, "init", "--phase", "2") == 0
    st = load_state(repo / ".claude" / "review-gate.state.json")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    assert st.base_sha == head and st.phase == "2" and st.round == 1


def test_complete_refuses_without_pass_token(repo):
    _run(repo, "init", "--phase", "2")
    # No outcome token written -> chokepoint must refuse with usage/IO code.
    assert _run(repo, "complete", "--phase", "2") == 2
    st = load_state(repo / ".claude" / "review-gate.state.json")
    assert st.status != "passed"


def test_complete_refuses_token_for_other_sha(repo):
    _run(repo, "init", "--phase", "2")
    tok = repo / ".claude" / "review-gate.last-outcome.json"
    tok.write_text(json.dumps({"base_sha": "WRONG", "phase": "2",
                               "passed": True, "ts": "t"}), encoding="utf-8")
    assert _run(repo, "complete", "--phase", "2") == 2


def test_unknown_subcommand_is_usage_error(repo):
    assert _run(repo, "bogus") == 2
