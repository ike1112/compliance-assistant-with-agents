"""Score every chunking config, emit report.json (machine contract) +
report.md (rendered from it), select the winner over DEPLOY-EQUIVALENT
configs only, and write that winner into infra/cdk.json.

Generation scoring is bound to the RECOMPUTED deterministic retriever:
each fixture's retrieved_context must equal this run's BM25 top-k for
that (question, config), and its identity fields must match — a
hand-authored fixture cannot inject its own context. A missing fixture
for any deploy-equivalent config is a hard failure (advisory
HIERARCHICAL has no fixtures by design). The binding generation
criterion is deterministic groundedness; the recorded judge score is
corroborating evidence only.

Selection rule: max context-recall@k subject to deterministic
groundedness >= 0.95 and faithfulness >= 0.95 and no forged fixture,
over deploy-equivalent FIXED_SIZE configs only. Tie-break: MRR, then
precision, then config key.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.evals.harness import fixtures_io as FX
from tests.evals.harness import generation_metrics as G
from tests.evals.harness import retrieval_metrics as RM
from tests.evals.harness import task_metrics as TM
from tests.evals.harness.chunking import STRATEGIES, chunk_corpus
from tests.evals.harness.configs import DEPLOY_CONFIGS, SCORED_CONFIGS
from tests.evals.harness.goldset import (
    index_by_id, load_corpus, load_labeled_subset, load_negatives,
    load_positives)
from tests.evals.harness.retriever import BM25Index, K_DEFAULT

EVALS_DIR = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
REPORT_JSON = EVALS_DIR / "report.json"
REPORT_MD = EVALS_DIR / "report.md"
CDK_JSON = REPO / "infra" / "cdk.json"

FAITHFULNESS_BAR = 0.95
GROUNDEDNESS_BAR = 0.95
_DEPLOY_KEYS = {FX.config_key(s, m, o) for s, m, o in DEPLOY_CONFIGS}


def _expected_context(idx: BM25Index, question: str) -> list[dict]:
    return [{"chunk_id": c.chunk_id, "text": c.text}
            for c, _ in idx.search(question, K_DEFAULT)]


def _assert_bound(fx: dict, path_name: str, *, item_id: str, question: str,
                  kind: str, cfg: dict, expected_ctx: list[dict]) -> None:
    FX.assert_hash_binding(fx, path_name)
    assert fx["item_id"] == item_id, f"{path_name}: item_id mismatch"
    assert fx["question"] == question, f"{path_name}: question mismatch"
    assert fx["kind"] == kind, f"{path_name}: kind mismatch"
    assert fx["chunking_config"] == cfg, f"{path_name}: config mismatch"
    # The core anti-circularity bind: the fixture's context MUST be this
    # run's recomputed deterministic top-k (a forged context cannot pass).
    assert fx["retrieved_context"] == expected_ctx, (
        f"{path_name}: retrieved_context != recomputed BM25 top-k")


def _generation(idx: BM25Index, cfg_key: str, cfg: dict, positives,
                negatives, by_id, subset_ids, expected_by_id) -> dict:
    pos_fx, neg_fx, scored = {}, [], []
    for p in positives:
        fp = FX.fixture_path(p.id, cfg_key)
        assert fp.exists(), (
            f"missing fixture {fp.name} for deploy-equivalent config "
            f"{cfg_key} — hard fail (no silent skip)")
        fx = FX.load_fixture(fp)
        _assert_bound(fx, fp.name, item_id=p.id, question=p.question,
                      kind="positive", cfg=cfg,
                      expected_ctx=_expected_context(idx, p.question))
        pos_fx[p.id] = fx
        scored.append(G.score_positive(
            fx, [by_id[g] for g in p.gold_passage_ids]))
    for n in negatives:
        fp = FX.fixture_path(n.id, cfg_key)
        assert fp.exists(), (
            f"missing fixture {fp.name} for deploy-equivalent config "
            f"{cfg_key} — hard fail (no silent skip)")
        fx = FX.load_fixture(fp)
        _assert_bound(fx, fp.name, item_id=n.id, question=n.question,
                      kind="negative", cfg=cfg,
                      expected_ctx=_expected_context(idx, n.question))
        neg_fx.append(fx)
    agg = G.aggregate_generation(scored)
    agg["not_found_honesty"] = TM.not_found_honesty(neg_fx)
    agg["requirement_coverage"] = TM.requirement_coverage(
        pos_fx, subset_ids, expected_by_id)
    return agg


def _retrieval(idx: BM25Index, positives, by_id) -> dict:
    per = []
    for p in positives:
        gold = [by_id[g].text for g in p.gold_passage_ids]
        top = [c for c, _ in idx.search(p.question, K_DEFAULT)]
        per.append((top, gold))
    return RM.mean_retrieval(per)


def build_report() -> dict:
    corpus = load_corpus()
    positives = load_positives()
    negatives = load_negatives()
    by_id = index_by_id()
    subset_ids = load_labeled_subset()["requirement_coverage_ids"]
    expected_by_id = {p.id: p.expected_requirements for p in positives}

    configs = []
    for strat, mt, ov in SCORED_CONFIGS:
        cfg_key = FX.config_key(strat, mt, ov)
        cfg = {"strategy": strat, "max_tokens": mt, "overlap_pct": ov}
        idx = BM25Index(chunk_corpus(corpus, strat, mt, ov))
        deploy = STRATEGIES[strat]
        gen = None
        if deploy:  # advisory configs have no fixtures by design
            gen = _generation(idx, cfg_key, cfg, positives, negatives,
                              by_id, subset_ids, expected_by_id)
        configs.append({
            "strategy": strat, "max_tokens": mt, "overlap_pct": ov,
            "config_key": cfg_key, "deploy_equivalent": deploy,
            "retrieval": _retrieval(idx, positives, by_id),
            "generation": gen,
        })

    eligible = [
        c for c in configs
        if c["deploy_equivalent"]
        and c["generation"] is not None
        and not c["generation"]["any_forged"]
        and c["generation"]["groundedness"] >= GROUNDEDNESS_BAR
        and c["generation"]["faithfulness"] >= FAITHFULNESS_BAR
    ]
    winner = None
    if eligible:
        eligible.sort(key=lambda c: (
            -c["retrieval"]["context_recall"],
            -c["retrieval"]["mrr"],
            -c["retrieval"]["context_precision"],
            c["config_key"],
        ))
        w = eligible[0]
        winner = {
            "chunkingStrategy": w["strategy"],
            "chunkMaxTokens": int(w["max_tokens"]),
            "chunkOverlapPercent": int(w["overlap_pct"]),
        }

    return {
        "k": K_DEFAULT,
        "faithfulness_bar": FAITHFULNESS_BAR,
        "groundedness_bar": GROUNDEDNESS_BAR,
        "selection_rule": (
            "max context-recall@k subject to deterministic groundedness "
            ">= 0.95 and faithfulness >= 0.95 and no forged fixture, over "
            "deploy-equivalent FIXED_SIZE configs; tie-break MRR, "
            "precision, then config_key"),
        "configs": configs,
        "winner": winner,
    }


def render_md(report: dict) -> str:
    lines = [
        "# RAG Evaluation Report",
        "",
        f"- k = {report['k']}",
        f"- selection rule: {report['selection_rule']}",
        "",
        "| config | deploy-equiv | recall | precision | MRR | "
        "groundedness | faithfulness | hallucination | citation | "
        "not-found | req-cov |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in report["configs"]:
        r = c["retrieval"]
        g = c["generation"] or {}

        def f(x):
            return f"{x:.3f}" if isinstance(x, (int, float)) else "—"

        lines.append(
            f"| {c['config_key']} | {c['deploy_equivalent']} | "
            f"{f(r['context_recall'])} | {f(r['context_precision'])} | "
            f"{f(r['mrr'])} | {f(g.get('groundedness'))} | "
            f"{f(g.get('faithfulness'))} | {f(g.get('hallucination'))} | "
            f"{f(g.get('citation_correctness'))} | "
            f"{f(g.get('not_found_honesty'))} | "
            f"{f(g.get('requirement_coverage'))} |")
    lines += ["", f"**Winner (deployable):** `{report['winner']}`",
              "", "_HIERARCHICAL is advisory/non-deployable: "
              "infra/stacks/kb_stack.py emits only fixed-size chunking._",
              ""]
    return "\n".join(lines)


def emit_quality_metrics(report: dict, env=None) -> dict | None:
    """Publish the ComplianceAssistant/Quality SLO metrics as a
    CloudWatch EMF line, so the Quality alarms watch a real producer.

    Opt-in via EVALS_EMIT_METRICS (default OFF) so the deterministic
    offline gate never spuriously emits and scoring is unchanged — the
    metrics are emitted by the live/refresh eval run, not the gate.
    Uses the deploy-equivalent config's generation aggregate (the same
    faithfulness/citation the Phase-3 bars use). Returns the emitted
    EMF doc (or None when not emitting / no deploy-equivalent gen)."""
    import os as _os

    from compliance_assistant.tracing import build_quality_emf

    env = env if env is not None else _os.environ
    if env.get("EVALS_EMIT_METRICS", "").strip().lower() not in {
        "1", "true", "yes", "on"
    }:
        return None
    gen = next(
        (c["generation"] for c in report.get("configs", [])
         if c.get("deploy_equivalent") and c.get("generation")),
        None,
    )
    if not gen:
        return None
    doc = build_quality_emf(
        gen.get("faithfulness", 0.0),
        gen.get("citation_correctness", 0.0),
    )
    print(json.dumps(doc, ensure_ascii=False))
    return doc


def write_reports(report: dict) -> None:
    REPORT_JSON.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(render_md(report), encoding="utf-8")
    emit_quality_metrics(report)


def write_cdk_json(winner: dict) -> None:
    data = json.loads(CDK_JSON.read_text(encoding="utf-8"))
    ctx = data["context"]
    ctx["chunkingStrategy"] = winner["chunkingStrategy"]
    ctx["chunkMaxTokens"] = int(winner["chunkMaxTokens"])
    ctx["chunkOverlapPercent"] = int(winner["chunkOverlapPercent"])
    CDK_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> None:  # pragma: no cover - invoked by the live/refresh path
    rep = build_report()
    write_reports(rep)
    if rep["winner"]:
        write_cdk_json(rep["winner"])


if __name__ == "__main__":  # pragma: no cover
    main()
