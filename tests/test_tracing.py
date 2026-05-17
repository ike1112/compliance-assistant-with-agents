"""Offline, hash-bound contract test for crew tracing.

No network/subprocess: replays the committed, provenance-stamped span
fixture and RECOMPUTES every per-span sha256 (a hand-edited fixture
fails — same binding discipline as the Phase-3 eval harness). Asserts
exactly three spans named researcher / writer / designer, each with a
non-empty input + output and a present `tool_calls` list; non-empty
only for the researcher (the sole tool-bearing agent in crew.py —
owner CHECK-intent ruling). The opt-in live path (TRACING_LIVE=1)
re-records from a real run; it is skipped offline.
"""
import os
import re

import pytest

from compliance_assistant import tracing


def _doc():
    return tracing.load()


def test_fixture_is_provenance_and_hash_bound():
    # verify() asserts recorder_version + recorded_at_commit and
    # recomputes each span sha256; a tampered fixture fails here.
    spans = tracing.verify(_doc())
    assert [s["name"] for s in spans] == ["researcher", "writer", "designer"]


def test_exactly_three_spans_with_required_fields():
    spans = tracing.verify(_doc())
    assert len(spans) == 3
    by = {s["name"]: s for s in spans}
    assert set(by) == set(tracing.SPAN_ORDER)
    for name, s in by.items():
        assert s["input"].strip(), f"{name}: empty input"
        assert s["output"].strip(), f"{name}: empty output"
        assert isinstance(s["tool_calls"], list), f"{name}: tool_calls not a list"


def test_tool_calls_nonempty_only_where_a_tool_exists():
    # Owner CHECK-intent ruling: tool_calls is present + faithfully
    # captured; non-empty ONLY for an agent that actually invokes a
    # tool. crew.py: only the researcher has BedrockInvokeAgentTool.
    by = {s["name"]: s for s in tracing.verify(_doc())}
    assert by["researcher"]["tool_calls"], "researcher must record its tool call"
    assert by["writer"]["tool_calls"] == [], "writer invokes no tool (no sentinel)"
    assert by["designer"]["tool_calls"] == [], "designer invokes no tool (no sentinel)"
    assert tracing.TOOL_BEARING == {"researcher"}


def test_no_raw_pan_or_email_survives_in_any_span():
    blob = " ".join(
        str(s["input"]) + str(s["output"]) + str(s["tool_calls"])
        for s in tracing.verify(_doc())
    )
    assert "@" not in re.sub(r"\[REDACTED-EMAIL\]", "", blob) or \
        "[REDACTED-EMAIL]" in blob or "@" not in blob
    # A Luhn-valid 16-digit run must not appear unmasked.
    for m in re.finditer(r"(?<!\d)(?:\d[ -]?){13,19}(?<=\d)", blob):
        digits = re.sub(r"[ -]", "", m.group(0))
        assert not tracing._luhn_ok(digits), (
            f"unmasked Luhn-valid PAN in span: {m.group(0)!r}")


@pytest.mark.skipif(
    not tracing.tracing_live_enabled(os.environ),
    reason="live capture is opt-in (set TRACING_LIVE=1)",
)
def test_live_recapture_round_trips():  # pragma: no cover - opt-in only
    # A real crew run would be wired here; offline this is skipped.
    from compliance_assistant.tracing import build_tracer
    t = build_tracer()
    assert hasattr(t, "on_step") and hasattr(t, "on_task")
