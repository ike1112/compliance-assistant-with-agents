"""Opt-in live re-recording. Skipped unless EVALS_LIVE=1 so the gate
never spends model budget. This is the ONLY path that (re)writes raw
fixtures; the gate replays + recomputes them.
"""
import os

import pytest

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("EVALS_LIVE") != "1",
    reason="live recording is opt-in (set EVALS_LIVE=1)",
)
def test_record_refreshes_fixtures():
    from tests.evals.harness import recorder
    # Resumable: only writes fixtures that do not already exist.
    written = recorder.record()
    assert written >= 0
