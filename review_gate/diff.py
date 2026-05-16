"""Frozen-diff window for a gate run.

The base SHA is pinned once per phase (persisted in gate state) and never
recomputed across remediation rounds, so accumulated work is always judged
whole. integrity_violations() blocks the "edit the bar to pass" move:
if a protected path (the config file, the declared pure-logic list, or a
frozen fixture/gold set) was modified inside the diff being judged, that
is a hard finding.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True,
        capture_output=True, text=True,
    ).stdout


def pin_base_sha(repo: Path) -> str:
    return _git(Path(repo), "rev-parse", "HEAD").strip()


def changed_files(repo: Path, base_sha: str) -> list[str]:
    """Every path that differs from base_sha by ANY means: committed since
    base, staged, unstaged-tracked, or untracked. The unstaged/staged legs
    are load-bearing for the anti-gaming guarantee — without them a builder
    could edit a tracked protected file (the bar, a frozen fixture) in the
    working tree, leave it uncommitted, and the integrity check would miss
    it. codex treats untracked files as reviewable work, so we do too."""
    repo = Path(repo)
    committed = _git(repo, "diff", "--name-only", f"{base_sha}..HEAD")
    unstaged = _git(repo, "diff", "--name-only")
    staged = _git(repo, "diff", "--name-only", "--cached")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard")
    out: list[str] = []
    for blob in (committed, unstaged, staged, untracked):
        out.extend(line.strip() for line in blob.splitlines() if line.strip())
    return sorted(set(out))


def _is_under(candidate: str, protected: str) -> bool:
    """protected may be a file ('a/b.py') or a dir prefix ('a/b/')."""
    candidate = candidate.replace("\\", "/").strip("/")
    protected = protected.replace("\\", "/").strip("/")
    return candidate == protected or candidate.startswith(protected + "/")


def integrity_violations(
    repo: Path, base_sha: str, protected_paths: list[str]
) -> list[str]:
    changed = changed_files(repo, base_sha)
    hits: list[str] = []
    for prot in protected_paths:
        if any(_is_under(c, prot) for c in changed):
            hits.append(prot)
    return hits
