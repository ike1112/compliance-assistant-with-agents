# Demo script

A short outline for presenting or recording a walkthrough of this project, plus
the evidence checklist behind each beat. The whole demo runs on the **free,
offline path** — no AWS spend. For an actual live deployment, see
[`live-launch.md`](live-launch.md).

## One-line framing

An AWS sample compliance assistant (CrewAI + Bedrock) that was
production-hardened against the AWS Well-Architected GenAI Lens: IaC, an offline
RAG eval harness, observability with test-enforced SLOs, and a six-leg quality
gate — every claim verified at synth time and by tests, not by a live console.

## Beats

### 1. The problem (30s)

Open [`ARCHITECTURE.md`](../ARCHITECTURE.md) §1: the starting point was a
click-ops sample — no IaC, no evals, no observability, placeholder IDs in
`.env`. Frame the work as making it defensible to a senior reviewer.

### 2. It reproduces green on a clean checkout (2 min — the credibility beat)

Run the quick-start from [`../README.md`](../README.md):

```bash
uv sync && uv sync --extra infra && uv sync --extra gate
cd infra && npx aws-cdk@latest synth --all -q && cd ..
PYTHONPATH=src python -m pytest tests infra/tests -q
PYTHONPATH=src python -m pytest tests/evals -m gate -q
```

All four exit 0, deterministically, with no Bedrock calls. This is the
"it actually works" moment — show the green output.

### 3. The wedge: the RAG eval harness (2 min)

This is the differentiator, not the IaC. Open [`evals.md`](evals.md) and
[ADR 0004](adr/0004-codex-authored-frozen-gold-set.md): the gold set is authored
by a separate model and **frozen** — a test fails if the judged diff touches it,
so the system cannot grade its own answers. Show the gate thresholds
(faithfulness, citation-correctness, not-found-honesty) and
`tests/evals/report.md` (the chunking decision is data, not opinion).

### 4. The architecture (1 min)

Show the diagram ([`diagrams/compliance-assistant-v12.png`](diagrams/compliance-assistant-v12.png)):
the numbered request flow (operator → runtime → agent → KB → Aurora → report)
and the ingestion + observability bands. Narrate one request using the
right-side walkthrough or [`SYSTEM.md`](SYSTEM.md).

### 5. Decisions + maturity (1 min)

Open [`adr/`](adr/): point at the cost-driven vector-store choice
([0001](adr/0001-aurora-pgvector-over-opensearch.md)) and the
owner-acceptance override of a contested gate FAIL
([0007](adr/0007-owner-acceptance-override.md)) — a real practice adjudicating a
gate dispute with a written, preserved-as-dissent defense. Mention the threat
model ([`threat-model.md`](threat-model.md)) for the compliance angle.

### 6. Observability is test-enforced, not aspirational (30s)

[`SLOs.md`](SLOs.md) is the single source of truth; the observability stack
synthesizes exactly one alarm per row and a test cross-checks the thresholds
([ADR 0006](adr/0006-slos-md-single-source.md)). Editing the doc moves the
alarm.

### 7. Close (15s)

Synth + test ≠ deploy: the billable `cdk deploy` is an explicit operator
decision, not an autonomous step. That line — drawn at "anything the
CloudFormation API mutates in real AWS" — is deliberate cost discipline.

## Evidence checklist (for a recording)

- [ ] terminal showing all four quick-start commands exiting 0
- [ ] the green RAG eval gate + `tests/evals/report.md`
- [ ] the architecture diagram on screen
- [ ] the `docs/adr/` index and one ADR open
- [ ] (optional, live) a real run's `2-report.md` from the report bucket — see
      [`live-launch.md`](live-launch.md)
