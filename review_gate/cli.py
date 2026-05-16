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
from review_gate.aggregate import Verdict, aggregate, write_outcome_token
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


def _integrity_hits(repo: Path, phase: str, base_sha: str) -> list[str]:
    """Protected paths (the bar file + this phase's frozen fixtures) that
    were touched anywhere in the judged window. Shared by `integrity` and
    re-asserted at token-mint time so the deterministic core — not the
    skill's step ordering — enforces the anti-gaming invariant."""
    cfg_p, _, _, _ = _paths(repo)
    cfg = load_config(cfg_p)
    protected = [CONFIG_REL]
    pc = cfg.phases.get(phase)
    if pc:
        protected += pc.frozen_fixture_paths
    return diff.integrity_violations(repo, base_sha, protected)


def _cmd_integrity(repo: Path, phase: str) -> int:
    _, state_p, _, _ = _paths(repo)
    st = load_state(state_p)
    if st is None:
        print("no gate state; run init first", file=sys.stderr)
        return USAGE
    hits = _integrity_hits(repo, phase, st.base_sha)
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
    raw = json.loads(Path(verdicts_path).read_text(encoding="utf-8"))
    verdicts = [Verdict(**v) for v in raw]
    outcome = aggregate(verdicts)

    # Re-assert the deterministic guards here so a minted PASS token can
    # never outlive a bar/fixture/gold-set tamper, regardless of whether
    # the skill called `integrity`/`provenance` first or was interrupted.
    hits = _integrity_hits(repo, phase, st.base_sha)
    if hits:
        outcome.passed = False
        if "integrity" not in outcome.blocking:
            outcome.blocking = sorted({*outcome.blocking, "integrity"})
    if phase == "3":
        prov = verify_gold_provenance(repo, st.base_sha)
        if not prov.ok:
            outcome.passed = False
            if "provenance" not in outcome.blocking:
                outcome.blocking = sorted({*outcome.blocking, "provenance"})

    write_outcome_token(token_p, base_sha=st.base_sha, phase=phase,
                        round_=st.round, outcome=outcome)
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
    if st.status != "reviewing":
        # complete may only consume the token minted by the most recent
        # aggregate; any other state means no fresh independent verdict.
        print(f"refusing: state is {st.status!r}, expected 'reviewing' "
              f"(run aggregate)", file=sys.stderr)
        return USAGE
    tok = json.loads(Path(token_p).read_text(encoding="utf-8"))
    if not (tok.get("passed") is True
            and tok.get("base_sha") == st.base_sha
            and tok.get("phase") == phase
            and tok.get("round") == st.round):
        print("refusing: PASS token does not match this judged base SHA "
              "and round", file=sys.stderr)
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
    # --repo is shared by the top level AND every subcommand (callers pass
    # it after the subcommand), so it lives on a parent parser.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".")

    parser = argparse.ArgumentParser(prog="review_gate", parents=[common])
    sub = parser.add_subparsers(dest="cmd")
    for name in ("init", "integrity", "mutation", "provenance", "complete"):
        sp = sub.add_parser(name, parents=[common])
        sp.add_argument("--phase", required=True)
    agg = sub.add_parser("aggregate", parents=[common])
    agg.add_argument("--phase", required=True)
    agg.add_argument("--verdicts", required=True)
    sub.add_parser("status", parents=[common])

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
