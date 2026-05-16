"""Turn a Bedrock agent trace into a Sources section for the report.

`analysis/a.md` flagged that the generated report had zero citations.
With agent trace enabled, the InvokeAgent response carries the source
passages it grounded each answer on; this renders them into a stable,
de-duplicated Markdown block appended to the report.

render_citations is pure and never raises: a missing or malformed
trace must not break a run, and its output must be deterministic so
the later RAG-eval sub-project can assert on it (no timestamps, no
set-iteration ordering).
"""
from typing import Any

_NO_SOURCES = "## Sources\n\n_No grounded sources returned._"


def _iter_references(trace: Any):
    """Yield (location, snippet) from whatever shape the trace has."""
    if not isinstance(trace, dict):
        return
    for citation in trace.get("citations", []) or []:
        if not isinstance(citation, dict):
            continue
        for ref in citation.get("retrievedReferences", []) or []:
            if not isinstance(ref, dict):
                continue
            loc = ref.get("location", {}) or {}
            s3 = (loc.get("s3Location") or {}).get("uri")
            uri = s3 or loc.get("type") or "unknown source"
            snippet = ((ref.get("content") or {}).get("text") or "").strip()
            snippet = " ".join(snippet.split())
            if len(snippet) > 200:
                snippet = snippet[:197] + "..."
            yield uri, snippet


def render_citations(trace: Any) -> str:
    """A deterministic '## Sources' Markdown block. Never raises."""
    try:
        seen = []
        for uri, snippet in _iter_references(trace):
            entry = (uri, snippet)
            if entry not in seen:
                seen.append(entry)
        if not seen:
            return _NO_SOURCES
        # Sort for determinism (input order must not matter).
        seen.sort()
        lines = ["## Sources", ""]
        for i, (uri, snippet) in enumerate(seen, 1):
            lines.append(f"{i}. `{uri}`" + (f" — {snippet}" if snippet else ""))
        return "\n".join(lines)
    except Exception:
        return _NO_SOURCES


def append_sources(report_path: str, trace: Any) -> None:
    """Append the rendered Sources block to a report file. Best-effort."""
    try:
        block = render_citations(trace)
        with open(report_path, "a", encoding="utf-8") as fh:
            fh.write("\n\n" + block + "\n")
    except OSError:
        # A missing report file (e.g. a skipped conditional task) is
        # not an error worth failing the run over.
        pass
