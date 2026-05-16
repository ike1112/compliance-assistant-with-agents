# Phase 2 gate findings — round 1

**Verdict:** gate FAIL — blocking legs: `codex`, `test_integrity`.
**Judged base SHA:** a55cdf3a8657d4b29df8108e032e02e4b4bfa5c2 (pinned).
**Panel:** security PASS, code PASS, regression PASS, test_engineer (advisory) noted gaps.

The two FAILs are different in kind. Group A is genuine Phase 2 code,
fixable by a remediation build. Group B is quality-gate machinery —
**not Phase 2 code**, not fixable by a builder loop, needs an owner
decision (the builder must not alter the gate's bar/machinery).

---

## Group A — genuine Phase 2 code defects (remediable)

### A1 [HIGH, codex] SSM failures silently fall back to env-controlled agent IDs
`agent_ids.py` `_from_ssm()` catches every exception (boto3 import,
client creation, both `get_parameter` calls) and returns `None`;
`resolve_agent_ids()` then reads `AGENT_ID`/`AGENT_ALIAS_ID` from the
process environment. In a deployed run an `AccessDenied`,
`ParameterNotFound`, wrong region, or malformed response silently
downgrades to env-controlled ids instead of failing closed on the
infra-published source of truth. `tests/test_agent_ids.py::test_partial_ssm_failure_falls_back_to_env`
(added this phase) enshrines the unsafe behaviour. security-auditor
concurs this is a prod-readiness source-confusion gap (it is not a
*bypass* — the env value is still placeholder-gated).
**Root-cause fix:** fail closed for post-boto3 / permission /
configuration SSM failures; restrict the env fallback to the genuine
local-no-SSM case behind an explicit opt-in (e.g. `USE_ENV_AGENT_IDS`);
update the partial-failure test to expect an error. Note: this expands
hardening into the agent-id path the plan had scoped out — that scoping
decision is itself the gap.

### A2 [MEDIUM, codex] Placeholder validation bypassed by surrounding whitespace
`resolve_agent_ids()` passes raw SSM/env values into the placeholder
check, which only rejects empty or literal `replace-with-` prefix. A
copied `.env` value `AGENT_ID=' replace-with-...'` (leading space) is
non-empty and not prefixed → passes startup validation and reaches
`BedrockInvokeAgentTool`, defeating the fail-fast guarantee that is the
entire point of Phase 2. The plan deliberately did **not** strip
agent-id values ("Phase 1's algorithm, out of scope"); that decision is
the defect — TOPIC/MODEL were stripped, agent ids were not.
**Root-cause fix:** strip (or reject non-stripped) agent-id values
before the placeholder check in `resolve_agent_ids` (keep the
mutation-frozen primitive itself byte-identical); add whitespace-prefixed
placeholder tests.

### A3 [advisory, test_engineer] test hardening
- Add `pytest.raises(RuntimeError, match="AGENT_ALIAS_ID")` / `"AGENT_ID"`
  so the `agent_ids.py:66-67` name-arg mutants are killed (protects the
  0.80 mutation floor once the mutation leg can run again).
- Assert directly that importing `crew`/`main` performs no AWS/SSM call
  (the literal BLOCKER invariant), not incidentally via TOPIC-unset.
- Cover `validate_startup_config` happy path with SSM-supplied ids.

---

## Group B — quality-gate machinery defects (NOT Phase 2 code; owner decision)

These are why `test_integrity` cannot produce an honest PASS regardless
of code quality. They live in `review_gate` / its config / the env, i.e.
the bar's own machinery — outside builder authority.

### B1 mutmut 2.5.1 crashes on Windows → mutation leg cannot run
`review_gate.mutation.run_mutation` shells `mutmut run`. mutmut 2.5.1
prints a `🎉` (U+1F389) and dies with `UnicodeEncodeError: 'charmap'
codec can't encode` under the Windows cp1252 console, so `mutmut
results` is empty and the gate FAILs closed ("no scored mutants").
Verified independently: the pytest baseline is clean (`python -m pytest
-x -q` → 106 passed) and the package imports — the mutation *target* is
fine; mutmut itself is the failure. Also surfaced en route: mutmut was
not installed anywhere (the `gate` extra was never installed — I
installed `mutmut==2.5.1`/`pytest-cov`), and the gate's runner
`python -m pytest -x -q` has no `PYTHONPATH=src` (worked around with an
editable install). Candidate fixes (all in gate machinery): set
`PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8` in the mutmut subprocess env;
or pin a mutmut without the emoji print; or run the gate under the
project `.venv`. **Owner decision — this is the gate's code/deps.**

### B2 coverage floor structurally unreachable for a config-only phase
`pytest --cov --cov-fail-under=90` → 71.68%. `main.py` (44%) and
`crew.py` (65%) need `crewai_tools`, which is absent in the documented
base test interpreter; `citations.py` (76%) is Phase 3's module, not
touched here. A whole-repo 90% floor cannot be met by a phase that only
hardens config, under the documented env. New code itself is fully
covered (`startup.py` 100%). Candidate fixes (gate config/skill):
scope `--cov` to the phase's changed modules; per-phase coverage
targets; or install `crewai` in the gate env. **Owner decision — this
is `coverage_floor` / the skill's leg-B command.**

---

## Why the loop is paused, not auto-remediating

The orchestrator's FAIL route would increment the round and spawn a
fresh remediation ralph. That would address Group A but **cannot** fix
Group B: a builder loop may not rewrite `review_gate`, its config, or
the skill's leg commands, and must not weaken the bar. With B unresolved
the gate can never mint a PASS no matter how good the code, so auto-
looping would burn all three rounds and STOP anyway. Halting for an
owner decision is the correct, non-gaming action (phase-gate: gate
machinery problems HALT for human; never a silent skip or self-fix).
