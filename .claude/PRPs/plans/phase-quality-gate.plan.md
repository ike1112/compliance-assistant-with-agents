# Phase Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an outer orchestrator loop that makes it impossible for a PRD phase to reach `complete` without passing an independent multi-agent review panel plus an objective mutation/coverage test-integrity check.

**Architecture:** All deterministic judgement lives in a tested Python package `review_gate/` (config, loop state, frozen-diff + integrity, mutation parsing, verdict aggregation, PRD flip, Phase-3 gold-set provenance), exposed through one CLI. A thin project skill `.claude/skills/phase-gate/SKILL.md` is the agent-facing orchestrator that sequences prp-plan → **adversarial plan review (codex + code-reviewer-verify, revise+commit before any build)** → prp-ralph → the parallel panel (codex adversarial + mutation/coverage + security-auditor + code-reviewer + PRD-CHECK regression, plus an advisory non-blocking test-engineer leg) → PASS-flip or capped fresh-ralph remediation. The CLI's `complete` command is the single chokepoint: it refuses to flip the PRD unless an independent panel PASS token for the exact judged base SHA exists, so the builder can never self-certify.

**Tech Stack:** Python 3.10–3.12, pytest (existing `testpaths=["tests","infra/tests"]`), `mutmut==2.5.1`, `pytest-cov`, git CLI, the `openai-codex` plugin (`/codex:adversarial-review`), `agent-skills` subagents (`security-auditor`, `code-reviewer`) via the Agent tool.

---

## Context the engineer needs

- **Project layout:** product code is src-layout under `src/compliance_assistant/` (installed editable via hatch); CDK app under `infra/`; tests under `tests/` and `infra/tests/`. The gate is **tooling, not product** — it goes in a new root package `review_gate/` so it never enters the product wheel (`[tool.hatch.build.targets.wheel] packages = ["src/compliance_assistant"]`).
- **Test style to mirror** (`tests/test_agent_ids.py`): small focused pytest modules, `monkeypatch`, `pytest.raises`, one behaviour per test, module docstring stating the contract.
- **`review_gate/` is not pip-installed**, so a `tests/review_gate/conftest.py` prepends the repo root to `sys.path` (explicit, deterministic). Tests are collected automatically because they live under `tests/`.
- **The PRD** (`.claude/PRPs/compliance-prod-hardening.prd.md`) has an "Implementation Phases" table (rows keyed by `| N |`, a `Status` column ∈ `pending|in-progress|complete`), a "Progress Log" section (append one line per status change), and a "Success Criteria (per phase, machine-checkable)" section with `CHECK:`/`HUMAN-GATE:` items. The orchestrator owns the `Status`→`complete` flip; prp-ralph never performs it.
- **Spec** being implemented: `docs/superpowers/specs/2026-05-16-phase-quality-gate-design.md` (untracked working note; this plan and the `review_gate/` code ARE git-tracked, per the project convention recorded in PRD §"Scope Decisions").
- **Codex panel leg:** `/codex:adversarial-review --wait --base <base_sha>` (review-only, returns Codex output verbatim; CLI `codex-cli` is installed). **Subagent panel legs:** Agent tool with `subagent_type="agent-skills:security-auditor"` and `subagent_type="agent-skills:code-reviewer"`, fresh isolated context.
- **mutmut 2.5.x contract:** `mutmut run --paths-to-mutate <p1,p2> --runner "<cmd>"` then `mutmut results`. `mutmut results` prints, after a header, lines of the form `<id>: <status>` where status ∈ `killed|timeout|suspicious|survived|skipped`. killed/timeout/suspicious count as caught; survived counts against the kill rate; skipped is excluded from the denominator. Pin `mutmut==2.5.1` so this parse contract is stable; on any parse failure the gate FAILs closed (never silent-passes).

## File structure

| File | Responsibility |
|---|---|
| `.claude/review-gate.config.json` | CREATE, tracked. `mutation_floor`, `coverage_floor`, per-phase `pure_logic_paths` + `frozen_fixture_paths`. The bar lives here so editing it is detectable. |
| `review_gate/__init__.py` | CREATE. Package marker. |
| `review_gate/config.py` | Load + validate the config file into typed dataclasses. |
| `review_gate/state.py` | Loop state: init/load/save `.claude/review-gate.state.json` (atomic). |
| `review_gate/diff.py` | Pin base SHA, compute frozen range + changed files, detect protected-path tampering inside the judged diff. |
| `review_gate/mutation.py` | Parse `mutmut results`; compare kill-rate to floor (pure parser is unit-tested; live runner is the integration seam). |
| `review_gate/aggregate.py` | Apply the spec §3 step-6 PASS/FAIL rule to normalized verdicts (advisory legs recorded, never blocking); emit a base-SHA-bound outcome token. |
| `review_gate/prd.py` | Flip a phase row to `complete` + append a Progress-Log line, with an idempotency guard. |
| `review_gate/provenance.py` | Phase-3 gold-set authoring-marker contract + verifier. |
| `review_gate/cli.py` | One argparse entry; subcommands map 1:1 to skill steps; documented exit codes. |
| `.claude/skills/phase-gate/SKILL.md` | CREATE. The agent-facing orchestrator loop. |
| `tests/review_gate/__init__.py` + `conftest.py` + `test_*.py` | The gate's own tests (stubbed panel, cap, integrity, tamper, provenance). |
| `pyproject.toml` | MODIFY: add `[project.optional-dependencies] gate`. |
| `.gitignore` | MODIFY: ignore the runtime state + outcome-token files. |
| `.claude/PRPs/compliance-prod-hardening.prd.md` | MODIFY: one-sentence completion rule + per-phase `GATE:` lines. |

## Data contracts (locked — every later task must match these names)

- `GateConfig(mutation_floor: float, coverage_floor: float, phases: dict[str, PhaseConfig])`; `PhaseConfig(pure_logic_paths: list[str], frozen_fixture_paths: list[str])`; raises `GateConfigError`.
- `GateState(phase: str, base_sha: str, round: int, status: str, findings_path: str | None)`; `status ∈ {"building","reviewing","remediating","passed","halted"}`.
- `MutationResult(killed: int, survived: int, skipped: int, total: int, kill_rate: float)`.
- `Verdict(name: str, passed: bool, severity: str | None, summary: str)`; `severity ∈ {None,"MINOR","MAJOR","BLOCKER"}`; required-leg `name ∈ {"codex","test_integrity","security","code","regression"}`; `"test_engineer"` is an **optional advisory** verdict — recorded in evidence, never required, never blocks (mutation is the objective test bar).
- `GateOutcome(passed: bool, blocking: list[str], evidence: dict)`.
- `ProvenanceResult(ok: bool, reason: str)`.
- Outcome token `.claude/review-gate.last-outcome.json`: `{"base_sha": str, "phase": str, "passed": bool, "ts": str}`.
- CLI exit codes: `0` ok / gate-PASS, `1` gate-FAIL (acted-on by the loop), `2` usage or I/O error (loop halts for human).

