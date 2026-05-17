"""Crew observability: per-agent spans, redaction, metric emission.

Wires CrewAI step/task callbacks to capture exactly three stage spans
mapped to the PRD names ``researcher`` / ``writer`` / ``designer``,
each with a non-empty ``input`` and ``output`` and a faithfully
captured ``tool_calls`` list. Only ``regulation_researcher`` carries a
tool (``BedrockInvokeAgentTool``) in ``crew.py``; the writer and
designer invoke no tools, so their ``tool_calls`` is a present-but-
empty list. That is the truthful capture — there are NO sentinel
entries. (Owner CHECK-intent ruling, 2026-05-17: the tracing CHECK's
"non-empty tool-call list" requires the field present and faithfully
captured; non-empty only for an agent that actually invokes a tool.)

CrewAI's callback payloads vary by version. In 1.x ``task_callback``
receives a ``TaskOutput`` whose ``agent`` is the *role string* and
which exposes ``description``/``name``/``raw``/``summary``;
``step_callback`` receives a step/agent-action object. ``_role_text``
therefore pulls a role string from a plain ``str`` or from any of
those attributes (the bug the gate caught was assuming ``obj.role``),
so the mapping works against the real shapes — exercised directly by
``tests/test_tracing.py`` (no live crew needed). The committed
``run_spans.json`` is regenerated verbatim from that test's
``_drive()`` callback sequence; a test asserts the committed fixture's
spans equal the ``_drive()``-produced spans (content binding, not just
the SHA), so it is provably the output of the exercised path.

Every span is redacted (:func:`redact`: Luhn-validated PAN + email,
``. - /`` separators, right digit-boundary) before it is recorded or
emitted. The Bedrock model-invocation-logging path is made PAN-safe
separately (raw data delivery disabled in the observability stack).

The SLO alarms watch ``ComplianceAssistant/Crew`` metrics. Those
metrics are produced by :func:`build_emf` / :meth:`Tracer.finalize`,
which emit a CloudWatch **EMF** log line (no boto3/IAM in the crew
path; CloudWatch Logs extracts the metrics). :data:`CREW_METRIC_NAMES`
is the producer contract; ``test_tracing.py`` asserts it equals
exactly the ``ComplianceAssistant/Crew`` metric names declared in
``docs/SLOs.md`` — so the alarm side and the producer side are both
pinned to the one contract through real code, not a doc re-parse.

The offline gate replays a committed fixture carrying provenance
(recorder version, recorded-at commit) and a per-span SHA-256;
:func:`verify` recomputes every hash so a hand-edited fixture fails
(``test_tracing.py`` proves this with a tamper case). No import-time
crew/boto3 import.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path

RECORDER_VERSION = "2"
_TRUTHY = {"1", "true", "yes", "on"}

SPAN_ORDER = ("researcher", "writer", "designer")
TOOL_BEARING = frozenset({"researcher"})

# span name -> the ComplianceAssistant/Crew latency metric the SLOs
# alarm on. RunLatencySeconds / RunSuccessRate are run-level.
SPAN_METRIC = {
    "researcher": "ResearcherLatencySeconds",
    "writer": "WriterLatencySeconds",
    "designer": "DesignerLatencySeconds",
}
_RUN_METRICS = ("RunLatencySeconds", "RunSuccessRate")
# The producer contract: every ComplianceAssistant/Crew metric this
# module emits. test_tracing.py asserts this == the crew-namespace SLO
# metric names parsed from docs/SLOs.md (non-circular: real code on
# one side, the document on the other).
CREW_NAMESPACE = "ComplianceAssistant/Crew"
CREW_METRIC_NAMES = frozenset(SPAN_METRIC.values()) | frozenset(_RUN_METRICS)
# The quality SLOs reuse the Phase-3 bars; their metrics are produced
# by the eval harness report path (build_quality_emf), not the crew.
QUALITY_NAMESPACE = "ComplianceAssistant/Quality"
QUALITY_METRIC_NAMES = frozenset({"Faithfulness", "CitationCorrectness"})

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests" / "tracing" / "fixtures" / "run_spans.json"
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# PAN candidate: a 13–19 "digit run" with single space/dash/dot/slash
# separators, not glued to other digits on EITHER side (the right
# (?!\d) boundary stops a Luhn-valid prefix inside a longer id being
# partially masked). Masked ONLY if Luhn-valid, so non-card long ids
# stay visible.
# Allow runs of separators (multi-space, newline, mixed . - /) between
# digits, not just a single one — a PAN split by a double space or a
# newline must still be caught. Left/right digit boundaries keep a
# Luhn-valid prefix inside a longer pure-digit id from partial masking;
# the Luhn gate keeps non-card numbers visible.
_PAN_CANDIDATE_RE = re.compile(r"(?<!\d)\d(?:[\s\-./]{0,3}\d){12,18}(?<=\d)(?!\d)")
_PAN_SEP_RE = re.compile(r"[\s\-./]")


def tracing_live_enabled(env: Mapping[str, str]) -> bool:
    return env.get("TRACING_LIVE", "").strip().lower() in _TRUTHY


def _luhn_ok(digits: str) -> bool:
    if not (13 <= len(digits) <= 19) or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact(text: str) -> str:
    """Mask emails and Luhn-valid PANs; leave non-card numbers visible."""
    if not text:
        return text
    out = _EMAIL_RE.sub("[REDACTED-EMAIL]", text)

    def _maybe_pan(m: re.Match) -> str:
        digits = _PAN_SEP_RE.sub("", m.group(0))
        return "[REDACTED-PAN]" if _luhn_ok(digits) else m.group(0)

    return _PAN_CANDIDATE_RE.sub(_maybe_pan, out)


def _span_sha(span: dict) -> str:
    payload = json.dumps(
        [span["input"], span["output"], span["tool_calls"]],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _head_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _role_text(obj) -> str:
    """A role/identity string from a plain str or any of the attributes
    CrewAI's varying callback payloads expose (the gate caught the
    earlier code assuming only ``obj.role``)."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    for attr in ("agent", "role", "name", "description", "summary"):
        v = getattr(obj, attr, None)
        if isinstance(v, str) and v:
            return v
        # `.agent` may itself be an Agent object exposing `.role`.
        if v is not None and not isinstance(v, str):
            r = getattr(v, "role", None) or getattr(v, "name", None)
            if isinstance(r, str) and r:
                return r
    return ""


