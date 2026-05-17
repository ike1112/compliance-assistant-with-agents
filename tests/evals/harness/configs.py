"""Single source of truth for the chunking configs the harness uses, so
the recorder (which writes fixtures) and the report (which scores them)
cannot drift. Deploy-equivalent configs are FIXED_SIZE (the only
strategy infra/stacks/kb_stack.py emits); HIERARCHICAL is advisory and
non-deployable.
"""
from __future__ import annotations

# (strategy, max_tokens, overlap_pct) — fixtures are recorded for every
# deploy-equivalent config; the report selects the winner over these.
DEPLOY_CONFIGS: list[tuple[str, int, int]] = [
    ("FIXED_SIZE", 512, 20),
    ("FIXED_SIZE", 256, 15),
]

# Scored for comparison only; never written to infra/cdk.json.
ADVISORY_CONFIGS: list[tuple[str, int, int]] = [
    ("HIERARCHICAL", 250, 20),
]

SCORED_CONFIGS: list[tuple[str, int, int]] = DEPLOY_CONFIGS + ADVISORY_CONFIGS