---

### Task 1: Package skeleton, dependency group, ignore rules

**Files:**
- Create: `review_gate/__init__.py`
- Create: `tests/review_gate/__init__.py`
- Create: `tests/review_gate/conftest.py`
- Modify: `pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Create the package marker**

`review_gate/__init__.py`:

```python
"""Phase Quality Gate — deterministic orchestrator-loop logic.

Tooling, not product: deliberately a root package so it never enters the
compliance_assistant wheel. The agent-facing loop is .claude/skills/phase-gate.
"""
```

- [ ] **Step 2: Create the test package + path shim**

`tests/review_gate/__init__.py`:

```python
```

`tests/review_gate/conftest.py`:

```python
"""review_gate is not pip-installed (it is tooling, not the product wheel),
so make the repo root importable for these tests explicitly."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
```

- [ ] **Step 3: Add the optional dependency group**

In `pyproject.toml`, after the existing `infra = [...]` block inside `[project.optional-dependencies]`, add:

```toml
# Quality-gate tooling. Build/CI-time only; never in the runtime closure.
gate = [
    "mutmut==2.5.1",
    "pytest-cov>=5.0",
    "pytest>=8.0",
]
```

- [ ] **Step 4: Ignore the runtime loop files**

Append to `.gitignore`:

```
.claude/review-gate.state.json
.claude/review-gate.last-outcome.json
.mutmut-cache
```

- [ ] **Step 5: Verify collection works**

Run: `python -m pytest tests/review_gate -q`
Expected: `no tests ran` (exit 5) — confirms the directory is discovered and the conftest imports cleanly with no error.

- [ ] **Step 6: Commit**

```bash
git add review_gate/__init__.py tests/review_gate/__init__.py tests/review_gate/conftest.py pyproject.toml .gitignore
git commit -m "add review_gate package skeleton: dep group + path shim + ignore loop state"
```

---

### Task 2: Config loader

**Files:**
- Create: `review_gate/config.py`
- Create: `.claude/review-gate.config.json`
- Test: `tests/review_gate/test_config.py`

- [ ] **Step 1: Write the failing tests**

`tests/review_gate/test_config.py`:

```python
"""load_config: typed, validated, fails loud on a malformed bar file."""
import json

import pytest

from review_gate.config import GateConfig, GateConfigError, load_config


def _write(tmp_path, obj):
    p = tmp_path / "review-gate.config.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_loads_typed_config(tmp_path):
    p = _write(tmp_path, {
        "mutation_floor": 0.80,
        "coverage_floor": 0.90,
        "phases": {"3": {"pure_logic_paths": ["a.py"], "frozen_fixture_paths": ["g/"]}},
    })
    cfg = load_config(p)
    assert isinstance(cfg, GateConfig)
    assert cfg.mutation_floor == 0.80
    assert cfg.phases["3"].pure_logic_paths == ["a.py"]
    assert cfg.phases["3"].frozen_fixture_paths == ["g/"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(GateConfigError):
        load_config(tmp_path / "nope.json")


def test_bad_json_raises(tmp_path):
    p = tmp_path / "review-gate.config.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(GateConfigError):
        load_config(p)


@pytest.mark.parametrize("bad", [
    {"coverage_floor": 0.9, "phases": {}},                       # no mutation_floor
    {"mutation_floor": 1.5, "coverage_floor": 0.9, "phases": {}}, # out of range
    {"mutation_floor": 0.8, "coverage_floor": 0.9, "phases": {"3": {}}},  # phase missing keys
    {"mutation_floor": 0.8, "coverage_floor": 0.9},               # no phases
])
def test_schema_violations_raise(tmp_path, bad):
    with pytest.raises(GateConfigError):
        load_config(_write(tmp_path, bad))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/review_gate/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_gate.config'`.

- [ ] **Step 3: Implement the loader**

`review_gate/config.py`:

```python
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
        phases[str(phase_id)] = PhaseConfig(
            pure_logic_paths=[str(x) for x in pc["pure_logic_paths"]],
            frozen_fixture_paths=[str(x) for x in pc["frozen_fixture_paths"]],
        )

    return GateConfig(mutation_floor, coverage_floor, phases)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/review_gate/test_config.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Create the real config file**

`.claude/review-gate.config.json` (floors are the bar; pure-logic = files where mutation testing is meaningful, i.e. pure decision/format/math, never I/O or LLM-call glue):

```json
{
  "mutation_floor": 0.80,
  "coverage_floor": 0.90,
  "phases": {
    "2": {
      "pure_logic_paths": ["src/compliance_assistant/agent_ids.py"],
      "frozen_fixture_paths": []
    },
    "3": {
      "pure_logic_paths": ["src/compliance_assistant/citations.py"],
      "frozen_fixture_paths": ["tests/evals/gold/", "tests/evals/gold/PROVENANCE.md"]
    },
    "5": {
      "pure_logic_paths": ["src/compliance_assistant/citations.py"],
      "frozen_fixture_paths": []
    }
  }
}
```

- [ ] **Step 6: Commit**

```bash
git add review_gate/config.py tests/review_gate/test_config.py .claude/review-gate.config.json
git commit -m "add review_gate config loader + tracked bar file"
```

---

### Task 3: Loop state

**Files:**
- Create: `review_gate/state.py`
- Test: `tests/review_gate/test_state.py`

- [ ] **Step 1: Write the failing tests**

`tests/review_gate/test_state.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/review_gate/test_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_gate.state'`.

- [ ] **Step 3: Implement the state module**

`review_gate/state.py`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/review_gate/test_state.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add review_gate/state.py tests/review_gate/test_state.py
git commit -m "add review_gate loop state: atomic, resumable, status-validated"
```

---

### Task 4: Frozen diff + protected-path integrity

**Files:**
- Create: `review_gate/diff.py`
- Test: `tests/review_gate/test_diff.py`

- [ ] **Step 1: Write the failing tests**

`tests/review_gate/test_diff.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/review_gate/test_diff.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_gate.diff'`.

- [ ] **Step 3: Implement the diff module**

`review_gate/diff.py`:

```python
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
    """Committed changes since base_sha PLUS untracked files (codex treats
    untracked as reviewable work, so the integrity check must too)."""
    repo = Path(repo)
    committed = _git(repo, "diff", "--name-only", f"{base_sha}..HEAD")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard")
    out: list[str] = []
    for blob in (committed, untracked):
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/review_gate/test_diff.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add review_gate/diff.py tests/review_gate/test_diff.py
git commit -m "add review_gate frozen-diff + protected-path integrity check"
```

---

### Task 5: Mutation-result parser + floor check

**Files:**
- Create: `review_gate/mutation.py`
- Test: `tests/review_gate/test_mutation.py`

- [ ] **Step 1: Write the failing tests**

`tests/review_gate/test_mutation.py`:

```python
"""parse_mutmut_results: objective kill-rate from `mutmut results` text.
The live runner is the integration seam; this parser is the unit-tested
anti-gaming core (a weakened assertion lowers kill-rate -> hard fail)."""
import pytest

from review_gate.mutation import (
    MutationResult,
    meets_floor,
    parse_mutmut_results,
)

_RESULTS = """\

