"""Provenance guard: the frozen gold tree must be byte-identical to its
committed git blobs, with no added / moved / modified / untracked files.
Bidirectional — catches the builder writing, normalizing, or adding
anything under tests/evals/gold/.
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GOLD = "tests/evals/gold"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), text=True, capture_output=True,
        check=True).stdout


def test_no_uncommitted_changes_under_gold():
    porcelain = _git("status", "--porcelain", "--", GOLD).strip()
    assert porcelain == "", (
        f"gold tree has uncommitted changes (added/modified/moved):\n"
        f"{porcelain}")


def test_tracked_fileset_matches_head_and_bytes_identical():
    tracked = sorted(
        line for line in _git(
            "ls-tree", "-r", "--name-only", "HEAD", "--", GOLD
        ).splitlines() if line.strip()
    )
    assert tracked, "no tracked gold files at HEAD"

    on_disk = sorted(
        str(p.relative_to(REPO)).replace("\\", "/")
        for p in (REPO / GOLD).rglob("*") if p.is_file()
    )
    assert on_disk == tracked, (
        f"working-tree gold fileset != HEAD\n"
        f"only on disk: {set(on_disk) - set(tracked)}\n"
        f"only at HEAD: {set(tracked) - set(on_disk)}")

    for rel in tracked:
        blob = subprocess.run(
            ["git", "show", f"HEAD:{rel}"], cwd=str(REPO),
            capture_output=True, check=True).stdout
        disk = (REPO / rel).read_bytes()
        assert disk == blob, f"{rel} differs from its committed blob"
