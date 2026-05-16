# Feature: Config & secrets hardening — fail-fast startup validation

## Summary

Make the crew refuse to start when its required configuration is missing
or still a `.env.example` placeholder, instead of failing deep inside a
Bedrock call (or, worse, running with a wrong value). Centralise startup
validation for `TOPIC`, `MODEL`, and the agent-id resolution path; gate
the currently-hardcoded CrewAI verbosity behind an env flag that defaults
**off**; add a `.env.example` parity test so a newly-read env key can
never silently go undocumented; and verify the dependency lockfile is
frozen-installable and tracked. No new runtime dependencies — the
validation is stdlib-only, so `uv sync --frozen` stays green.

Closes GAP-SEC-04 (placeholder/secret config reaching runtime),
GAP-OPS-04 (no fail-fast config contract), GAP-OPS-05 (lockfile /
`.env.example` drift).

## User Story

As an operator running the compliance crew
I want it to fail immediately and clearly when config is missing, empty,
or a left-in placeholder
So that I never get a confusing mid-run Bedrock failure or a silent run
against the wrong agent/model, and so a teammate cloning the repo has a
`.env.example` that is provably complete.

## Problem Statement

Today:

- `main.py:21-23` validates only `TOPIC`, only for `None` (not empty
  string, not the placeholder), with a generic `Exception`.
- `MODEL` is never validated by project code (CrewAI reads it lazily; a
  missing/placeholder `MODEL` surfaces as an opaque downstream error).
- Agent-id validation exists and is correct (`agent_ids.py`) but is only
  reached lazily when the crew runs, so a misconfigured agent id is not
  reported at startup.
- All four `verbose=` sites in `crew.py` are hardcoded `True` — no way
  to get a quiet run without editing source.
- Nothing prevents a newly-added `os.environ[...]` key from being absent
  in `.env.example`, or the lockfile from drifting out of frozen-sync.

Each is independently testable (see Validation).

## Solution Statement

Introduce one small, dependency-free module
`src/compliance_assistant/startup.py` that exposes two pure functions:

- `validate_startup_config(env)` — **strips then** rejects
  missing/empty/whitespace-only/`replace-with-` values for `TOPIC` and
  `MODEL`, then exercises the **existing** agent-id resolution path
  (`resolve_agent_ids()`) so all three required inputs are checked at
  startup with one clear `RuntimeError`. The `.strip()` lives in
  `startup.py`, **not** in the mutation-frozen primitive.
- `crew_verbose_enabled(env)` — parses a `CREW_VERBOSE` flag, **default
  off**.

Promote the existing private `agent_ids._reject_placeholder` to a public
`reject_missing_or_placeholder` and reuse it from `startup.py`, so the
missing/placeholder primitive stays in the one module the gate
mutation-tests (`src/compliance_assistant/agent_ids.py`) — no behaviour
change, just a rename + re-export.

**Validation is function-scoped, not import-time** (revised per
adversarial review — see Notes). `main.py` calls
`validate_startup_config(os.environ)` as the **first statement of each
entry function** (`run`/`train`/`replay`/`test`), *not* at module load.
Rationale: `validate_startup_config` calls `resolve_agent_ids()`, which
tries SSM (boto3 import + `ssm.get_parameter` network/credential I/O)
before env fallback. Putting that at module load would make a bare
`import compliance_assistant.main` perform AWS I/O and would poison
`pytest infra/tests tests` collection (CHECK 5) — a BLOCKER both
reviewers raised. Function-scoped keeps the module a pure, side-effect-
free import while still failing fast: the validation is the first thing
any CLI command does, before any spend. `crew.py` reads
`crew_verbose_enabled(os.environ)` once and feeds it to all four
`verbose=` sites (it imports **only** `crew_verbose_enabled`, never
`validate_startup_config`, so the `import compliance_assistant.crew`
contract is structurally preserved).