To apply a mutant on disk:
    mutmut apply <id>

1: killed
2: killed
3: timeout
4: suspicious
5: survived
6: skipped
"""


def test_parses_counts_and_rate():
    r = parse_mutmut_results(_RESULTS)
    assert isinstance(r, MutationResult)
    assert r.killed == 4          # killed + timeout + suspicious
    assert r.survived == 1
    assert r.skipped == 1
    assert r.total == 5           # skipped excluded from denominator
    assert r.kill_rate == pytest.approx(0.8)


def test_all_killed_is_rate_one():
    r = parse_mutmut_results("1: killed\n2: killed\n")
    assert r.kill_rate == 1.0


def test_no_mutants_raises_not_silent_pass():
    # An empty result must NOT read as a free pass.
    with pytest.raises(ValueError):
        parse_mutmut_results("\nNo mutants found\n")


def test_unparseable_raises():
    with pytest.raises(ValueError):
        parse_mutmut_results("totally unexpected output")


def test_meets_floor_boundary():
    r = parse_mutmut_results("1: killed\n2: killed\n3: killed\n4: survived\n")
    assert r.kill_rate == pytest.approx(0.75)
    assert meets_floor(r, 0.75) is True
    assert meets_floor(r, 0.7500001) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/review_gate/test_mutation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_gate.mutation'`.

- [ ] **Step 3: Implement the mutation module**

`review_gate/mutation.py`:

```python
"""Objective test-integrity leg: mutation kill-rate vs a configured floor.

Parsing is isolated from running so the anti-gaming core is unit-tested
with captured `mutmut results` text. mutmut==2.5.1 is pinned so this
line contract is stable. Any deviation raises (FAIL closed) — the gate
never reads ambiguous mutation output as a pass.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_LINE = re.compile(r"^\s*\d+:\s*(killed|timeout|suspicious|survived|skipped)\s*$")
_CAUGHT = {"killed", "timeout", "suspicious"}


@dataclass(frozen=True)
class MutationResult:
    killed: int
    survived: int
    skipped: int
    total: int        # killed + survived (skipped excluded)
    kill_rate: float


