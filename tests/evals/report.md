# RAG Evaluation Report

- k = 5
- selection rule: max context-recall@k subject to faithfulness >= 0.95 over deploy-equivalent FIXED_SIZE configs; tie-break MRR, precision, then config_key

| config | deploy-equiv | recall | precision | MRR | faithfulness | hallucination | citation | not-found | req-cov |
|---|---|---|---|---|---|---|---|---|---|
| FIXED_SIZE-512-20 | True | 1.000 | 0.960 | 0.972 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| FIXED_SIZE-256-15 | True | 1.000 | 0.893 | 0.905 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| HIERARCHICAL-250-20 | False | 1.000 | 0.911 | 0.935 | — | — | — | — | — |

**Winner (deployable):** `{'chunkingStrategy': 'FIXED_SIZE', 'chunkMaxTokens': 512, 'chunkOverlapPercent': 20}`

_HIERARCHICAL is advisory/non-deployable: infra/stacks/kb_stack.py emits only fixed-size chunking._
