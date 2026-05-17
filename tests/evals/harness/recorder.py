"""LIVE-ONLY raw-artifact recorder. NEVER imported by the gate.

There is no deployed Bedrock knowledge base in this environment (Phase 1's
operator deploy is a HUMAN-GATE), so the 'system under test' for the eval
is: deterministic BM25 retrieval over the FROZEN corpus -> an LLM
(authenticated `codex` CLI) answering strictly from the retrieved
context -> an LLM judge scoring faithfulness with the committed prompt.
This is exactly the signal a chunking decision needs and is documented in
docs/evals.md. Re-recording is opt-in (EVALS_LIVE=1) and resumable
(existing fixtures are skipped). The gate later RECOMPUTES every
deterministic metric and hash-binds these raw artifacts, so the recorder
cannot manufacture a pass.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _codex_bin() -> str:
    # Windows: the runnable shim is codex.cmd, not the extensionless
    # bash script that CreateProcess cannot launch. Refuse a bare name:
    # only an absolute, existing executable is acceptable (no PATH/CWD
    # hijack of a --dangerously-bypass invocation).
    for name in ("codex.cmd", "codex"):
        found = shutil.which(name)
        if found and Path(found).is_absolute() and Path(found).exists():
            return found
    npm = Path(os.environ.get("APPDATA", "")) / "npm" / "codex.cmd"
    if npm.is_absolute() and npm.exists():
        return str(npm)
    raise RuntimeError(
        "codex CLI not found as an absolute executable; refusing "
        "bare-name exec for a sandbox-bypass invocation")

from compliance_assistant.citations import render_citations
from tests.evals.harness import fixtures_io as FX
from tests.evals.harness.chunking import chunk_corpus
from tests.evals.harness.goldset import (
    index_by_id, load_corpus, load_negatives, load_positives)
from tests.evals.harness.retriever import BM25Index, K_DEFAULT

HARNESS_VERSION = "1"
MODEL_ID = "codex-cli"
REPO = Path(__file__).resolve().parents[3]

# Single source of truth shared with report.py so the two cannot drift.
from tests.evals.harness.configs import DEPLOY_CONFIGS  # noqa: E402

_ANSWER_TMPL = """\
You are a retrieval-augmented PCI DSS compliance assistant. Answer the \
QUESTION using ONLY the CONTEXT passages. If and only if the CONTEXT \
contains the needed information, give a concise 2-4 sentence answer and \
end by citing the relevant PCI DSS requirement id(s) exactly as written \
in the context (e.g. "PCI DSS v4.0 Req 3.5.1"). If the CONTEXT does not \
contain the information, respond with EXACTLY this line and nothing \
else:
Not found in knowledge base
Use no knowledge outside CONTEXT. Output only the answer text.

QUESTION: {question}

