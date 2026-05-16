"""Objective test-integrity leg: mutation kill-rate vs a configured floor.

Parsing is isolated from running so the anti-gaming core is unit-tested
with captured mutmut output. mutmut==2.5.1 is pinned so the contract is
stable. Any deviation raises (FAIL closed) — the gate never reads
ambiguous mutation output as a pass.

Format note (mutmut 2.5.1): `mutmut results` only enumerates the
*non-killed* mutants in ranged groups, so the killed count is not
derivable from it. The authoritative counts are the run-summary
counters emitted by `mutmut run`:

    35/35  🎉 23  ⏰ 0  🤔 1  🙁 11  🔇 0
           killed  timeout suspicious survived skipped

(the line is repainted via CR many times; the final occurrence with
done == planned is authoritative). killed/timeout/suspicious are
"caught"; skipped is excluded from the denominator.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# done/planned then the five emoji counters, in mutmut 2.5.1's order.
_SUMMARY = re.compile(
    r"(\d+)\s*/\s*(\d+)\s+"
    r"\U0001F389\s*(\d+)\s+"   # 🎉 killed
    r"\U000023F0\s*(\d+)\s+"   # ⏰ timeout
    r"\U0001F914\s*(\d+)\s+"   # 🤔 suspicious
    r"\U0001F641\s*(\d+)\s+"   # 🙁 survived
    r"\U0001F507\s*(\d+)"      # 🔇 skipped
)


@dataclass(frozen=True)
class MutationResult:
    killed: int
    survived: int
    skipped: int
    total: int        # killed + survived (skipped excluded)
    kill_rate: float


def parse_mutmut_results(text: str) -> MutationResult:
    """Parse the authoritative run-summary counters from `mutmut run`
    output. Raises (FAIL closed) on absent counters or an incomplete
    run (done != planned) so a crashed/partial run is never a pass."""
    matches = list(_SUMMARY.finditer(text))
    if not matches:
        raise ValueError(
            "no mutmut run-summary counters parsed; refusing to treat "
            "as a pass"
        )
    done, planned, killed, timeout, suspicious, survived, skipped = (
        int(g) for g in matches[-1].groups()
    )
    if done != planned or planned == 0:
        raise ValueError(
            f"mutmut run incomplete ({done}/{planned}); refusing to "
            f"treat as a pass"
        )
    caught = killed + timeout + suspicious
    total = caught + survived          # skipped excluded from denominator
    if total == 0:
        raise ValueError(
            "no scored mutants (all skipped); refusing to treat as a pass"
        )
    return MutationResult(
        killed=caught, survived=survived, skipped=skipped,
        total=total, kill_rate=caught / total,
    )


def meets_floor(result: MutationResult, floor: float) -> bool:
    return result.kill_rate >= floor


def run_mutation(repo: Path, paths: list[str], runner: str) -> MutationResult:
    """Integration seam (not in the gate's own unit suite). Runs mutmut on
    the declared pure-logic paths and parses the result. A missing declared
    path or a mutmut crash raises -> caller treats as gate FAIL."""
    repo = Path(repo)
    for p in paths:
        if not (repo / p).exists():
            raise FileNotFoundError(
                f"declared pure-logic path missing, cannot gate: {p}"
            )
    # Preflight: refuse to run if a target has uncommitted changes. The
    # post-run restore does `git checkout -- <target>`, which would
    # otherwise silently destroy real local edits if the worktree was
    # dirty. The gate is meant to judge committed work, so a dirty
    # target is a hard, fail-closed error — never a clobber.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths],
        cwd=str(repo), check=False, capture_output=True,
        encoding="utf-8", errors="replace",
    ).stdout.strip()
    if dirty:
        raise RuntimeError(
            "mutation target has uncommitted changes; commit or stash "
            f"before gating (refusing to risk clobbering them):\n{dirty}"
        )
    # Drop any stale cache so a crashed `mutmut run` cannot report a
    # prior run's (possibly passing) numbers.
    cache = repo / ".mutmut-cache"
    if cache.exists():
        cache.unlink()
    # Invoke mutmut via the running interpreter (no PATH dependency) and
    # force UTF-8 I/O: mutmut 2.5.1 prints non-ASCII status glyphs and
    # aborts under a non-UTF-8 console (e.g. Windows cp1252), which would
    # otherwise leave `mutmut results` empty and FAIL the gate for a
    # tooling reason rather than a real survived mutant. PYTHONPATH keeps
    # the pytest runner able to import the package under test without
    # depending on an editable install in the gate environment.
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": os.pathsep.join(
            [str(repo / "src"), os.environ.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep),
    }
    mutmut = [sys.executable, "-m", "mutmut"]
    # Decode the child's stdout as UTF-8 in THIS process too (not the
    # locale codec): mutmut emits non-ASCII glyphs, and `text=True` would
    # decode them with cp1252 on Windows and raise UnicodeDecodeError
    # here, FAILing the gate for a tooling reason. errors="replace" keeps
    # a glyph we cannot map from aborting the parse.
    dec = dict(capture_output=True, encoding="utf-8", errors="replace")
    try:
        # The authoritative counts are in `mutmut run`'s own summary
        # output (stdout+stderr — the spinner/summary may land on
        # either). `mutmut results` cannot give the killed count in
        # 2.5.1, so it is not used. check=False: mutmut exits non-zero
        # whenever any mutant survives; that is data, not an error.
        proc = subprocess.run(
            [*mutmut, "run", "--paths-to-mutate", ",".join(paths),
             "--runner", runner],
            cwd=str(repo), check=False, env=env, **dec,
        )
        results = (proc.stdout or "") + (proc.stderr or "")
    finally:
        # mutmut applies each mutant to the file on disk and reverts it;
        # a crash mid-run leaves the mutation target corrupted, which
        # would silently poison every later gate leg and any commit.
        # Always restore the judged paths and drop mutmut's .bak files.
        subprocess.run(
            ["git", "checkout", "--", *paths],
            cwd=str(repo), check=False, capture_output=True,
        )
        for p in paths:
            bak = repo / (p + ".bak")
            if bak.exists():
                bak.unlink()
    return parse_mutmut_results(results)
