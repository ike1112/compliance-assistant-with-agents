"""Corpus chunking strategies.

Only FIXED_SIZE is *deploy-equivalent*: infra/stacks/kb_stack.py reads
only chunkingStrategy/chunkMaxTokens/chunkOverlapPercent and always emits
a Bedrock fixed_size_chunking_configuration. HIERARCHICAL is computed for
comparison only and is honestly flagged non-deployable; it must never be
written into infra/cdk.json.

Token proxy = whitespace-delimited words (documented; no tokenizer dep).
All output is deterministic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# strategy -> deploy-equivalent (writable into infra/cdk.json)
STRATEGIES: dict[str, bool] = {
    "FIXED_SIZE": True,
    "HIERARCHICAL": False,
}

# A corpus section header: a short title-case line, no terminal period,
# not one of the "PCI DSS v4.0 Requirement N.N ..." sentences (those
# contain '.' and lowercase) and not the "Requirement N: Title" doc
# title (contains ':').
_HEADER_RE = re.compile(r"^[A-Z][A-Za-z0-9 ,/&-]{2,68}$")


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: str
    text: str


def _words(text: str) -> list[str]:
    return text.split()


def _fixed_size(doc_id: str, text: str, max_tokens: int,
                overlap_pct: int) -> list[Chunk]:
    words = _words(text)
    if not words:
        return []
    step = max(1, max_tokens - (max_tokens * overlap_pct) // 100)
    chunks: list[Chunk] = []
    i = 0
    idx = 0
    n = len(words)
    while i < n:
        window = words[i:i + max_tokens]
        chunks.append(
            Chunk(doc_id, f"{doc_id}#fs-{max_tokens}-{overlap_pct}-{idx:04d}",
                  " ".join(window)))
        idx += 1
        if i + max_tokens >= n:
            break
        i += step
    return chunks


def _sections(text: str) -> list[str]:
    """Split a doc into header-led sections by its own structure."""
    lines = text.split("\n")
    sections: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        is_header = (
            bool(_HEADER_RE.match(stripped))
            and not stripped.startswith("PCI DSS")
        )
        if is_header and current:
            sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)
    return ["\n".join(s).strip() for s in sections if "\n".join(s).strip()]


def _hierarchical(doc_id: str, text: str, max_tokens: int,
                  overlap_pct: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    idx = 0
    for sec in _sections(text):
        sec_words = _words(sec)
        if len(sec_words) <= max_tokens:
            chunks.append(Chunk(doc_id, f"{doc_id}#h-{idx:04d}", sec))
            idx += 1
            continue
        # Oversized section: sub-split by the fixed rule, stable ids.
        for sub in _fixed_size(doc_id, sec, max_tokens, overlap_pct):
            chunks.append(
                Chunk(doc_id, f"{doc_id}#h-{idx:04d}", sub.text))
            idx += 1
    return chunks


def chunk(doc_id: str, text: str, strategy: str, max_tokens: int,
          overlap_pct: int) -> list[Chunk]:
    if strategy == "FIXED_SIZE":
        return _fixed_size(doc_id, text, max_tokens, overlap_pct)
    if strategy == "HIERARCHICAL":
        return _hierarchical(doc_id, text, max_tokens, overlap_pct)
    raise ValueError(f"unknown chunking strategy {strategy!r}")


def chunk_corpus(corpus: dict[str, str], strategy: str, max_tokens: int,
                 overlap_pct: int) -> list[Chunk]:
    out: list[Chunk] = []
    for doc_id in sorted(corpus):
        out.extend(chunk(doc_id, corpus[doc_id], strategy, max_tokens,
                          overlap_pct))
    return out