CONTEXT:
{context}
"""

_JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "faithfulness": {"type": "number"},
        "hallucination": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["faithfulness", "hallucination", "rationale"],
}


def _codex(prompt: str, schema: dict | None = None, timeout: int = 240) -> str:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "last.txt"
        cmd = [
            _codex_bin(), "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "-s", "read-only", "--skip-git-repo-check", "--ephemeral",
            "-C", str(REPO), "-o", str(out),
        ]
        if schema is not None:
            sp = Path(td) / "schema.json"
            sp.write_text(json.dumps(schema), encoding="utf-8")
            cmd += ["--output-schema", str(sp)]
        cmd.append("-")
        subprocess.run(
            cmd, input=prompt, text=True, encoding="utf-8",
            capture_output=True, timeout=timeout, check=True)
        return out.read_text(encoding="utf-8").strip()


def _context_block(retrieved) -> tuple[str, list[dict]]:
    rc = [{"chunk_id": c.chunk_id, "text": c.text} for c, _ in retrieved]
    block = "\n".join(f"[{i}] {c['text']}" for i, c in enumerate(rc, 1))
    return block, rc


def _trace(rc: list[dict]) -> dict:
    return {"citations": [{"retrievedReferences": [
        {"content": {"text": c["text"]},
         "location": {"s3Location": {"uri": f"s3://corpus/{cid_doc(c)}"}}}
        for c in rc]}]}


def cid_doc(c: dict) -> str:
    # chunk_id is "<doc_id>#...": the citation uri is the source doc.
    return c["chunk_id"].split("#", 1)[0] + ".txt"


def _judge(question: str, context: str, prose_answer: str) -> tuple[str, str]:
    prompt = (
        FX.JUDGE_PROMPT.read_text(encoding="utf-8")
        + f"\n\nQUESTION: {question}\n\nRETRIEVED_CONTEXT:\n{context}"
        + f"\n\nANSWER:\n{prose_answer}\n"
    )
    raw = _codex(prompt, schema=_JUDGE_SCHEMA)
    return prompt, raw


def record(progress=lambda m: None) -> int:
    """Record all missing fixtures. Returns count written. Resumable."""
    if os.environ.get("EVALS_LIVE") != "1":
        raise RuntimeError("recorder is live-only; set EVALS_LIVE=1")
    FX.FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    corpus = load_corpus()
    positives = load_positives()
    negatives = load_negatives()
    by_id = index_by_id()
    p_sha, r_sha = FX.judge_prompt_sha(), FX.judge_rubric_sha()
    written = 0

    for strat, mt, ov in DEPLOY_CONFIGS:
        cfg_key = FX.config_key(strat, mt, ov)
        idx = BM25Index(chunk_corpus(corpus, strat, mt, ov))

        for p in positives:
            fp = FX.fixture_path(p.id, cfg_key)
            if fp.exists():
                continue
            retrieved = idx.search(p.question, K_DEFAULT)
            ctx_block, rc = _context_block(retrieved)
            ans = _codex(_ANSWER_TMPL.format(
                question=p.question, context=ctx_block))
            trace = _trace(rc)
            full = ans + "\n\n" + render_citations(trace)
            jreq, jraw = _judge(p.question, ctx_block, ans)
            fp.write_text(json.dumps({
                "kind": "positive",
                "item_id": p.id,
                "chunking_config": {"strategy": strat,
                                    "max_tokens": mt, "overlap_pct": ov},
                "question": p.question,
                "retrieved_context": rc,
                "retrieved_context_sha256": FX.context_hash(rc),
                "system_answer": full,
                "trace": trace,
                "judge_request": jreq,
                "judge_raw_response": jraw,
                "prompt_sha256": p_sha,
                "rubric_sha256": r_sha,
                "model_id": MODEL_ID,
                "harness_version": HARNESS_VERSION,
                "recorded_at_commit": _head(),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            written += 1
            progress(f"{p.id}__{cfg_key}")

        for n in negatives:
            fp = FX.fixture_path(n.id, cfg_key)
            if fp.exists():
                continue
            retrieved = idx.search(n.question, K_DEFAULT)
            ctx_block, rc = _context_block(retrieved)
            ans = _codex(_ANSWER_TMPL.format(
                question=n.question, context=ctx_block))
            fp.write_text(json.dumps({
                "kind": "negative",
                "item_id": n.id,
                "chunking_config": {"strategy": strat,
                                    "max_tokens": mt, "overlap_pct": ov},
                "question": n.question,
                "retrieved_context": rc,
                "retrieved_context_sha256": FX.context_hash(rc),
                "system_answer": ans,
                "trace": _trace(rc),
                "prompt_sha256": p_sha,
                "rubric_sha256": r_sha,
                "model_id": MODEL_ID,
                "harness_version": HARNESS_VERSION,
                "recorded_at_commit": _head(),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            written += 1
            progress(f"{n.id}__{cfg_key}")

    (FX.FIXTURES_DIR / "recording_manifest.json").write_text(json.dumps({
        "model_id": MODEL_ID,
        "harness_version": HARNESS_VERSION,
        "judge_prompt_sha256": p_sha,
        "judge_rubric_sha256": r_sha,
        "deploy_configs": [FX.config_key(s, m, o)
                           for s, m, o in DEPLOY_CONFIGS],
        "k": K_DEFAULT,
    }, indent=2), encoding="utf-8")
    return written


def _head() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO), text=True,
        capture_output=True, check=True).stdout.strip()
    assert out, "could not resolve HEAD for fixture provenance"
    return out


if __name__ == "__main__":  # pragma: no cover
    print(f"wrote {record(lambda m: print(m, file=sys.stderr))} fixtures")