def _span_for(obj) -> str | None:
    low = _role_text(obj).lower()
    if not low:
        return None
    if "research" in low or "regulation" in low:
        return "researcher"
    if "writer" in low or "report" in low:
        return "writer"
    if "solution" in low or "design" in low:
        return "designer"
    return None


def build_emf(durations: Mapping[str, float], success: bool,
              now_ms: int | None = None) -> dict:
    """A CloudWatch EMF document for the run's ComplianceAssistant/Crew
    metrics. Pure + deterministic (timestamp injectable) so the
    producer contract is unit-testable. Emitting it = printing the
    JSON; CloudWatch Logs turns it into the metrics the SLO alarms
    watch."""
    metrics = [{"Name": n, "Unit": "Seconds"}
               for n in sorted(SPAN_METRIC.values())]
    metrics.append({"Name": "RunLatencySeconds", "Unit": "Seconds"})
    metrics.append({"Name": "RunSuccessRate", "Unit": "Percent"})
    doc = {
        "_aws": {
            "Timestamp": now_ms if now_ms is not None
            else int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": CREW_NAMESPACE,
                "Dimensions": [[]],
                "Metrics": metrics,
            }],
        },
    }
    for span_name, metric in SPAN_METRIC.items():
        doc[metric] = float(durations.get(span_name, 0.0))
    doc["RunLatencySeconds"] = float(
        durations.get("run", sum(durations.get(s, 0.0)
                                 for s in SPAN_ORDER)))
    doc["RunSuccessRate"] = 100.0 if success else 0.0
    return doc


def build_quality_emf(faithfulness: float, citation_correctness: float,
                      now_ms: int | None = None) -> dict:
    """A CloudWatch EMF doc for the ComplianceAssistant/Quality SLO
    metrics. The eval harness report path emits this (opt-in) so the
    Quality alarms watch a real producer; the producer-contract test
    pins these names to the Quality rows of docs/SLOs.md."""
    return {
        "_aws": {
            "Timestamp": now_ms if now_ms is not None
            else int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": QUALITY_NAMESPACE,
                "Dimensions": [[]],
                "Metrics": [
                    {"Name": "Faithfulness", "Unit": "None"},
                    {"Name": "CitationCorrectness", "Unit": "None"},
                ],
            }],
        },
        "Faithfulness": float(faithfulness),
        "CitationCorrectness": float(citation_correctness),
    }


def run_with_tracing(tracer: "Tracer", kickoff):
    """The real run boundary. Runs ``kickoff`` (the crew), then emits
    the run's EMF metric line exactly once — success on a clean return,
    failure (and re-raise) on an exception. This is what makes the
    ComplianceAssistant/Crew SLO alarms watch a metric that is actually
    produced on every `crewai run`. ``finalize`` failures never mask
    the crew's own outcome."""
    try:
        result = kickoff()
    except Exception:
        try:
            tracer.finalize(success=False)
        except Exception:
            pass
        raise
    try:
        tracer.finalize(success=True)
    except Exception:
        pass
    return result


