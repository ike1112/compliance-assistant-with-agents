"""Phase-3 anti-bootstrap rule: ralph may not author its own ground truth.
The eval gold set must be owner-seeded or codex-authored, committed before
the harness, and untouched by the judged diff."""
import subprocess

import pytest

from review_gate.provenance import GOLD_MARKER, verify_gold_provenance


def _git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True,
                    capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "seed.txt").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def _commit_marker(repo, author):
    d = repo / "tests" / "evals" / "gold"
    d.mkdir(parents=True, exist_ok=True)
    (d / "PROVENANCE.md").write_text(
        f"author: {author}\ncommitted-before-harness: true\n",
        encoding="utf-8",
    )
    (d / "q001.json").write_text('{"q": "..."}', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed gold set")


def test_valid_owner_marker_untouched_passes(repo):
    _commit_marker(repo, "owner")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    (repo / "harness.py").write_text("pass\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "harness only")
    r = verify_gold_provenance(repo, base)
    assert r.ok is True


def test_missing_marker_fails(repo):
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    r = verify_gold_provenance(repo, base)
    assert r.ok is False
    assert "marker" in r.reason.lower()


def test_unapproved_author_fails(repo):
    _commit_marker(repo, "ralph")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    r = verify_gold_provenance(repo, base)
    assert r.ok is False
    assert "author" in r.reason.lower()


def test_gold_modified_in_judged_diff_fails(repo):
    _commit_marker(repo, "codex")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    # ralph tampers with ground truth inside the diff being judged
    (repo / "tests" / "evals" / "gold" / "q001.json").write_text(
        '{"q": "edited to pass"}', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "oops touched gold")
    r = verify_gold_provenance(repo, base)
    assert r.ok is False
    assert "modified" in r.reason.lower()


def test_marker_constant_points_at_gold_dir():
    assert GOLD_MARKER == "tests/evals/gold/PROVENANCE.md"
