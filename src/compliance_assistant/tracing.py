"""Crew observability: per-agent spans, redaction, provenance fixtures.

Wires CrewAI step/task callbacks to capture exactly three stage spans
mapped to the PRD names ``researcher`` / ``writer`` / ``designer``,
each with a non-empty ``input`` and ``output`` and a faithfully
captured ``tool_calls`` list. Only ``regulation_researcher`` carries a
tool (``BedrockInvokeAgentTool``) in ``crew.py``; ``report_writer`` and
``solution_designer`` invoke no tools, so their ``tool_calls`` is a
present-but-empty list. That is the truthful capture — there are NO
sentinel entries. (Owner CHECK-intent ruling, 2026-05-17: the tracing
CHECK's "non-empty tool-call list" requires the field to be present and
faithfully captured; non-empty is required only for an agent that
actually invokes a tool.)

Every span is passed through :func:`redact` before it is recorded or
emitted, so a PAN or email never reaches the in-process trace sink. The
Bedrock model-invocation-logging path is made PAN-safe separately, in
``infra/stacks/observability_stack.py``, by disabling raw text/image/
embedding/video data delivery (metadata only).

The offline gate replays a committed fixture that the live recorder
(``TRACING_LIVE=1``) produced; the fixture carries provenance
(recorder version, recorded-at commit) and a per-span SHA-256, and
:func:`verify` recomputes every hash, so a hand-edited fixture fails —
the same hash-binding discipline the Phase-3 eval harness uses. No
import-time crew/boto3 import (keeps offline test collection clean).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

RECORDER_VERSION = "1"
_TRUTHY = {"1", "true", "yes", "on"}

# crew.py @agent/@task method names → the PRD CHECK span names. The
# crew runs the three stages in this order.
_SPAN_NAME = {
    "regulation_researcher": "researcher",
    "report_writer": "writer",
    "solution_designer": "designer",
}
SPAN_ORDER = ("researcher", "writer", "designer")
# The only stage that invokes a tool (crew.py: only the researcher has
# BedrockInvokeAgentTool). Used solely to document/validate intent —
# the tracer records whatever tool calls actually occurred, never a
# placeholder.
TOOL_BEARING = frozenset({"researcher"})

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests" / "tracing" / "fixtures" / "run_spans.json"
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A PAN candidate: a 13–19 "digit run" allowing single space/dash
# separators, not glued to other digits. It is masked ONLY if the
# digits pass the Luhn check — so long non-card identifiers (request
# ids, account-like numbers that are not Luhn-valid) stay visible and
# observability is not destroyed.
_PAN_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?<=\d)")


def tracing_live_enabled(env: Mapping[str, str]) -> bool:
    """True only when an opt-in live capture is requested (default OFF)."""
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
        digits = re.sub(r"[ -]", "", m.group(0))
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


class Tracer:
    """Accumulates the three stage spans from CrewAI callbacks.

    Callbacks accept ``*args, **kwargs`` and extract defensively because
    the CrewAI callback payload shape varies across versions; the gate's
    source of truth is the recorded fixture, the live path is opt-in.
    """

    def __init__(self) -> None:
        self._spans: dict[str, dict] = {}

    def _ensure(self, span_name: str) -> dict:
        return self._spans.setdefault(
            span_name,
            {"name": span_name, "input": "", "output": "", "tool_calls": []},
        )

    @staticmethod
    def _span_for(obj) -> str | None:
        # Map a CrewAI agent/task object to a PRD span name by the
        # agent role / task config the crew defines.
        role = ""
        for attr in ("role", "name"):
            role = role or str(getattr(obj, attr, "") or "")
        agent = getattr(obj, "agent", None)
        if agent is not None:
            role = role or str(getattr(agent, "role", "") or "")
        low = role.lower()
        if "research" in low or "regulation" in low:
            return "researcher"
        if "writer" in low or "report" in low:
            return "writer"
        if "solution" in low or "designer" in low or "design" in low:
            return "designer"
        return None

    def on_step(self, *args, **kwargs) -> None:
        step = kwargs.get("step") or (args[0] if args else None)
        if step is None:
            return
        span_name = self._span_for(getattr(step, "agent", step))
        if span_name is None:
            return
        span = self._ensure(span_name)
        tool = getattr(step, "tool", None) or kwargs.get("tool")
        if tool:
            tin = getattr(step, "tool_input", None)
            span["tool_calls"].append(
                {"tool": redact(str(tool)),
                 "input": redact(str(tin)) if tin is not None else ""}
            )
        text = getattr(step, "text", None) or getattr(step, "output", None)
        if text:
            span["output"] = redact(str(text))

    def on_task(self, *args, **kwargs) -> None:
        out = kwargs.get("output") or (args[0] if args else None)
        if out is None:
            return
        span_name = self._span_for(out)
        if span_name is None:
            return
        span = self._ensure(span_name)
        desc = getattr(out, "description", None) or getattr(
            out, "summary", None)
        if desc:
            span["input"] = redact(str(desc))
        raw = getattr(out, "raw", None) or getattr(out, "output", None)
        if raw:
            span["output"] = redact(str(raw))

    def spans(self) -> list[dict]:
        """The three spans in stage order (missing ones materialised
        empty so the shape is always exactly three)."""
        return [self._ensure(n) for n in SPAN_ORDER]

    def record(self, path: Path | None = None) -> Path:
        """Live writer: stamp provenance + per-span sha256. Live only —
        the offline gate never calls this."""
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
    """Recompute every per-span hash and assert provenance. A
    hand-edited fixture fails here (hash-binding, like the Phase-3
    eval harness). Returns the spans on success."""
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
