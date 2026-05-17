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


def test_committed_fixture_is_the_drive_paths_output():
    # Content binding (not just SHA): the committed run_spans.json must
    # equal what the exercised _drive() callback path produces.
    import pathlib
    import tempfile
    t = tracing.Tracer()
    _drive(t)
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "f.json"
        t.record(p)
        fresh = {s["name"]: s for s in tracing.load(p)["spans"]}
    committed = {s["name"]: s for s in _doc()["spans"]}
    assert set(fresh) == set(committed) == set(tracing.SPAN_ORDER)
    for n in tracing.SPAN_ORDER:
        for field in ("input", "output", "tool_calls"):
            assert fresh[n][field] == committed[n][field], (
                f"committed fixture {n}.{field} != _drive() output "
                f"(fixture not produced by the exercised path)")


class _FakeTracer:
    def __init__(self):
        self.calls = []

    def finalize(self, success):
        self.calls.append(success)


def test_run_with_tracing_finalizes_once_on_success_and_failure():
    f = _FakeTracer()
    assert tracing.run_with_tracing(f, lambda: "result") == "result"
    assert f.calls == [True], "finalize(success=True) once on clean return"

    f2 = _FakeTracer()

    def _boom():
        raise RuntimeError("crew exploded")

    with pytest.raises(RuntimeError, match="crew exploded"):
        tracing.run_with_tracing(f2, _boom)
    assert f2.calls == [False], "finalize(success=False) once, then re-raise"

    # A finalize() that itself raises must never mask the crew outcome.
    class _BadTracer:
        def finalize(self, success):
            raise ValueError("metric sink down")

    assert tracing.run_with_tracing(_BadTracer(), lambda: 7) == 7
    with pytest.raises(RuntimeError, match="orig"):
        tracing.run_with_tracing(
            _BadTracer(), lambda: (_ for _ in ()).throw(RuntimeError("orig")))


def test_main_run_wires_the_tracer_to_the_run_boundary():
    # The wiring contract without importing crewai: main.run builds a
    # ComplianceAssistant, calls ca.crew(), and routes kickoff through
    # run_with_tracing(ca._tracer, ...). Assert the source encodes that.
    import pathlib
    src = pathlib.Path("src/compliance_assistant/main.py").read_text()
    assert "run_with_tracing(ca._tracer" in src
    assert src.count("run_with_tracing(ca._tracer") >= 4  # run/train/replay/test
    crew_src = pathlib.Path("src/compliance_assistant/crew.py").read_text()
    assert "self._tracer = build_tracer()" in crew_src
    assert "step_callback=self._tracer.on_step" in crew_src


def test_quality_producer_contract_matches_slo_doc():
    import sys
    sys.path.insert(0, "infra")
    from stacks.slo_contract import SLOS_MD, parse_slos

    quality_slo_metrics = {
        s.metric for s in parse_slos(SLOS_MD)
        if s.namespace == tracing.QUALITY_NAMESPACE
    }
    assert tracing.QUALITY_METRIC_NAMES == quality_slo_metrics, (
        f"quality producer {sorted(tracing.QUALITY_METRIC_NAMES)} != "
        f"quality SLO metrics {sorted(quality_slo_metrics)}")
    doc = tracing.build_quality_emf(0.97, 0.96)
    names = {m["Name"] for m in doc["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    assert names == tracing.QUALITY_METRIC_NAMES
    assert doc["_aws"]["CloudWatchMetrics"][0]["Namespace"] \
        == tracing.QUALITY_NAMESPACE
    assert doc["Faithfulness"] == 0.97 and doc["CitationCorrectness"] == 0.96


def test_eval_harness_emits_quality_metrics_only_when_opted_in():
    import sys
    sys.path.insert(0, "tests")
    from evals.harness import report as R

    rep = {"configs": [{"deploy_equivalent": True, "generation": {
        "faithfulness": 0.99, "citation_correctness": 0.98}}]}
    assert R.emit_quality_metrics(rep, env={}) is None  # default OFF
    doc = R.emit_quality_metrics(rep, env={"EVALS_EMIT_METRICS": "1"})
    assert doc is not None
    assert doc["Faithfulness"] == 0.99 and doc["CitationCorrectness"] == 0.98


def test_redact_empty_and_luhn_edge_branches():
    assert tracing.redact("") == ""               # empty early return
    assert tracing._luhn_ok("123") is False        # too short
    assert tracing._luhn_ok("12a4567890123") is False  # non-digit
    assert tracing._luhn_ok("4111111111111111") is True


def test_role_text_and_span_for_edge_branches():
    assert tracing._role_text(None) == ""
    assert tracing._role_text(object()) == ""      # no usable attrs
    assert tracing._span_for(object()) is None

    class _AgentObj:
        role = "Regulation Researcher"

    class _Wrapper:
        agent = _AgentObj()                        # .agent is an object

    assert tracing._role_text(_Wrapper()) == "Regulation Researcher"
    assert tracing._span_for(_Wrapper()) == "researcher"


def test_callback_early_returns_are_safe_noops():
    t = tracing.Tracer()
    t.on_step()                                    # step is None -> return
    t.on_step(_Step("nobody-role"))                # unmappable -> return
    t.on_task()                                    # out is None -> return
    t.on_task(_TaskOutput("nobody-role", "d", "r"))  # unmappable -> return
    # No span was created by any of the above no-ops.
    assert t._spans == {}


def test_on_task_captures_tools_used_when_present():
    class _TO:
        agent = "Regulation Researcher"
        description = "d"
        raw = "r"
        tools_used = ["BedrockInvokeAgentTool", "Other"]

    t = tracing.Tracer()
    t.on_task(_TO())
    tc = t.spans()[0]["tool_calls"]
    assert [c["tool"] for c in tc] == ["BedrockInvokeAgentTool", "Other"]


def test_head_commit_falls_back_to_unknown(monkeypatch):
    def _raise(*_a, **_k):
        raise OSError("no git here")

    monkeypatch.setattr(tracing.subprocess, "run", _raise)
    assert tracing._head_commit() == "unknown"


def test_build_tracer_returns_a_tracer():
    assert isinstance(tracing.build_tracer(), tracing.Tracer)


@pytest.mark.skipif(
    not tracing.tracing_live_enabled(os.environ),
    reason="live capture is opt-in (set TRACING_LIVE=1)",
)
def test_live_recapture_round_trips():  # pragma: no cover - opt-in only
    from compliance_assistant.tracing import build_tracer
    t = build_tracer()
    assert hasattr(t, "on_step") and hasattr(t, "on_task")
