"""Flip exactly one phase row to `complete` and append one Progress-Log
line with panel evidence. This is the only place a phase is marked done;
prp-ralph never edits the Status column.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path


class PrdError(Exception):
    """Phase row not found, or already complete (no silent re-flip)."""


def _row_re(phase: str) -> re.Pattern:
    # | <phase> | ... | <status> | ... |  -- capture the 3rd cell (Status)
    return re.compile(
        rf"^(\|\s*{re.escape(phase)}\s*\|[^|]*\|[^|]*\|\s*)"
        rf"(pending|in-progress|complete)(\s*\|.*)$",
        re.MULTILINE,
    )


def flip_phase_complete(prd_path: Path, phase: str, evidence: dict) -> None:
    prd_path = Path(prd_path)
    text = prd_path.read_text(encoding="utf-8")

    m = _row_re(phase).search(text)
    if m is None:
        raise PrdError(f"no phase row '{phase}' in {prd_path}")
    if m.group(2) == "complete":
        raise PrdError(f"phase {phase} already complete; refusing re-flip")

    text = text[:m.start()] + m.group(1) + "complete" + m.group(3) + text[m.end():]

    ev = " ".join(f"{k}={v}" for k, v in sorted(evidence.items()))
    line = f"- {date.today().isoformat()} — phase {phase} -> complete via " \
           f"quality gate ({ev})."

    # Anchor on the real heading LINE (not any prose mention of the words)
    # and insert right after it, tolerating an optional following blank line.
    hm = re.search(r"^##\s+Progress Log[^\n]*$", text, re.MULTILINE)
    if hm is None:
        raise PrdError("no '## Progress Log' heading in PRD")
    after_heading = text.index("\n", hm.end()) + 1
    insert_at = (text.index("\n", after_heading) + 1
                 if text[after_heading:after_heading + 1] == "\n"
                 else after_heading)
    text = text[:insert_at] + line + "\n" + text[insert_at:]

    prd_path.write_text(text, encoding="utf-8")