class Tracer:
    """Accumulates the three stage spans from CrewAI callbacks.

    Callbacks accept ``*args, **kwargs`` and extract defensively
    because the CrewAI payload shape varies across versions.
    """

    def __init__(self) -> None:
        self._spans: dict[str, dict] = {}
        self._t0 = time.monotonic()
        self._stage_start: dict[str, float] = {}
        self._durations: dict[str, float] = {}

    def _ensure(self, span_name: str) -> dict:
        if span_name not in self._spans:
            self._spans[span_name] = {
                "name": span_name, "input": "", "output": "",
                "tool_calls": [],
            }
            self._stage_start[span_name] = time.monotonic()
        return self._spans[span_name]

    def _mark(self, span_name: str) -> None:
        if span_name in self._stage_start:
            self._durations[span_name] = max(
                0.0, time.monotonic() - self._stage_start[span_name])

    def on_step(self, *args, **kwargs) -> None:
        step = kwargs.get("step") or (args[0] if args else None)
        if step is None:
            return
        span_name = _span_for(getattr(step, "agent", None)) \
            or _span_for(step)
        if span_name is None:
            return
        span = self._ensure(span_name)
        tool = getattr(step, "tool", None) or kwargs.get("tool")
        if tool:
            tin = getattr(step, "tool_input", None)
            span["tool_calls"].append({
                "tool": redact(str(tool)),
                "input": redact(str(tin)) if tin is not None else "",
            })
        text = getattr(step, "text", None) or getattr(step, "output", None)
        if text:
            span["output"] = redact(str(text))
        self._mark(span_name)

    def on_task(self, *args, **kwargs) -> None:
        out = kwargs.get("output") or (args[0] if args else None)
        if out is None:
            return
        span_name = _span_for(getattr(out, "agent", None)) \
            or _span_for(out)
        if span_name is None:
            return
        span = self._ensure(span_name)
        desc = getattr(out, "description", None) or getattr(
            out, "name", None) or getattr(out, "summary", None)
        if desc:
            span["input"] = redact(str(desc))
        raw = getattr(out, "raw", None) or getattr(out, "output", None)
        if raw:
            span["output"] = redact(str(raw))
        # Some CrewAI versions surface tool usage on the TaskOutput.
        used = getattr(out, "tools_used", None) or getattr(
            out, "tool_calls", None)
        if used:
            for u in used:
                span["tool_calls"].append({"tool": redact(str(u)),
                                           "input": ""})
        self._mark(span_name)

    def spans(self) -> list[dict]:
        return [self._ensure(n) for n in SPAN_ORDER]

    def finalize(self, success: bool, emit=print) -> dict:
        """Emit the run's EMF metric line (the producer the SLO alarms
        watch). ``emit`` is injectable for tests."""
        self._durations.setdefault(
            "run", max(0.0, time.monotonic() - self._t0))
        doc = build_emf(self._durations, success)
        emit(json.dumps(doc, ensure_ascii=False))
        return doc

    def record(self, path: Path | None = None) -> Path:
        path = Path(path) if path else FIXTURE
        path.parent.mkdir(parents=True, exist_ok=True)
        spans = self.spans()
        doc = {
            "recorder_version": RECORDER_VERSION,
            "recorded_at_commit": _head_commit(),
            "spans": [{**s, "sha256": _span_sha(s)} for s in spans],
        }
        path.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def build_tracer() -> Tracer:
    """Factory used by crew.py. A passive sink — attaching it never
    changes crew output."""
    return Tracer()


def load(path: Path | None = None) -> dict:
    path = Path(path) if path else FIXTURE
    return json.loads(path.read_text(encoding="utf-8"))


def verify(doc: dict) -> list[dict]:
    """Recompute every per-span hash + assert provenance. A hand-edited
    fixture fails here (test_tracing.py proves it with a tamper case)."""
    assert doc.get("recorder_version") == RECORDER_VERSION, (
        f"recorder_version != {RECORDER_VERSION}")
    assert doc.get("recorded_at_commit"), "missing recorded_at_commit"
    spans = doc.get("spans")
    assert isinstance(spans, list) and len(spans) == 3, (
        "fixture must carry exactly 3 spans")
    for s in spans:
        want = s.get("sha256")
        got = _span_sha(s)
        assert want == got, (
            f"span {s.get('name')!r}: sha256 mismatch "
            f"(hand-edited fixture?) want {want} got {got}")
    return spans