def parse_mutmut_results(text: str) -> MutationResult:
    killed = survived = skipped = 0
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        status = m.group(1)
        if status in _CAUGHT:
            killed += 1
        elif status == "survived":
            survived += 1
        else:
            skipped += 1

    total = killed + survived
    if total == 0:
        raise ValueError(
            "no scored mutants parsed from mutmut output; refusing to "
            "treat as a pass"
        )
    return MutationResult(
        killed=killed, survived=survived, skipped=skipped,
        total=total, kill_rate=killed / total,
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
    subprocess.run(
        ["mutmut", "run", "--paths-to-mutate", ",".join(paths),
         "--runner", runner],
        cwd=str(repo), check=False, capture_output=True, text=True,
    )
    results = subprocess.run(
        ["mutmut", "results"], cwd=str(repo), check=True,
        capture_output=True, text=True,
    ).stdout
    return parse_mutmut_results(results)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/review_gate/test_mutation.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add review_gate/mutation.py tests/review_gate/test_mutation.py
git commit -m "add review_gate mutation parser + kill-rate floor (FAIL-closed)"
```

---

### Task 6: Verdict aggregation + base-SHA-bound outcome token

**Files:**
- Create: `review_gate/aggregate.py`
- Test: `tests/review_gate/test_aggregate.py`

- [ ] **Step 1: Write the failing tests**

`tests/review_gate/test_aggregate.py`:

```python
"""aggregate: the spec §3 step-6 rule, plus a base-SHA-bound PASS token
that makes builder self-certification impossible. test_engineer is
advisory — it is recorded but never blocks."""
import json

from review_gate.aggregate import GateOutcome, Verdict, aggregate, write_outcome_token


def _v(name, passed, severity=None):
    return Verdict(name=name, passed=passed, severity=severity, summary=name)


def _all_clean():
    return [
        _v("codex", True),
        _v("test_integrity", True),
        _v("security", True),
        _v("code", True),
        _v("regression", True),
    ]


def test_all_clean_passes():
    out = aggregate(_all_clean())
    assert out.passed is True
    assert out.blocking == []


def test_test_integrity_fail_blocks():
    v = _all_clean()
    v[1] = _v("test_integrity", False)
    out = aggregate(v)
    assert out.passed is False
    assert "test_integrity" in out.blocking


def test_regression_fail_blocks():
    v = _all_clean()
    v[4] = _v("regression", False)
    assert aggregate(v).passed is False


def test_codex_major_blocks_minor_does_not():
    v = _all_clean()
    v[0] = _v("codex", True, "MINOR")
    assert aggregate(v).passed is True
    v[0] = _v("codex", True, "MAJOR")
    assert aggregate(v).passed is False


def test_security_or_code_blocker_blocks():
    v = _all_clean()
    v[2] = _v("security", True, "BLOCKER")
    assert aggregate(v).passed is False
    v = _all_clean()
    v[3] = _v("code", True, "MAJOR")
    assert aggregate(v).passed is False


def test_missing_required_leg_is_fail_not_pass():
    # Only four legs reported (codex absent) -> cannot pass.
    out = aggregate([_v("test_integrity", True), _v("security", True),
                      _v("code", True), _v("regression", True)])
    assert out.passed is False
    assert "codex" in out.blocking


def test_test_engineer_is_advisory_never_blocks():
    # Even a BLOCKER from test-engineer must not fail the gate; it is
    # evidence only. Mutation is the objective test bar, not this opinion.
    v = _all_clean()
    v.append(_v("test_engineer", False, "BLOCKER"))
    out = aggregate(v)
    assert out.passed is True
    assert "test_engineer" not in out.blocking
    assert "test_engineer" in out.evidence


def test_outcome_token_is_bound_to_base_sha(tmp_path):
    tok = tmp_path / "tok.json"
    write_outcome_token(tok, base_sha="deadbeef", phase="3",
                         outcome=aggregate(_all_clean()))
    data = json.loads(tok.read_text(encoding="utf-8"))
    assert data["base_sha"] == "deadbeef"
    assert data["phase"] == "3"
    assert data["passed"] is True
    assert "ts" in data
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/review_gate/test_aggregate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_gate.aggregate'`.

- [ ] **Step 3: Implement the aggregator**

`review_gate/aggregate.py`:

```python
"""Panel verdict aggregation (spec §3 step-6) and the PASS token.

Rule: test_integrity OR regression failing -> FAIL; codex/security/code
reporting BLOCKER or MAJOR -> FAIL; any of the five required legs missing
-> FAIL (a leg that did not run is never an implicit pass). The PASS token
is bound to the exact judged base SHA so `complete` cannot consume a stale
or builder-fabricated pass. Any verdict whose name is not a required leg
(e.g. "test_engineer") is advisory: kept in evidence, never blocking.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_LEGS = {"codex", "test_integrity", "security", "code", "regression"}
_BLOCKING_SEVERITY = {"MAJOR", "BLOCKER"}


@dataclass(frozen=True)
class Verdict:
    name: str
    passed: bool
    severity: str | None
    summary: str


@dataclass
class GateOutcome:
    passed: bool
    blocking: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def aggregate(verdicts: list[Verdict]) -> GateOutcome:
    by_name = {v.name: v for v in verdicts}
    blocking: list[str] = []

    for leg in sorted(REQUIRED_LEGS):
        if leg not in by_name:
            blocking.append(leg)  # missing leg never passes implicitly

    for name in ("test_integrity", "regression"):
        v = by_name.get(name)
        if v is not None and not v.passed:
            blocking.append(name)

    for name in ("codex", "security", "code"):
        v = by_name.get(name)
        if v is not None and v.severity in _BLOCKING_SEVERITY:
            blocking.append(name)

    blocking = sorted(set(blocking))
    evidence = {v.name: {"passed": v.passed, "severity": v.severity,
                          "summary": v.summary} for v in verdicts}
    return GateOutcome(passed=not blocking, blocking=blocking,
                       evidence=evidence)


def write_outcome_token(path: Path, base_sha: str, phase: str,
                        outcome: GateOutcome) -> None:
    Path(path).write_text(json.dumps({
        "base_sha": base_sha,
        "phase": phase,
        "passed": outcome.passed,
        "ts": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/review_gate/test_aggregate.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add review_gate/aggregate.py tests/review_gate/test_aggregate.py
git commit -m "add review_gate verdict aggregation + base-SHA-bound PASS token"
```

---

### Task 7: PRD phase flip + Progress-Log append

**Files:**
- Create: `review_gate/prd.py`
- Test: `tests/review_gate/test_prd.py`

- [ ] **Step 1: Write the failing tests**

`tests/review_gate/test_prd.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/review_gate/test_prd.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_gate.prd'`.

- [ ] **Step 3: Implement the PRD writer**

`review_gate/prd.py`:

```python
"""Flip exactly one phase row to `complete` and append one Progress-Log
line with panel evidence. This is the only place a phase is marked done;
prp-ralph never edits the Status column.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path


class PrdError(Exception):
    """Phase row not found, or already complete (no silent re-flip)."""


def _row_re(phase: str) -> re.Pattern:
    # | <phase> | ... | <status> | ... |  -- capture the 3rd cell (Status)
    return re.compile(
        rf"^(\|\s*{re.escape(phase)}\s*\|[^|]*\|[^|]*\|\s*)"
        rf"(pending|in-progress|complete)(\s*\|.*)$",
        re.MULTILINE,
    )


def flip_phase_complete(prd_path: Path, phase: str, evidence: dict) -> None:
    prd_path = Path(prd_path)
    text = prd_path.read_text(encoding="utf-8")

    m = _row_re(phase).search(text)
    if m is None:
        raise PrdError(f"no phase row '{phase}' in {prd_path}")
    if m.group(2) == "complete":
        raise PrdError(f"phase {phase} already complete; refusing re-flip")

    text = text[:m.start()] + m.group(1) + "complete" + m.group(3) + text[m.end():]

    ev = " ".join(f"{k}={v}" for k, v in sorted(evidence.items()))
    line = f"- {date.today().isoformat()} — phase {phase} -> complete via " \
           f"quality gate ({ev})."

    marker = "## Progress Log"
    idx = text.index(marker)
    nl = text.index("\n", idx) + 1
    # insert right after the heading line + its blank line, before existing log
    insert_at = text.index("\n", nl) + 1 if text[nl:nl + 1] == "\n" else nl
    text = text[:insert_at] + line + "\n" + text[insert_at:]

    prd_path.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/review_gate/test_prd.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add review_gate/prd.py tests/review_gate/test_prd.py
git commit -m "add review_gate PRD flip: single-chokepoint status write + evidence log"
```

---

### Task 8: Phase-3 gold-set provenance

**Files:**
- Create: `review_gate/provenance.py`
- Test: `tests/review_gate/test_provenance.py`

- [ ] **Step 1: Write the failing tests**

`tests/review_gate/test_provenance.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/review_gate/test_provenance.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_gate.provenance'`.

- [ ] **Step 3: Implement provenance**

`review_gate/provenance.py`:

```python
"""Phase-3 gold-set bootstrap rule (spec §5).

Mutation cannot protect the gold set on the phase that *creates* it, so
the gate enforces authoring provenance instead: a committed PROVENANCE.md
marker declaring an approved author (owner or codex), present before the
harness diff, and the gold set untouched by the diff being judged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from review_gate.diff import integrity_violations

GOLD_DIR = "tests/evals/gold"
GOLD_MARKER = "tests/evals/gold/PROVENANCE.md"
_APPROVED_AUTHORS = {"owner", "codex"}
_AUTHOR_RE = re.compile(r"^author:\s*(\w+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ProvenanceResult:
    ok: bool
    reason: str


def verify_gold_provenance(repo: Path, base_sha: str) -> ProvenanceResult:
    repo = Path(repo)
    marker = repo / GOLD_MARKER

    if not marker.is_file():
        return ProvenanceResult(False, f"gold-set marker {GOLD_MARKER} missing")

    text = marker.read_text(encoding="utf-8")
    m = _AUTHOR_RE.search(text)
    if not m or m.group(1) not in _APPROVED_AUTHORS:
        return ProvenanceResult(
            False, f"gold-set author must be one of {_APPROVED_AUTHORS}")

    if integrity_violations(repo, base_sha, [GOLD_DIR]):
        return ProvenanceResult(
            False, f"{GOLD_DIR} was modified inside the judged diff")

    return ProvenanceResult(True, "gold-set provenance OK")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/review_gate/test_provenance.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add review_gate/provenance.py tests/review_gate/test_provenance.py
git commit -m "add review_gate Phase-3 gold-set provenance rule"
```

---

### Task 9: CLI — the orchestrator's deterministic surface

**Files:**
- Create: `review_gate/cli.py`
- Test: `tests/review_gate/test_cli.py`

- [ ] **Step 1: Write the failing tests**

`tests/review_gate/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/review_gate/test_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_gate.cli'`.

- [ ] **Step 3: Implement the CLI**

`review_gate/cli.py`:

```python
"""One entry point; subcommands map 1:1 to orchestrator-skill steps.

Exit codes (contract): 0 ok / gate-PASS, 1 gate-FAIL (loop acts on it),
2 usage or I/O error (loop halts for a human). The `complete` subcommand
is the single chokepoint: it flips the PRD only when an independent PASS
token bound to the current state's base SHA exists, so the builder can
never self-certify even if it calls this command.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from review_gate import diff
from review_gate.aggregate import aggregate, write_outcome_token
from review_gate.config import GateConfigError, load_config
from review_gate.mutation import meets_floor, run_mutation
from review_gate.prd import PrdError, flip_phase_complete
from review_gate.provenance import verify_gold_provenance
from review_gate.state import init_state, load_state, save_state

CONFIG_REL = ".claude/review-gate.config.json"
STATE_REL = ".claude/review-gate.state.json"
TOKEN_REL = ".claude/review-gate.last-outcome.json"
PRD_REL = ".claude/PRPs/compliance-prod-hardening.prd.md"

OK, GATE_FAIL, USAGE = 0, 1, 2


def _paths(repo: Path):
    repo = Path(repo)
    return (repo / CONFIG_REL, repo / STATE_REL,
            repo / TOKEN_REL, repo / PRD_REL)


def _cmd_init(repo: Path, phase: str) -> int:
    _, state_p, _, _ = _paths(repo)
    existing = load_state(state_p)
    if existing and existing.phase == phase:
        return OK  # resumable: keep the pinned base SHA
    init_state(state_p, phase=phase, base_sha=diff.pin_base_sha(repo))
    return OK


def _cmd_integrity(repo: Path, phase: str) -> int:
    cfg_p, state_p, _, _ = _paths(repo)
    st = load_state(state_p)
    if st is None:
        print("no gate state; run init first", file=sys.stderr)
        return USAGE
    cfg = load_config(cfg_p)
    protected = [CONFIG_REL]
    pc = cfg.phases.get(phase)
    if pc:
        protected += pc.frozen_fixture_paths
    hits = diff.integrity_violations(repo, st.base_sha, protected)
    if hits:
        print(f"integrity violation: {hits}", file=sys.stderr)
        return GATE_FAIL
    return OK


def _cmd_mutation(repo: Path, phase: str) -> int:
    cfg_p, _, _, _ = _paths(repo)
    cfg = load_config(cfg_p)
    pc = cfg.phases.get(phase)
    if pc is None or not pc.pure_logic_paths:
        print(f"no pure-logic paths declared for phase {phase}",
              file=sys.stderr)
        return USAGE
    result = run_mutation(repo, pc.pure_logic_paths,
                          runner="python -m pytest -x -q")
    if not meets_floor(result, cfg.mutation_floor):
        print(f"mutation kill-rate {result.kill_rate:.3f} < "
              f"{cfg.mutation_floor}", file=sys.stderr)
        return GATE_FAIL
    print(f"mutation kill-rate {result.kill_rate:.3f}")
    return OK


def _cmd_provenance(repo: Path, phase: str) -> int:
    _, state_p, _, _ = _paths(repo)
    if phase != "3":
        return OK  # rule only applies to the phase that creates the gold set
    st = load_state(state_p)
    if st is None:
        print("no gate state; run init first", file=sys.stderr)
        return USAGE
    r = verify_gold_provenance(repo, st.base_sha)
    if not r.ok:
        print(f"gold-set provenance: {r.reason}", file=sys.stderr)
        return GATE_FAIL
    return OK


def _cmd_aggregate(repo: Path, phase: str, verdicts_path: str) -> int:
    _, state_p, token_p, _ = _paths(repo)
    st = load_state(state_p)
    if st is None:
        print("no gate state; run init first", file=sys.stderr)
        return USAGE
    from review_gate.aggregate import Verdict
    raw = json.loads(Path(verdicts_path).read_text(encoding="utf-8"))
    verdicts = [Verdict(**v) for v in raw]
    outcome = aggregate(verdicts)
    write_outcome_token(token_p, base_sha=st.base_sha, phase=phase,
                        outcome=outcome)
    st.status = "reviewing"
    save_state(state_p, st)
    if not outcome.passed:
        print(f"gate FAIL; blocking: {outcome.blocking}", file=sys.stderr)
        return GATE_FAIL
    print("gate PASS")
    return OK


def _cmd_complete(repo: Path, phase: str) -> int:
    _, state_p, token_p, prd_p = _paths(repo)
    st = load_state(state_p)
    if st is None or st.phase != phase:
        print("no gate state for this phase", file=sys.stderr)
        return USAGE
    if not Path(token_p).is_file():
        print("refusing: no independent PASS token", file=sys.stderr)
        return USAGE
    tok = json.loads(Path(token_p).read_text(encoding="utf-8"))
    if not (tok.get("passed") is True
            and tok.get("base_sha") == st.base_sha
            and tok.get("phase") == phase):
        print("refusing: PASS token does not match this judged base SHA",
              file=sys.stderr)
        return USAGE
    try:
        flip_phase_complete(prd_p, phase=phase, evidence=tok)
    except PrdError as exc:
        print(f"PRD flip refused: {exc}", file=sys.stderr)
        return USAGE
    st.status = "passed"
    save_state(state_p, st)
    print(f"phase {phase} -> complete")
    return OK


def _cmd_status(repo: Path) -> int:
    _, state_p, _, _ = _paths(repo)
    st = load_state(state_p)
    print(json.dumps(st.__dict__ if st else {}, indent=2))
    return OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="review_gate")
    parser.add_argument("--repo", default=".")
    sub = parser.add_subparsers(dest="cmd")
    for name in ("init", "integrity", "mutation", "provenance", "complete"):
        sp = sub.add_parser(name)
        sp.add_argument("--phase", required=True)
    agg = sub.add_parser("aggregate")
    agg.add_argument("--phase", required=True)
    agg.add_argument("--verdicts", required=True)
    sub.add_parser("status")

    try:
        ns = parser.parse_args(argv)
    except SystemExit:
        return USAGE
    if ns.cmd is None:
        parser.print_usage(sys.stderr)
        return USAGE

    repo = Path(ns.repo)
    try:
        if ns.cmd == "init":
            return _cmd_init(repo, ns.phase)
        if ns.cmd == "integrity":
            return _cmd_integrity(repo, ns.phase)
        if ns.cmd == "mutation":
            return _cmd_mutation(repo, ns.phase)
        if ns.cmd == "provenance":
            return _cmd_provenance(repo, ns.phase)
        if ns.cmd == "aggregate":
            return _cmd_aggregate(repo, ns.phase, ns.verdicts)
        if ns.cmd == "complete":
            return _cmd_complete(repo, ns.phase)
        if ns.cmd == "status":
            return _cmd_status(repo)
    except (GateConfigError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"gate error: {exc}", file=sys.stderr)
        return USAGE
    parser.print_usage(sys.stderr)
    return USAGE


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/review_gate/test_cli.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the whole gate suite**

Run: `python -m pytest tests/review_gate -q`
Expected: PASS (all tasks 2–9 green together; ~35 tests).

- [ ] **Step 6: Commit**

```bash
git add review_gate/cli.py tests/review_gate/test_cli.py
git commit -m "add review_gate CLI: subcommands + self-certification-proof complete chokepoint"
```

---

### Task 10: The orchestrator skill

**Files:**
- Create: `.claude/skills/phase-gate/SKILL.md`

- [ ] **Step 1: Write the skill**

`.claude/skills/phase-gate/SKILL.md`:

````markdown
---
name: phase-gate
description: Outer orchestrator loop. Drives PRD phases prp-plan -> prp-ralph -> independent review panel -> PASS-flip or capped fresh-ralph remediation. The builder never marks its own phase complete.
---

# Phase Quality Gate — Orchestrator Loop

Implements `docs/superpowers/specs/2026-05-16-phase-quality-gate-design.md`.
The deterministic logic is the tested `review_gate` package; this skill is
the sequencing layer. **Never** edit a PRD `Status` cell by hand and never
run `cdk deploy` — `HUMAN-GATE:` items halt the loop.

All CLI calls below: `python -m review_gate.cli <cmd> --repo . [...]`.
Exit code 0 = ok/PASS, 1 = gate-FAIL (act on it), 2 = usage/IO (HALT for human).

## Loop

1. **Pick the phase.** Read `.claude/PRPs/compliance-prod-hardening.prd.md`.
   Choose the lowest-numbered phase whose `Status` is `pending` (or
   `in-progress` with no outstanding `HUMAN-GATE:`) and whose every
   dependency is `complete`. If the only remaining work for an otherwise
   actionable phase is a `HUMAN-GATE:` item, **STOP** and report — never
   deploy, never auto-pass it.

2. **`init`.** `python -m review_gate.cli init --phase <P>`. This pins the
   base SHA once and persists state (resumable; re-running keeps the pin).

3. **prp-plan.** Invoke `prp-core:prp-plan` with the PRD. The generated
   plan's validation section MUST be that phase's PRD `CHECK:` items
   verbatim — if it is not, fix the plan before continuing.

4. **Adversarial plan review (before any build is spent).**
   - Run `/codex:adversarial-review --wait --base HEAD` scoped to the
     newly written/committed plan file — challenge the approach,
     assumptions, and tradeoffs, not just defects.
   - Dispatch the Agent tool with
     `subagent_type="agent-skills:code-reviewer"`, fresh context, to
     verify the codex findings and the plan's internal consistency
     against this phase's PRD `CHECK:` items.
   - Revise the plan to resolve any BLOCKER/MAJOR finding, then **commit
     the revised plan** (`git add <plan> && git commit -m "phase <P>:
     plan revised per adversarial review"`). Only then continue. If codex
     is unavailable, HALT for human — never skip this stage silently.

5. **prp-ralph.** Invoke `prp-core:prp-ralph` on the (revised) plan and let
   it run its normal lifecycle to its own green (archive + report). ralph
   builds; ralph does not judge.

6. **`integrity`.** `python -m review_gate.cli integrity --phase <P>`.
   Exit 1 → the bar/fixtures were edited inside the judged diff: go to
   step 10 FAIL. Exit 2 → HALT for human.

7. **`provenance`** (phase 3 only — no-op otherwise).
   `python -m review_gate.cli provenance --phase <P>`. Exit 1 → FAIL
   (step 10). The Phase-3 RAG gold set must be owner-seeded or
   codex-authored and committed *before* the harness; ralph may not
   author its own ground truth.

8. **Review panel — run all legs in parallel on the frozen diff** (the
   range is `<base_sha>..HEAD`; get `base_sha` from
   `python -m review_gate.cli status`):

   - **A · codex adversarial (independent model, BLOCKING).** Run
     `/codex:adversarial-review --wait --base <base_sha>`. Normalize its
     output to a verdict: `severity` = the highest it reports
     (`BLOCKER`/`MAJOR`/`MINOR`/null), `passed` = no BLOCKER/MAJOR.
   - **B · test-integrity (objective, BLOCKING).** Run
     `python -m review_gate.cli mutation --phase <P>` AND
     `python -m pytest --cov --cov-fail-under=<coverage_floor*100> -q`
     (read `coverage_floor` from `.claude/review-gate.config.json`).
     `passed` = both exit 0.
   - **C · security.** Dispatch the Agent tool with
     `subagent_type="agent-skills:security-auditor"`, fresh context, asked
     to review only the frozen diff. Normalize to a verdict.
   - **D · code review.** Dispatch the Agent tool with
     `subagent_type="agent-skills:code-reviewer"`, fresh context, frozen
     diff only. Normalize to a verdict.
   - **E · regression.** Run that phase's PRD `CHECK:` commands verbatim.
     `passed` = every CHECK exits 0.
   - **F · test-engineer (ADVISORY — never blocks).** Dispatch the Agent
     tool with `subagent_type="agent-skills:test-engineer"`, fresh
     context, frozen diff only, asked "are these the right cases? what
     branch/edge is untested?" Record it as a verdict named
     `test_engineer`. It is evidence for the report; mutation (leg B) is
     the objective test bar, not this opinion.

   Write the normalized verdicts to `.claude/review-gate.verdicts.json`
   as a list of `{"name","passed","severity","summary"}`. The five
   required legs use `name` ∈ `codex|test_integrity|security|code|regression`;
   include the advisory leg as `name: "test_engineer"`.

9. **`aggregate`.**
   `python -m review_gate.cli aggregate --phase <P> --verdicts .claude/review-gate.verdicts.json`.
   This writes the base-SHA-bound PASS token. `test_engineer` is recorded
   in evidence but never affects the verdict. Exit 0 = PASS, 1 = FAIL.

10. **Route.**
   - **PASS:** `python -m review_gate.cli complete --phase <P>`. Exit 0 →
     the PRD row is now `complete` with an evidence line. Commit the PRD
     change (`git add .claude/PRPs/compliance-prod-hardening.prd.md &&
     git commit -m "phase <P>: gate PASS"`). Go to step 1 for the next
     phase. Exit 2 → chokepoint refused (no valid token): HALT, report.
   - **FAIL:** Write the consolidated panel findings to
     `.claude/findings-<P>-r<round>.md`. If `round` (from
     `review_gate.cli status`) is < 3: increment it (see "Round
     bookkeeping" below — NOT via re-`init`, which is resume-safe and
     would not advance the counter), then spawn remediation: invoke
     `prp-core:prp-ralph` afresh on the same plan with an appended task
     "Fix the ROOT CAUSE of the findings in
     `.claude/findings-<P>-r<round>.md`. Do NOT weaken tests, thresholds,
     fixtures, or the gold set.", then return to step 6 (re-gate the
     same pinned base SHA — accumulated work judged whole). If `round`
     ≥ 3: **STOP**, leave the phase `in-progress`, emit a consolidated
     report. No silent pass, ever.