`crew.py`'s lazy agent-tool construction is preserved, so
`PYTHONPATH=src python -c "import compliance_assistant.crew"` still
imports with no configured ids (Phase 1's CHECK). Startup validation
lives on the `main.py` entry path, not at `crew` import.

## Metadata

| Field            | Value                                                                 |
| ---------------- | --------------------------------------------------------------------- |
| Type             | ENHANCEMENT                                                           |
| Complexity       | MEDIUM                                                                |
| Systems Affected | `compliance_assistant.startup` (new), `agent_ids`, `main`, `crew`, `.env.example`, tests |
| Dependencies     | None new (stdlib `os`, `ast`, `subprocess`; existing `pytest`)        |
| Estimated Tasks  | 7                                                                     |

---

## UX Design

### Before State

```
 operator sets .env (TOPIC left blank OR AGENT_ID still
 "replace-with-...") ──► crewai run ──► import main.py
        │                                   │
        │  (TOPIC=None only check)          ▼
        │                          crew().kickoff()
        │                                   │
        │                                   ▼
        │                       _build_agent_tool() ──► resolve_agent_ids()
        │                                   │
        ▼                                   ▼
  empty TOPIC slips through         RuntimeError raised HERE — deep in the
  into agent prompts; MODEL         run, after model spend / partial output,
  never checked                     with no single up-front contract
```

PAIN_POINT: failures are late, partial, and per-variable. `verbose=True`
is unconditional — no quiet runs.

### After State

```
 operator sets .env ──► crewai run ──► import main.py (NO side effects)
                                          │
                                          ▼
                            run() / train() / replay() / test()
                                          │ first statement:
                                          ▼
                          validate_startup_config(os.environ)
                          ├─ TOPIC  strip→missing/placeholder ─┐
                          ├─ MODEL  strip→missing/placeholder ─┤─► one
                          └─ resolve_agent_ids() (agent-id path)┘   RuntimeError
                                          │ all ok                  with remediation
                                          ▼
                                  crew().kickoff()  (verbose = CREW_VERBOSE, default off)
```

VALUE_ADD: one clear error before any spend; quiet by default, opt-in
verbose; `.env.example` provably complete; lockfile provably frozen.

### Interaction Changes

| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| `crewai run` with bad/blank config | late mid-run `RuntimeError` or silent wrong run | immediate `RuntimeError` at startup naming the offending var + remediation | fails fast, no wasted spend |
| crew log noise | always verbose | quiet unless `CREW_VERBOSE` truthy | clean default output |
| adding a new env key | could go undocumented | parity test fails until added to `.env.example` | docs stay honest |

---

## Mandatory Reading

| Priority | File | Lines | Why Read This |
|----------|------|-------|---------------|
| P0 | `src/compliance_assistant/agent_ids.py` | all | Pattern to MIRROR + the module to extend (public rename). The mutation-tested module. |
| P0 | `src/compliance_assistant/main.py` | 1-23 | The weak check being replaced; module-load timing |
| P0 | `src/compliance_assistant/crew.py` | all | 4 `verbose=True` sites; import graph; preserve lazy id resolution |
| P1 | `tests/test_agent_ids.py` | all | Exact test pattern to FOLLOW (monkeypatch env + `sys.modules`, `pytest.raises(RuntimeError)`) |
| P1 | `.env.example` | all | Keys to keep in parity; add `CREW_VERBOSE` |
| P2 | `tests/review_gate/conftest.py` | all | conftest-for-import pattern (only if a path shim is needed; likely not) |
| P2 | `pyproject.toml` | `[tool.pytest.ini_options]`, `[project.optional-dependencies]` | `testpaths`; no runtime dep added → lock stays frozen |

**External Documentation:** none required — stdlib only, existing
patterns suffice.

---

## Patterns to Mirror

**MISSING/PLACEHOLDER REJECTION (the primitive to promote, not reinvent):**

```python
# SOURCE: src/compliance_assistant/agent_ids.py:20-28
def _reject_placeholder(name: str, value: str) -> str:
    if not value or value.startswith(_PLACEHOLDER_PREFIX):
        raise RuntimeError(
            f"{name} is unset or still a placeholder ({value!r}). "
            f"Deploy the infra stack (it publishes the ids to SSM) or "
            f"set a real value in .env."
        )
    return value
```

**ENV-VAR TEST PATTERN (mirror exactly in tests/test_startup.py):**

```python
# SOURCE: tests/test_agent_ids.py:30-41
def test_placeholder_is_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setenv("AGENT_ID", "replace-with-your-amazon-bedrock-agent-id")
    monkeypatch.setenv("AGENT_ALIAS_ID", "whatever")
    with pytest.raises(RuntimeError):
        agent_ids.resolve_agent_ids()
```

**MODULE DOCSTRING / "why named this" CONVENTION:**

```python
# SOURCE: src/compliance_assistant/agent_ids.py:1-13
"""Resolve the Bedrock agent ids the crew talks to.
... rationale prose, then a note on the module name choice ...
"""
```

---

## Files to Change

| File | Action | Justification |
|------|--------|---------------|
| `src/compliance_assistant/agent_ids.py` | UPDATE | Promote `_reject_placeholder` → public `reject_missing_or_placeholder`; keep a private alias so internal call sites are untouched in behaviour. No logic change (mutation-stable). |
| `src/compliance_assistant/startup.py` | CREATE | `validate_startup_config(env)` + `crew_verbose_enabled(env)` — the new fail-fast contract |
| `src/compliance_assistant/main.py` | UPDATE | Remove module-load `TOPIC is None` check; call `validate_startup_config(os.environ)` as the first statement of each entry function (function-scoped, no import-time side effects) |
| `src/compliance_assistant/crew.py` | UPDATE | Compute `verbose = crew_verbose_enabled(os.environ)` once; feed all 4 `verbose=` sites |
| `.env.example` | UPDATE | Add documented `CREW_VERBOSE=` (default off) so parity holds |
| `tests/test_startup.py` | CREATE | Startup validation + verbosity-default + `.env.example` parity + `uv.lock`-tracked tests |
| `tests/test_agent_ids.py` | UPDATE | Track the public rename; add mutation-hardening edge cases on `agent_ids` |

---

## NOT Building (Scope Limits)

- **No validation of `AWS_REGION*`, `MAX_TOKENS`, `TEMPERATURE`.** They
  are boto3/CrewAI-consumed, have working defaults, and are out of the
  PRD Phase 2 scope (`TOPIC`, `MODEL`, agent-id path only).
- **No new config framework / settings object / pydantic.** A staff
  engineer would say "just reuse the existing reject primitive" — we do.
- **No change to the agent-id resolution algorithm** (SSM→env→reject) —
  only a visibility rename. Behaviour must stay mutation-identical.
- **No `--cov=` source change or pytest config edits** — the gate owns
  its coverage command; the plan only maximises coverage of new code.
- **No PRD `Status` edit.** The controlling `phase-gate` skill forbids
  hand-editing the PRD; `Status` flips only via the `complete`
  chokepoint. (Deliberate deviation from prp-plan's PRD-update step —
  the orchestrator rule wins.)

---

## Step-by-Step Tasks

Execute in order. Each task is atomic and independently verifiable.

### Task 1: UPDATE `src/compliance_assistant/agent_ids.py` — publicise the reject primitive

- **ACTION**: Rename `_reject_placeholder` → `reject_missing_or_placeholder`
  (public). Keep behaviour byte-identical (same conditions, same message,
  same return). Add a module-level backward-compat alias
  `_reject_placeholder = reject_missing_or_placeholder` so any
  in-module/internal reference and existing tests keep working.
- **IMPLEMENT**: only the rename + alias; the `if not value or
  value.startswith(_PLACEHOLDER_PREFIX)` logic is unchanged.
- **MIRROR**: existing docstring/comment density in this file.
- **GOTCHA**: This file is the gate's mutation target — do **not**
  change the conditional, the message, or `_PLACEHOLDER_PREFIX`; a
  semantic change here risks the mutation kill-rate. Rename only.
- **VALIDATE**: `PYTHONPATH=src python -m pytest tests/test_agent_ids.py -q`

### Task 2: CREATE `src/compliance_assistant/startup.py`

- **ACTION**: New stdlib-only module with a rationale docstring matching
  `agent_ids.py` style.
- **IMPLEMENT**:
  - `_TRUTHY = {"1", "true", "yes", "on"}`
  - `def crew_verbose_enabled(env: Mapping[str, str]) -> bool:` returns
    `env.get("CREW_VERBOSE", "").strip().lower() in _TRUTHY`. Unset/empty
    /unknown ⇒ `False` (default OFF).
  - `def validate_startup_config(env: Mapping[str, str]) -> None:`
    **strips first**, then rejects:
    `reject_missing_or_placeholder("TOPIC", env.get("TOPIC", "").strip())`
    and `reject_missing_or_placeholder("MODEL", env.get("MODEL", "").strip())`.
    The `.strip()` is here (in `startup.py`), deliberately NOT in the
    `agent_ids` primitive — so a whitespace-only value (`"   "`)
    normalises to `""` and is rejected, while Task 1's mutation-frozen
    primitive stays byte-identical. Then call `resolve_agent_ids()`
    (imported from `.agent_ids`) to exercise + validate the agent-id
    resolution path (agent-id values are NOT stripped — that path is
    Phase 1's algorithm, out of scope to alter). Returns `None` on
    success; raises `RuntimeError`.
- **IMPORTS**: `import os` is NOT needed here (env passed in for
  testability); `from collections.abc import Mapping`; `from
  compliance_assistant.agent_ids import reject_missing_or_placeholder,
  resolve_agent_ids`.
- **GOTCHA**: Pass `env` in (don't read `os.environ` inside) so tests
  drive it deterministically and coverage is clean. `resolve_agent_ids`
  reads `os.environ` itself — that's existing behaviour, fine; tests
  monkeypatch env + `sys.modules["boto3"]` exactly like
  `tests/test_agent_ids.py`.
- **VALIDATE**: `PYTHONPATH=src python -c "import compliance_assistant.startup"`

### Task 3: UPDATE `src/compliance_assistant/main.py` — function-scoped startup validation

- **ACTION**: Remove the module-level lines 21-23 (`topic =
  os.environ.get('TOPIC')` / `if topic is None: raise Exception(...)`).
  Add `from compliance_assistant.startup import validate_startup_config`
  at the top (cheap, side-effect-free import). Make
  `validate_startup_config(os.environ)` the **first statement inside
  each** of `run()`, `train()`, `replay()`, `test()`. After it returns,
  read `topic = os.environ['TOPIC']` locally where each function builds
  its `inputs` dict (or via a tiny `_topic()` helper) — `topic` is no
  longer a module global.
- **IMPLEMENT**: keep the explanatory comment about what `topic` feeds,
  moved to where it is now read; preserve each entry function's
  behaviour otherwise.
- **MIRROR**: existing comment style in `main.py`.
- **GOTCHA — this is the BLOCKER fix.** Validation MUST NOT run at
  module import: `validate_startup_config` → `resolve_agent_ids()` →
  `_from_ssm()` does a boto3 import + `ssm.get_parameter` network/
  credential probe before env fallback. At module load that would make a
  bare `import compliance_assistant.main` perform AWS I/O and would
  poison `pytest infra/tests tests` collection (CHECK 5). Function-scoped
  still fails fast (first line of every CLI command, before any spend)
  while keeping the module a pure import. Do NOT add validation to
  `crew.py` — Phase 1's `import compliance_assistant.crew` CHECK must
  keep passing with no configured ids.
- **VALIDATE**:
  `PYTHONPATH=src python -c "import compliance_assistant.main"` exits 0
  with a clean env **and performs no network call** (no AWS creds
  needed to import); `PYTHONPATH=src python -c "import
  compliance_assistant.crew"` exits 0 (unchanged). A unit test in Task 6
  asserts each entry function calls `validate_startup_config` before
  doing work (monkeypatch it to raise a sentinel, assert the sentinel
  propagates and no crew is built).

### Task 4: UPDATE `src/compliance_assistant/crew.py` — env-gated verbosity

- **ACTION**: At the top of the class (or module), compute
  `_VERBOSE = crew_verbose_enabled(os.environ)` once; replace all four
  hardcoded `verbose=True` (3 `Agent(...)` + 1 `Crew(...)`) with
  `verbose=_VERBOSE`.
- **IMPLEMENT**: `import os` and
  `from compliance_assistant.startup import crew_verbose_enabled` at top.
  Update the existing inline comments that say "Set False for a silent
  run" to reflect the new env flag.
- **GOTCHA**: `startup.py` imports from `agent_ids` only (no crewai), so
  importing it from `crew.py` adds no heavy import and does not break the
  `import compliance_assistant.crew` CHECK. Resolve `_VERBOSE` at import
  (module/class scope) — acceptable since it only reads an env string.
- **VALIDATE**: `PYTHONPATH=src python -c "import compliance_assistant.crew"`
  exits 0 **and** a static guard (Task 6 test) asserts `crew.py`'s import
  list contains `crew_verbose_enabled` and NOT `validate_startup_config`
  — structurally protecting the no-config crew-import contract.

### Task 5: UPDATE `.env.example` — document `CREW_VERBOSE`

- **ACTION**: Add a commented line + `CREW_VERBOSE=` (empty ⇒ off) with
  a one-line comment: verbosity is off unless set truthy
  (`1/true/yes/on`).
- **GOTCHA**: `CREW_VERBOSE` is read in `startup.py` via the injected
  `env` Mapping (`env.get("CREW_VERBOSE")`), NOT via `os.environ`. The
  parity scanner in Task 6 is therefore extended to also collect
  `<env>.get("K")`/`<env>["K"]` reads where the receiver is the
  conventional name `env`/`environ` (see Task 6) — so `CREW_VERBOSE`
  (and the relocated `MODEL`) ARE policed and MUST appear here.
- **VALIDATE**: covered by Task 6's parity test (which now genuinely
  fails if `CREW_VERBOSE`/`MODEL` are missing — verified by Task 6's
  self-check assertion).

### Task 6: CREATE `tests/test_startup.py`

- **ACTION**: One file covering PRD CHECK items 1–4 (see Validation).
- **IMPLEMENT** (mirror `tests/test_agent_ids.py` monkeypatch style):
  - **Startup validation (CHECK 1):** for each of `TOPIC`, `MODEL`:
    missing ⇒ `pytest.raises(RuntimeError)`; empty string ⇒ raises;
    **whitespace-only `"   "` ⇒ raises** (required assertion — proves
    the `startup.py` strip, resolves the prior plan contradiction);
    `replace-with-...` ⇒ raises. Agent-id path: with
    `monkeypatch.setitem(sys.modules,"boto3",None)` + placeholder
    `AGENT_ID` ⇒ `validate_startup_config` raises `RuntimeError`. Happy
    path: all valid (TOPIC, MODEL set; boto3 None; real `AGENT_ID`/
    `AGENT_ALIAS_ID`) ⇒ returns `None`, no raise. (boto3-stubbed-None
    mirrors the established `tests/test_agent_ids.py` convention; Phase 2
    does not re-litigate the agent-id algorithm — see Notes.)
  - **Entry-point wiring (CHECK 1, BLOCKER-fix guard):** for each of
    `run/train/replay/test`, monkeypatch
    `compliance_assistant.main.validate_startup_config` to raise a
    sentinel and `ComplianceAssistant` to a spy; assert calling the
    entry function raises the sentinel and the crew was **never**
    constructed (proves validation is function-scoped AND first).
    Separately assert `import compliance_assistant.main` triggers no
    call to `validate_startup_config` (module import is side-effect-free).
  - **Verbosity (CHECK 2):** `crew_verbose_enabled({})` is `False`;
    unset and `""` ⇒ `False`; `"false"`/`"0"` ⇒ `False`;
    `"1"/"true"/"YES"/"on"` ⇒ `True`. Assert default-off explicitly.
  - **`.env.example` parity (CHECK 3):** AST-walk every `*.py` under
    `src/`, collect string-literal keys from: (a) `os.getenv("K"...)`;
    (b) `os.environ.get("K"...)` / `os.environ["K"]`; **(c)
    `<recv>.get("K"...)` / `<recv>["K"]` where `<recv>` is an `ast.Name`
    whose id is in `{"env", "environ"}`** — this is the project
    convention for an injected env Mapping (documented in the test's
    module docstring) and is what catches `startup.py`'s
    `env.get("CREW_VERBOSE")` / `env.get("MODEL")` / `env.get("TOPIC")`.
    Parse `.env.example` keys (`^[A-Z_]+=` lines, ignore comments/
    blanks); assert scanned keys ⊆ `.env.example` keys (diff in the
    message). **Self-check assertion:** assert the scanned set contains
    `{"CREW_VERBOSE", "MODEL", "TOPIC"}` — this fails loudly if the
    scanner ever silently stops seeing the injected-`env` reads, so
    CHECK 3 can never go vacuous for this phase's keys (the exact
    failure mode codex/code-reviewer flagged).
  - **Lockfile tracked (CHECK 4 part):** assert `uv.lock` is git-tracked
    via `subprocess.run(["git","ls-files","--error-unmatch","uv.lock"])`
    returncode 0. (The `uv sync --frozen` exit-0 half is run by the gate
    regression leg as a command, not from pytest.)
- **IMPORTS**: `import ast, sys, subprocess, pathlib, pytest`;
  `from compliance_assistant.startup import validate_startup_config,
  crew_verbose_enabled`; `import compliance_assistant.main as cli`.
- **GOTCHA**: locate repo root from `__file__`
  (`pathlib.Path(__file__).resolve().parents[1]`) — do not assume CWD.
  Skip the git test cleanly (`pytest.skip`) only if not a git work tree;
  otherwise it must assert. The parity receiver-name rule is a
  convention, not type inference — keep it to the literal names
  `env`/`environ` and document that in the test so a future reader knows
  the contract (an env Mapping param must be named `env`).
- **VALIDATE**: `PYTHONPATH=src python -m pytest tests/test_startup.py -q`

### Task 7: UPDATE `tests/test_agent_ids.py` — rename + mutation hardening

- **ACTION**: Add a test referencing the new public name
  `agent_ids.reject_missing_or_placeholder` (keep existing tests, which
  still pass via the alias). Add edge cases that kill likely mutants in
  the gate's mutation target:
  - empty string vs `None`-like `""` both rejected;
  - a value that *contains but does not start with* `replace-with-`
    (e.g. `"x-replace-with-y"`) is **accepted** (kills a `startswith`→`in`
    mutant);
  - exact prefix `"replace-with-"` rejected; one char past prefix
    (`"replace-with-x"`) rejected; valid `"AG123"` returned unchanged;
  - `_from_ssm` partial failure (one `get_parameter` raises) ⇒ returns
    `None` ⇒ env fallback (kills the broad-`except` mutants).
- **GOTCHA**: do not weaken or delete existing assertions; only add.
  These tests defend the ≥ `mutation_floor` kill-rate on
  `agent_ids.py` — the gate will mutation-test exactly this file.
- **VALIDATE**: `PYTHONPATH=src python -m pytest tests/test_agent_ids.py -q`

---

## Validation (PRD Phase 2 CHECK items — verbatim; the gate regression leg)

The five lines below are reproduced **exactly** from
`.claude/PRPs/compliance-prod-hardening.prd.md` → "Phase 2 — Config &
secrets hardening". They are the regression leg of the gate panel and
the definition of done. Do not paraphrase or weaken them.

- CHECK: `pytest tests/test_startup.py -q` passes — startup raises a clear error on missing **or** `replace-with-` placeholder for every required var (TOPIC, MODEL, and the agent-id resolution path), not just TOPIC.
- CHECK: a test asserts crew verbosity follows an env flag and defaults **off**.
- CHECK: `.env.example` parity test — every `os.environ` key read under `src/` appears in `.env.example`.
- CHECK: `uv sync --frozen` exits 0 and `uv.lock` is git-tracked.
- CHECK: full prior suite (`pytest infra/tests tests`) still green.

### How each CHECK is satisfied

| CHECK | Satisfied by | Command |
|-------|--------------|---------|
| 1 | Task 6 startup tests + Tasks 2,3 | `PYTHONPATH=src python -m pytest tests/test_startup.py -q` |
| 2 | Task 6 verbosity tests + Task 4 | (same file) |
| 3 | Task 6 parity test + Task 5 | (same file) |
| 4 | `uv.lock` tracked (unchanged) + no new runtime dep | `uv sync --frozen` (gate runs this) + git ls-files |
| 5 | No behaviour regression; rename-only in `agent_ids` | `PYTHONPATH=src python -m pytest infra/tests tests -q` |

### Gate panel (informational — owned by the phase-gate skill, not this plan)

Beyond the CHECK regression leg, the phase-gate panel also enforces:
mutation kill-rate ≥ `mutation_floor` on `src/compliance_assistant/agent_ids.py`,
coverage ≥ `coverage_floor`, and codex / security-auditor / code-reviewer
with no BLOCKER/MAJOR. Task 1's rename-only discipline and Task 7's
edge cases exist to hold the mutation bar; Tasks 2/6 keep new code
fully covered.

---

## Edge Cases Checklist

- [ ] `TOPIC` / `MODEL` unset (key absent) → `RuntimeError`
- [ ] `TOPIC` / `MODEL` empty string → `RuntimeError`
- [ ] `TOPIC` / `MODEL` whitespace-only `"   "` → **stripped in
      `startup.py` → empty → `RuntimeError`** (DECIDED, not open;
      required assertion in Task 6)
- [ ] `replace-with-` exact / prefix+1 / contains-not-prefix
- [ ] agent-id path: placeholder / missing → `RuntimeError`; valid → ok
- [ ] `CREW_VERBOSE` unset, `""`, `"0"`, `"false"`, `"1"`, `"TRUE"`,
      `"on"`, garbage
- [ ] `.env.example` parity: a key added to src but not example → test
      fails (verify by reasoning, not by leaving a real gap)
- [ ] not a git work tree → parity/lock test skips cleanly, never errors

---

## Acceptance Criteria

- [ ] All five PRD Phase 2 CHECK items (verbatim section above) pass
- [ ] `validate_startup_config` raises one clear `RuntimeError` naming
      the offending variable + remediation, for TOPIC, MODEL, and the
      agent-id path
- [ ] `crew_verbose_enabled` defaults **off**; all 4 `crew.py` sites
      honour it
- [ ] `.env.example` parity test is real (would fail on a true gap)
- [ ] `agent_ids.py` change is rename-only (no logic/message change) —
      mutation kill-rate unaffected or improved
- [ ] No new runtime dependency; `uv.lock` unchanged & tracked
- [ ] `import compliance_assistant.crew` still exits 0 with no config
- [ ] No regressions in `pytest infra/tests tests`

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Renaming the reject primitive perturbs the mutation kill-rate on `agent_ids.py` | MED | HIGH (gate FAIL) | Rename + alias only, zero logic change; Task 7 adds mutant-killing edge cases |
| Import-time AWS/SSM I/O via module-load validation (BLOCKER, both reviewers) | WAS HIGH | HIGH | RESOLVED: validation is function-scoped (Task 3) — `import main` is side-effect-free; Task 6 asserts no import-time call + no network on import |
| Parity scanner misses injected-`env` reads → CHECK 3 vacuous for new keys (MAJOR) | WAS HIGH | HIGH | RESOLVED: Task 6 scanner also collects `env`/`environ` Mapping reads + a self-check asserting `{CREW_VERBOSE,MODEL,TOPIC}` are seen |
| `.env.example` parity test too strict/loose (dynamic keys, comments) | LOW | MED | AST literal-key extraction only; receiver-name convention documented in the test; robust example parsing |
| Gate coverage leg (`pytest --cov --cov-fail-under=90`, no `--cov=` source) measures broadly and dips | MED | MED | Out of plan scope to change the gate command; keep new modules small + fully covered; flag to owner if the leg is mis-scoped |
| Whitespace-only value semantics | RESOLVED | LOW | DECIDED: strip in `startup.py` → empty → reject; required Task 6 assertion |

## Notes

- **Deliberate deviation:** prp-plan's template says to flip the PRD
  phase to `in-progress`. The controlling `phase-gate` skill explicitly
  forbids hand-editing the PRD; `Status` changes only through the
  `complete` chokepoint. This plan therefore does **not** touch the PRD.
- The agent-id resolution path is *reused, not reimplemented* — Phase 2
  hardens the *contract surface* (TOPIC/MODEL + startup timing +
  verbosity + parity + lockfile), not the agent-id algorithm Phase 1
  already shipped.
- Concentrating the reject primitive in `agent_ids.py` is intentional:
  it keeps the security-critical logic in the single module the gate
  mutation-tests, rather than spreading mutable logic into a new module
  the mutation leg does not target.
- **Revised per adversarial plan review** (codex + independent
  code-reviewer, both fresh-context). Three findings resolved before any
  build: (1) BLOCKER — module-load validation performed import-time AWS
  SSM/credential I/O and poisoned test collection → moved to
  function-scoped (first line of each entry point); `import main` is now
  side-effect-free, asserted by a Task 6 test. (2) MAJOR — the
  `.env.example` parity scanner only matched `os.environ`/`os.getenv`
  and would have gone vacuous for the phase's own new keys
  (`CREW_VERBOSE`, relocated `MODEL`) read via the injected `env`
  Mapping → scanner extended to the `env`/`environ` receiver convention
  plus a self-check assertion. (3) The whitespace-only contradiction was
  resolved with a definite strip-then-reject decision in `startup.py`
  (not in the mutation-frozen primitive). The agent-id leg's
  boto3-stubbed test convention is retained deliberately: it mirrors the
  already-accepted `tests/test_agent_ids.py` pattern, and Phase 2 does
  not redesign Phase 1's agent-id resolution algorithm.
