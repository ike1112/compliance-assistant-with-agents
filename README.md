# Compliance Assistant — production-hardened reference sample

A CrewAI + Amazon Bedrock compliance-research assistant that turns a regulation
topic (e.g. *"Latest PCI DSS requirements for trading platforms"*) into a
cited report. The project started as an AWS sample and was production-hardened
against the [AWS Well-Architected GenAI Lens](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html)
across six phases (IaC, config hardening, RAG evals, runtime IaC,
observability, and a final evidence-backed audit). For the engineering
narrative, see [ARCHITECTURE.md](ARCHITECTURE.md). For the WA-Lens audit
itself, see [docs/analysis/2026-05-16-compliance-prod-readiness.md](docs/analysis/2026-05-16-compliance-prod-readiness.md).

## Current status

The work was done as **synth-time IaC plus offline tests** — every CHECK in
the [PRD](.claude/PRPs/compliance-prod-hardening.prd.md) is autonomous and
deterministic (no AWS spend). The billable `cdk deploy` is gated as an
explicit operator decision, not an autonomous step, because the deployed
stack runs Aurora pgvector, Bedrock Agent, KB ingestion, and AgentCore
Runtime — all of which carry real cost. See the *HUMAN-GATE* rows in the PRD.

| Layer | What ships | Verified by |
|------|------------|-------------|
| Bedrock knowledge layer (KB, Aurora pgvector, Agent + Guardrail) | CDK synth → 5 templates | [`infra/stacks/kb_stack.py`](infra/stacks/kb_stack.py), [`infra/stacks/agent_stack.py`](infra/stacks/agent_stack.py), [`infra/tests/`](infra/tests/) (cfn-guard COMPLIANT) |
| Config & secrets | Fail-fast startup validation; env-gated verbosity | [`src/compliance_assistant/startup.py`](src/compliance_assistant/startup.py), [`tests/test_startup.py`](tests/test_startup.py) |
| RAG evaluation harness | Offline gold-set gate (PCI DSS), LLM-as-judge | [`tests/evals/`](tests/evals/) — `pytest tests/evals -m gate` |
| AgentCore Runtime IaC | Runtime + ECR stacks, async pre-start shim | [`infra/stacks/runtime_stack.py`](infra/stacks/runtime_stack.py), [`infra/stacks/runtime_ecr_stack.py`](infra/stacks/runtime_ecr_stack.py) |
| Observability + SLOs | EMF tracing, redaction, SLO-anchored alarms | [`src/compliance_assistant/tracing.py`](src/compliance_assistant/tracing.py), [`tests/test_tracing.py`](tests/test_tracing.py), [`docs/SLOs.md`](docs/SLOs.md), [`infra/stacks/observability_stack.py`](infra/stacks/observability_stack.py) |
| WA-Lens audit | All 7 pillars, 6-field Reasoning-Gate findings | [`docs/analysis/2026-05-16-compliance-prod-readiness.md`](docs/analysis/2026-05-16-compliance-prod-readiness.md), receipts under [`docs/analysis/_evidence/`](docs/analysis/_evidence/) |
| Quality gate (meta) | 6-leg adversarial review panel with mutation + coverage floors | [`review_gate/`](review_gate/), [`tests/review_gate/`](tests/review_gate/) |

**What is NOT deployed:** none of the above runs on real AWS in this repo.
Every claim above is verified at synth time and by tests, not by a live
CloudWatch dashboard. The HUMAN-GATE deploy is intentional cost discipline,
not an incomplete phase — see the *Engineering posture* section below.

## Quick start (local validation, no AWS spend)

Requires Python 3.10+ and Node (for the CDK CLI).

```bash
# 1. Install
pip install uv
uv sync                                # runtime deps
uv sync --extra infra                  # + CDK toolchain for synth
uv sync --extra gate                   # + mutation/coverage for the review gate

# 2. Synthesize the full stack (5 templates, no deploy)
cd infra
npx aws-cdk@latest synth --all -q
cd ..

# 3. Run the full test suite (Python + CDK assertion tests)
PYTHONPATH=src python -m pytest tests infra/tests -q

# 4. Run the offline RAG eval gate
PYTHONPATH=src python -m pytest tests/evals -m gate -q
```