## Round bookkeeping

The round counter lives in gate state. On a FAIL that will remediate,
bump it: `python -c "import json,pathlib;p=pathlib.Path('.claude/review-gate.state.json');d=json.loads(p.read_text());d['round']+=1;d['status']='remediating';p.write_text(json.dumps(d,indent=2))"`.
Halt when it would exceed 3.

## Hard rules

- The `complete` chokepoint is the ONLY way a phase becomes `complete`.
  It refuses unless an independent PASS token bound to the exact judged
  base SHA exists. Do not hand-edit the PRD, the token, or the state.
- A reviewer process erroring (e.g. codex unavailable) is a gate FAIL
  → HALT for human, never a silent skip of an independent leg.
- `HUMAN-GATE:` items (billable `cdk deploy`/`bootstrap`) always HALT.
````

- [ ] **Step 2: Verify the skill is discoverable and self-consistent**

Run: `python -c "import pathlib,re; t=pathlib.Path('.claude/skills/phase-gate/SKILL.md').read_text(encoding='utf-8'); assert t.startswith('---'); assert 'name: phase-gate' in t; assert 'review_gate.cli complete' in t; print('skill OK')"`
Expected: `skill OK`

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/phase-gate/SKILL.md
git commit -m "add phase-gate orchestrator skill: the agent-facing loop"
```

---

### Task 11: PRD integration — completion rule + per-phase GATE lines

**Files:**
- Modify: `.claude/PRPs/compliance-prod-hardening.prd.md`

- [ ] **Step 1: Add the completion-authority sentence**

In `.claude/PRPs/compliance-prod-hardening.prd.md`, in the "Success Criteria" preamble, find the paragraph beginning `**Rule for /goal / prp-ralph:**`. Append this sentence to the end of that paragraph (before the "Thresholds below" paragraph):

```
A phase reaches `complete` only via the `phase-gate` orchestrator's
`complete` chokepoint after the independent review panel passes; prp-ralph
finishing its plan is necessary but **not** sufficient, and prp-ralph never
edits the `Status` column.
```

- [ ] **Step 2: Add a GATE line to each phase's criteria block**

Under each of the `### Phase N — ...` headings in the Success Criteria section, add one line as the first bullet:

