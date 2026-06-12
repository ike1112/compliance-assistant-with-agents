# RAG Evaluation Harness

The repo now has two complementary evaluation paths:

1. **Offline gate** for deterministic, no-spend regression protection.
2. **Live conformance** for post-deploy checks against the deployed Bedrock
   agent.

The offline gate stays the merge/CI contract. The live conformance run is the
production-proof contract.

## Offline gate

The offline system under test is:

1. Deterministic BM25 retrieval over the frozen corpus.
2. A recorded LLM answer generated strictly from the retrieved context.
3. A recorded LLM judge response, used only as corroborating evidence.

`pytest tests/evals -m gate` is offline and deterministic. It never trusts a
stored score. It recomputes retrieval metrics, citation correctness,
groundedness, not-found honesty, and requirement coverage from raw fixtures
bound to the committed prompt/rubric and retrieved-context hashes.

### Gate thresholds

- context-recall >= 0.90
- context-precision >= 0.80
- MRR >= 0.80
- groundedness >= 0.95
- faithfulness >= 0.95
- citation-correctness >= 0.95
- hallucination <= 0.05
- not-found-honesty == 1.0
- requirement-coverage >= 0.90

## Live conformance

The live conformance path is separate from the BM25 recorder. It invokes the
deployed Bedrock agent with trace enabled and scores a fixed gold-set subset
listed in [`tests/evals/live_conformance_subset.json`](../tests/evals/live_conformance_subset.json).

### What it records

- the live answer text
- Bedrock citations / retrieved references from the response trace
- reconstructed retrieved context from those references
- judge-backed faithfulness for positive questions

### What it scores

- groundedness
- citation-correctness
- faithfulness
- requirement-coverage
- not-found-honesty
- forged-answer guard

### Live pass bar

The live conformance summary passes only when:

- groundedness >= 0.95
- citation-correctness >= 0.95
- faithfulness >= 0.95
- requirement-coverage >= 0.90
- not-found-honesty == 1.0
- no forged positive result is detected

### Running it

The deployed agent must already exist and be reachable through the same
SSM/env agent-id resolution path as the runtime.

```bash
PYTHONPATH=src python -m tests.evals.harness.live_agent
```

That command writes `tests/evals/live_report.json`. Treat the report as a
launch artifact, not as a CI input.

## Running locally

```bash
# Offline gate (CI / merge contract)
PYTHONPATH=src python -m pytest tests/evals -m gate -q

# Re-record raw offline fixtures (opt-in)
EVALS_LIVE=1 PYTHONPATH=src python -m tests.evals.harness.recorder
PYTHONPATH=src python -m tests.evals.harness.report

# Post-deploy live conformance
PYTHONPATH=src python -m tests.evals.harness.live_agent
```

## Current truth

The offline gate is enforced in code and CI today. The live conformance path
exists in code and documentation, but the repo should still be described as
"verified in code and tests, not yet proven in production" until a hardened
deploy completes and the live report is captured.
