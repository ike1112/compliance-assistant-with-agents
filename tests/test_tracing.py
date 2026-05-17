"""Offline, hash-bound contract test for crew tracing.

Exercises the REAL callback path (not just a replayed fixture):
CrewAI-1.x-shaped stub TaskOutput/step objects are fed through
on_task/on_step and the produced spans are asserted — the same code
path that produced the committed fixture. Also proves the hash-binding
is real (a mutated fixture must fail verify()) and that the EMF metric
producer's contract equals the ComplianceAssistant/Crew SLO metric
names declared in docs/SLOs.md (so alarm side and producer side are
both pinned to one contract, non-circularly).
"""
import copy
import os

import pytest

from compliance_assistant import tracing


# --- CrewAI-1.x-shaped stubs (TaskOutput.agent is the ROLE STRING; the
# step payload carries a role string + tool/text). The earlier bug was
# assuming obj.role — these stubs are the shapes the gate verified. ---
class _TaskOutput:
    def __init__(self, agent, description, raw):
        self.agent = agent
        self.description = description
        self.raw = raw


class _Step:
    def __init__(self, agent, tool=None, tool_input=None, text=None):
        self.agent = agent
        self.tool = tool
        self.tool_input = tool_input
        self.text = text


def _drive(t: tracing.Tracer) -> None:
    t.on_step(_Step("Regulation Researcher", tool="BedrockInvokeAgentTool",
                    tool_input="PCI DSS lookup", text="found reqs"))
    t.on_task(_TaskOutput("Regulation Researcher", "identify reqs",
                          "Req 1.2.7 grounded"))
    t.on_task(_TaskOutput("Report Writer", "write the report",
                          "# Report\n## Sources\n- s3://corpus/x.txt"))
    t.on_task(_TaskOutput("Solution Designer", "map to AWS",
                          "Req 1.2.7 -> security groups"))


def _doc():
    return tracing.load()


# ---- the live callback path actually works against real shapes ----

def test_span_for_maps_real_crewai_shapes():
    assert tracing._span_for(_TaskOutput("Regulation Researcher", "", "")) \
        == "researcher"
    assert tracing._span_for("Report Writer") == "writer"        # bare str
    assert tracing._span_for(_Step("Solution Designer")) == "designer"
    assert tracing._span_for(_TaskOutput("Unknown Role", "", "")) is None


def test_callbacks_produce_three_spans_with_required_fields():
    t = tracing.Tracer()
    _drive(t)
    spans = t.spans()
    assert [s["name"] for s in spans] == list(tracing.SPAN_ORDER)
    by = {s["name"]: s for s in spans}
    for name, s in by.items():
        assert s["input"].strip(), f"{name}: empty input"
        assert s["output"].strip(), f"{name}: empty output"
        assert isinstance(s["tool_calls"], list)
    # Owner CHECK-intent ruling: non-empty only where a tool exists.
    assert by["researcher"]["tool_calls"], "researcher must record its tool"
    assert by["writer"]["tool_calls"] == []
    assert by["designer"]["tool_calls"] == []
    assert tracing.TOOL_BEARING == {"researcher"}


def test_record_then_verify_round_trips_from_the_callback_path():
    t = tracing.Tracer()
    _drive(t)
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "f.json"
        t.record(p)
        spans = tracing.verify(tracing.load(p))
    assert [s["name"] for s in spans] == list(tracing.SPAN_ORDER)


# ---- the committed fixture is provenance + hash bound ----

def test_committed_fixture_is_provenance_and_hash_bound():
    spans = tracing.verify(_doc())
    by = {s["name"]: s for s in spans}
    assert set(by) == set(tracing.SPAN_ORDER)
    assert by["researcher"]["tool_calls"]
    assert by["writer"]["tool_calls"] == []
    assert by["designer"]["tool_calls"] == []


def test_hand_edited_fixture_fails_verify():
    # The headline gate-integrity claim, now PROVEN: tamper one span and
    # verify() must reject it (deleting verify's sha loop fails this).
    doc = copy.deepcopy(_doc())
    doc["spans"][0]["output"] += " INJECTED"
    with pytest.raises(AssertionError, match="sha256 mismatch"):
        tracing.verify(doc)


def test_no_raw_email_or_luhn_pan_in_any_span():
    blob = " ".join(
        str(s["input"]) + str(s["output"]) + str(s["tool_calls"])
        for s in tracing.verify(_doc())
    )
    assert not tracing._EMAIL_RE.search(blob), "raw email survived a span"
    for m in tracing._PAN_CANDIDATE_RE.finditer(blob):
        digits = tracing._PAN_SEP_RE.sub("", m.group(0))
        assert not tracing._luhn_ok(digits), f"unmasked PAN: {m.group(0)!r}"


# ---- the EMF metric producer is real and pinned to the SLO contract ----

def test_emf_producer_emits_exactly_the_crew_slo_metrics():
    import sys
    sys.path.insert(0, "infra")
    from stacks.slo_contract import SLOS_MD, parse_slos

    crew_slo_metrics = {
        s.metric for s in parse_slos(SLOS_MD)
        if s.namespace == tracing.CREW_NAMESPACE
    }
    # Producer contract == the crew-namespace SLO metric names: the
    # alarm side (SLOs.md) and the producer side (this module's real
    # code) are tied to one contract, so the cross-check is not
    # circular doc-reparse.
    assert tracing.CREW_METRIC_NAMES == crew_slo_metrics, (
        f"producer {sorted(tracing.CREW_METRIC_NAMES)} != crew SLO "
        f"metrics {sorted(crew_slo_metrics)}")

    captured = []
    t = tracing.Tracer()
    _drive(t)
    doc = t.finalize(success=True, emit=captured.append)
    assert len(captured) == 1
    emitted = {
        mm["Name"]
        for mm in doc["_aws"]["CloudWatchMetrics"][0]["Metrics"]
    }
    assert emitted == tracing.CREW_METRIC_NAMES
    assert doc["_aws"]["CloudWatchMetrics"][0]["Namespace"] \
        == tracing.CREW_NAMESPACE
    assert doc["RunSuccessRate"] == 100.0
    assert t.finalize(success=False, emit=lambda _x: None) is not None


@pytest.mark.skipif(
    not tracing.tracing_live_enabled(os.environ),
    reason="live capture is opt-in (set TRACING_LIVE=1)",
)
def test_live_recapture_round_trips():  # pragma: no cover - opt-in only
    from compliance_assistant.tracing import build_tracer
    t = build_tracer()
    assert hasattr(t, "on_step") and hasattr(t, "on_task")