For Phase 2:

```
- GATE: panel PASS required — mutation kill-rate ≥ `review-gate.config.json` `mutation_floor`; coverage ≥ `coverage_floor`; codex adversarial no BLOCKER/MAJOR; security-auditor + code-reviewer no BLOCKER/MAJOR; all CHECK: items below green (regression leg). The plan is adversarially reviewed (codex + code-reviewer-verify) and revised before any build; test-engineer reviews case coverage as an advisory, non-blocking leg.
```

For Phase 3 (adds the provenance clause):

```
- GATE: panel PASS required — same panel as Phase 2, PLUS the gold-set provenance rule: `tests/evals/gold/PROVENANCE.md` declares an `owner` or `codex` author and the gold set is unmodified by the judged diff (ralph may not author its own ground truth).
```

For Phases 4, 5, 6 (Phase 4 and 6 keep their HUMAN-GATE/none lines unchanged):

```
- GATE: panel PASS required — same panel as Phase 2 (mutation+coverage / codex / security / code / CHECK-regression), evaluated on this phase's frozen diff before `complete`.
```

- [ ] **Step 3: Verify the edits are present and the table is intact**

Run: `python -c "import pathlib; t=pathlib.Path('.claude/PRPs/compliance-prod-hardening.prd.md').read_text(encoding='utf-8'); assert t.count('GATE: panel PASS required') == 5; assert 'never edits the \`Status\` column' in t; assert t.count('| 1 | Bedrock knowledge-layer IaC') == 1; print('PRD integration OK')"`
Expected: `PRD integration OK`