All four commands should exit 0 on a clean checkout. The eval gate runs
deterministically against recorded fixtures — no Bedrock calls are made.
Live re-recording is opt-in via `-m live` (see [`tests/evals/test_live.py`](tests/evals/test_live.py)).

## Engineering posture (the non-obvious choices)

A few decisions are worth surfacing because they tend to look like gaps but
are deliberate:

- **Synth + test ≠ deploy.** The PRD's `CHECK:` items are autonomous and
  free; `HUMAN-GATE:` items are operator-gated because they cost money.
  An autonomous loop that runs `cdk deploy` would burn through cloud spend
  and silently drift the stack. The line is drawn at "anything the
  CloudFormation API mutates in real AWS."
- **`docs/` is mostly working notes.** Only named deliverables are tracked
  (SLO contract, eval contract, the WA-Lens audit + receipts). The original
  spec and plan documents stay untracked because they have been superseded
  by code that is the source of truth. See `.gitignore` for the exact list.
- **Phase 6 closed by owner-acceptance, not gate PASS.** The 6-leg quality
  gate returned FAIL on a contested finding from the codex adversarial
  leg; the other five legs (security, code review, test-engineer mutant
  sweep, regression, mutation floor 0.881) refuted it, and the owner
  adjudicated and overrode with a written defense in the PRD Progress
  Log. The dissenting record is preserved in
  `.claude/review-gate.verdicts.json`. This is in `ARCHITECTURE.md` because
  the override is mature engineering judgment, not a hidden gap.
- **The 6-leg quality gate is part of the system, not external CI.**
  `review_gate/` ran on every phase and is itself tested
  ([`tests/review_gate/`](tests/review_gate/)). It is what made the
  multi-phase autonomous work credible.

## Repository layout

```
infra/              CDK stacks (kb, agent, runtime, ecr, observability)
infra/tests/        Python assertion tests on synthesized templates
src/compliance_assistant/
                    Crew (agents.yaml, tasks.yaml, crew.py, main.py),
                    tracing, redaction, startup validation, citations
tests/              Top-level Python tests (startup, citations, tracing,
                    redaction, agent_ids, prod_readiness)
tests/evals/        RAG evaluation harness: gold set, retrieval +
                    generation + task metrics, judge prompts, CI gate
tests/review_gate/  Tests covering the quality-gate machine itself
review_gate/        Quality-gate orchestration (panel, mutation, diff,
                    aggregation, provenance, PRD updates)
docs/               Tracked: SLOs.md, evals.md, analysis/ (the WA-Lens
                    audit + evidence). Other files are local working
                    notes (gitignored).
analysis/_legacy/   Pre-hardening AWS-sample artifacts, kept for
                    provenance. See its own README.
.claude/PRPs/       PRD + per-phase plans (tracked). Internal artifacts
                    (ralph archives, findings) are also here.
```

## Configuring + running the crew

The crew itself is a CrewAI sequential pipeline (researcher → writer →
designer) that delegates retrieval to a Bedrock Agent. Configuration is
read from `.env` with fail-fast validation
([`src/compliance_assistant/startup.py`](src/compliance_assistant/startup.py)) —
the application refuses to start with placeholder values, missing IDs, or
invalid models.

After deploy, the Bedrock Agent/KB IDs are published to SSM and read at
startup; you do **not** copy them into `.env` manually (that was the
click-ops baseline; Phase 1 replaced it). See
[`.env.example`](.env.example) for the contract.

To run the crew (assumes a deployed stack and valid AWS credentials):

```bash
crewai run
```

The crew writes to `output/1-requirements.md` (research),
`output/2-report.md` (full report — final line is a `## Sources` block
with citation IDs), and `output/3-solution.md` (the proposed AWS
control implementation).

## License

MIT-0. See [LICENSE](LICENSE).
