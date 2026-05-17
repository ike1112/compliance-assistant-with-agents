"""Raw-artifact fixtures: load + validate + hash-bind. No write path here
(the live recorder is the only writer).

A fixture is the RAW recorded behaviour of one (gold item x chunking
config) — system answer, retrieved context, trace, judge request and raw
judge response, plus the SHA-256 of the committed judge prompt/rubric.
The gate RECOMPUTES every deterministic metric from these raw fields and
hash-binds them; it never trusts a precomputed score (there are none).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = EVALS_DIR / "fixtures"
JUDGE_DIR = EVALS_DIR / "judge"
JUDGE_PROMPT = JUDGE_DIR / "judge_prompt.md"
JUDGE_RUBRIC = JUDGE_DIR / "judge_rubric.md"

_REQUIRED = (
    "kind", "item_id", "chunking_config", "question",
    "retrieved_context", "retrieved_context_sha256", "system_answer",
    "trace", "prompt_sha256", "rubric_sha256", "model_id",
    "harness_version",
)
# Positives additionally carry the judge round-trip.
_REQUIRED_POS = _REQUIRED + ("judge_request", "judge_raw_response")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def judge_prompt_sha() -> str:
    return sha256_bytes(JUDGE_PROMPT)


def judge_rubric_sha() -> str:
    return sha256_bytes(JUDGE_RUBRIC)


def config_key(strategy: str, max_tokens: int, overlap_pct: int) -> str:
    return f"{strategy}-{max_tokens}-{overlap_pct}"


def context_hash(retrieved: list[dict]) -> str:
    """Order-sensitive, timestamp-free hash of the retrieved context."""
    payload = json.dumps(
        [[c["chunk_id"], c["text"]] for c in retrieved],
        ensure_ascii=False, separators=(",", ":"))
    return sha256_text(payload)


def fixture_path(item_id: str, cfg_key: str) -> Path:
    return FIXTURES_DIR / f"{item_id}__{cfg_key}.json"


_MAX_FIXTURE_BYTES = 1_000_000


def load_fixture(path: Path) -> dict:
    raw = path.read_bytes()
    assert len(raw) <= _MAX_FIXTURE_BYTES, (
        f"{path.name}: fixture exceeds {_MAX_FIXTURE_BYTES} bytes")
    fx = json.loads(raw.decode("utf-8"))
    required = _REQUIRED_POS if fx.get("kind") == "positive" else _REQUIRED
    missing = [k for k in required if k not in fx]
    assert not missing, f"{path.name}: missing fixture fields {missing}"
    return fx


def assert_hash_binding(fx: dict, path_name: str) -> None:
    """Bind a fixture to the committed judging contract + its own context.

    Fails closed: a tampered/forged fixture decoupled from the committed
    judge prompt/rubric or whose recorded context hash does not match its
    recorded context is rejected before any metric is read.
    """
    assert fx["prompt_sha256"] == judge_prompt_sha(), (
        f"{path_name}: prompt_sha256 != committed judge_prompt.md")
    assert fx["rubric_sha256"] == judge_rubric_sha(), (
        f"{path_name}: rubric_sha256 != committed judge_rubric.md")
    assert fx["retrieved_context_sha256"] == context_hash(
        fx["retrieved_context"]), (
        f"{path_name}: retrieved_context_sha256 does not match context")


def load_all() -> list[tuple[Path, dict]]:
    out = []
    for p in sorted(FIXTURES_DIR.glob("*.json")):
        if p.name == "recording_manifest.json":
            continue
        out.append((p, load_fixture(p)))
    return out