- [ ] **Step 4: Commit**

```bash
git add .claude/PRPs/compliance-prod-hardening.prd.md
git commit -m "PRD: phase-gate is the sole completion authority + per-phase GATE lines"
```

---

### Task 12: Full-suite regression + plan self-check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire repository test suite**

Run: `python -m pytest -q`
Expected: PASS — the pre-existing suites (`tests/test_agent_ids.py`, `tests/test_citations.py`, `infra/tests/`) AND the new `tests/review_gate/` suite all green; no collection errors. (`infra/tests` requires the `infra` extra; if it is not installed in this environment, run `python -m pytest tests -q` and note infra was exercised under its own venv per the bedrock plan — do not weaken or skip review_gate tests to make the command pass.)

- [ ] **Step 2: Confirm the gate package is not in the product wheel**

Run: `python -c "import tomllib,pathlib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); assert d['tool']['hatch']['build']['targets']['wheel']['packages']==['src/compliance_assistant']; print('wheel clean')"`
Expected: `wheel clean` (proves `review_gate/` stays out of the runtime closure).

- [ ] **Step 3: Confirm runtime loop files are ignored**

Run: `git status --porcelain .claude/review-gate.state.json .claude/review-gate.last-outcome.json`
Expected: empty output (both are gitignored; only `review-gate.config.json` is tracked).

