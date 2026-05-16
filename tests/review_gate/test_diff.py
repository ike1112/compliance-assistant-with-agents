"""Frozen diff: pin a base SHA; detect tampering with the bar/fixtures
inside the very diff being judged."""
import subprocess

import pytest

from review_gate import diff


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                    capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "keep.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def test_pin_base_sha_is_head(repo):
    sha = diff.pin_base_sha(repo)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    assert sha == head


def test_changed_files_includes_committed_and_untracked(repo):
    base = diff.pin_base_sha(repo)
    (repo / "new_tracked.py").write_text("x=1\n", encoding="utf-8")
    _git(repo, "add", "new_tracked.py")
    _git(repo, "commit", "-q", "-m", "work")
    (repo / "untracked.py").write_text("y=2\n", encoding="utf-8")
    changed = set(diff.changed_files(repo, base))
    assert "new_tracked.py" in changed
    assert "untracked.py" in changed


def test_integrity_flags_protected_path_touched_in_diff(repo):
    base = diff.pin_base_sha(repo)
    (repo / "guarded.json").write_text("{}", encoding="utf-8")
    _git(repo, "add", "guarded.json")
    _git(repo, "commit", "-q", "-m", "moved the bar")
    violations = diff.integrity_violations(repo, base, ["guarded.json", "safe.py"])
    assert violations == ["guarded.json"]


def test_integrity_clean_when_protected_untouched(repo):
    base = diff.pin_base_sha(repo)
    (repo / "feature.py").write_text("z=3\n", encoding="utf-8")
    _git(repo, "add", "feature.py")
    _git(repo, "commit", "-q", "-m", "feature only")
    assert diff.integrity_violations(repo, base, ["guarded.json"]) == []
