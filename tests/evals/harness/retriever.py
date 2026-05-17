"""Deterministic BM25 retriever (stdlib only, no Bedrock).

Pinned by the plan's metric contract: default k = 5, k1 = 1.5, b = 0.75.
Equal scores break ties by chunk_id ascending so ranking is fully
deterministic and reproducible from the frozen corpus alone (mirrors the
seen.sort() determinism rule in compliance_assistant.citations).
"""
from __future__ import annotations

import math
import re
from collections import Counter

from tests.evals.harness.chunking import Chunk

K_DEFAULT = 5
_K1 = 1.5
_B = 0.75
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = list(chunks)
        self._tokens = [tokenize(c.text) for c in self.chunks]
        self._len = [len(t) for t in self._tokens]
        self._avgdl = (sum(self._len) / len(self._len)) if self._len else 0.0
        self._tf = [Counter(t) for t in self._tokens]
        df: Counter = Counter()
        for toks in self._tokens:
            for term in set(toks):
                df[term] += 1
        n = len(self.chunks)
        self._idf = {
            term: math.log(1 + (n - d + 0.5) / (d + 0.5))
            for term, d in df.items()
        }

    def _score(self, q_terms: list[str], i: int) -> float:
        tf = self._tf[i]
        dl = self._len[i]
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = self._idf.get(term, 0.0)
            freq = tf[term]
            denom = freq + _K1 * (
                1 - _B + _B * (dl / self._avgdl if self._avgdl else 0.0))
            score += idf * (freq * (_K1 + 1)) / denom
        return score

    def search(self, query: str, k: int = K_DEFAULT) -> list[tuple[Chunk, float]]:
        q_terms = tokenize(query)
        scored = [
            (self._score(q_terms, i), self.chunks[i].chunk_id, i)
            for i in range(len(self.chunks))
        ]
        # Highest score first; deterministic tie-break by chunk_id asc.
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [(self.chunks[i], s) for s, _, i in scored[:k]]