- [ ] **Step 4: Final commit if anything is uncommitted**

```bash
git status --short
git add -A && git commit -m "chore: phase quality gate complete — full suite green" || echo "nothing to commit"
```

---

## Self-Review

**1. Spec coverage** (against `docs/superpowers/specs/2026-05-16-phase-quality-gate-design.md`):

- §2 outer loop not Stop-hook → Task 10 skill is an outer loop; no Stop hook anywhere. ✔
- §2/§3 mutation + codex both blocking → aggregate (Task 6) makes `test_integrity` and `codex` blocking; panel step 8 A+B. ✔
- §3 step-2 pre-build adversarial plan review (codex + code-reviewer-verify, revise+commit before build) → skill step 4. ✔
- §3 pinned base SHA, never recomputed across rounds → `init` keeps the pin (Task 9 `_cmd_init`); skill step 10 FAIL path re-gates same SHA. ✔
- §3 four-agent parallel panel + CHECK regression + advisory test-engineer → skill step 8 A–E (required) + F (advisory). ✔
- §3 step-6 aggregation rule (advisory legs evidence-only) → Task 6 `aggregate` + `test_test_engineer_is_advisory_never_blocks`. ✔
- §3 PASS flips PRD + Progress-Log evidence + advance → Task 7 + `_cmd_complete` + skill step 10. ✔
- §3 FAIL → fresh capped-3 ralph remediation then halt → skill step 10 + round bookkeeping. ✔
- §3 orchestrator owns the flip / ralph never does → `complete` chokepoint + token binding (Task 9) + PRD sentence (Task 11). ✔
- §4 honest independence + test-engineer advisory row → encoded operationally (codex+mutation are the BLOCKING legs in `aggregate`; test_engineer never blocks); skill labels A & B BLOCKING, F advisory. ✔
- §5 mutation objective + scoped pure-logic list → config (Task 2) + mutation (Task 5). ✔
- §5 frozen diff + integrity (edit-the-bar block) → Task 4 + `_cmd_integrity`. ✔
- §5 config/fixture integrity → protected set includes the config file + frozen fixtures (Task 9). ✔
- §5 Phase-3 gold-set provenance → Task 8 + `_cmd_provenance` + PRD GATE line (Task 11). ✔
- §6 PRD rule sentence + per-phase GATE lines + HUMAN-GATE orthogonal → Task 11; skill steps 1 & "Hard rules". ✔
- §7 components/boundaries (orchestrator, panel runner, state, config) → one file per responsibility. ✔ (Panel "runner" is the skill's step 8 + the CLI legs; there is no separate process — documented as the sequencing layer, consistent with §2 "skill/driver".)
- §8 failure handling (reviewer error = FAIL→HALT; resumable state) → skill "Hard rules" + Task 3 atomic resumable state + exit-code 2 = HALT. ✔
- §9 scope (this repo only; not running phases 2–6) → plan builds the gate only; running it is out of scope. ✔
- §10 residual risks → accepted in spec; nothing in the plan contradicts them. ✔
- §11 the gate must itself be tested (incl. test-engineer-never-blocks) → Tasks 2–9 are TDD with stubbed-panel/cap/integrity/tamper/provenance/advisory tests. ✔

No gaps. The two owner-approved additions (pre-build plan review, advisory test-engineer leg) are in the spec (§3 steps 2 & 5-F, §4 table) and mapped above.

**2. Placeholder scan:** no TBD/TODO; every code step has complete code; no "similar to Task N"; the only `_(none)_`/`_(not yet planned)_` strings are literal PRD fixture content in Task 7's test, not plan placeholders. ✔

**3. Type consistency:** `GateState` fields/`status` set, `Verdict`/`GateOutcome`, `MutationResult`, `ProvenanceResult`, `GateConfig`/`PhaseConfig`, `GOLD_MARKER`, CLI subcommand names and exit codes (0/1/2) are used identically across Tasks 2–11 and match the "Data contracts" block. The advisory `"test_engineer"` verdict uses the same `Verdict` shape; `aggregate` already excludes any non-required name from blocking (only `codex/security/code` are severity-checked and only `REQUIRED_LEGS` are missing-checked), so no code change was needed beyond the docstring + the advisory test. `flip_phase_complete(prd_path, phase, evidence)`, `write_outcome_token(path, base_sha, phase, outcome)`, `verify_gold_provenance(repo, base_sha)`, `integrity_violations(repo, base_sha, protected_paths)` signatures are consistent between definition and call sites. ✔

One refinement applied inline: the skill's FAIL path explicitly bumps `round` via a documented one-liner (round lives in gate state) rather than via `init`, since `init` is resume-safe and would not advance the counter — this keeps the cap-3 behaviour correct.
