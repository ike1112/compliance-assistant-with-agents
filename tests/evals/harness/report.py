"""Score every chunking config, emit report.json (machine contract) +
report.md (rendered from it), select the winner over DEPLOY-EQUIVALENT
configs only, and write that winner into infra/cdk.json.

Selection rule (plan + PRD): max context-recall@k subject to
faithfulness >= 0.95, evaluated only over deploy-equivalent FIXED_SIZE
configs. Deterministic tie-break: then max MRR, then max precision, then
lexicographically smallest config key. HIERARCHICAL is scored on
retrieval for comparison but labelled non-deployable and never selected.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.evals.harness import fixtures_io as FX
from tests.evals.harness import generation_metrics as G
from tests.evals.harness import retrieval_metrics as RM
from tests.evals.harness import task_metrics as TM
from tests.evals.harness.chunking import chunk_corpus
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

# Every config the report scores: 2 deploy-equivalent FIXED_SIZE + 1
# advisory HIERARCHICAL (satisfies "FIXED_SIZE + >=1 of HIER/SEMANTIC").
SCORED_CONFIGS = [
    ("FIXED_SIZE", 512, 20),
    ("FIXED_SIZE", 256, 15),
    ("HIERARCHICAL", 250, 20),
]


def _retrieval(idx: BM25Index, positives, by_id) -> dict:
    per = []
    for p in positives:
        gold = [by_id[g].text for g in p.gold_passage_ids]
        top = [c for c, _ in idx.search(p.question, K_DEFAULT)]
        per.append((top, gold))
    return RM.mean_retrieval(per)


def _generation(cfg_key: str, positives, negatives, by_id,
                subset_ids, expected_by_id) -> dict | None:
    """None when this config has no committed fixtures (advisory)."""
    pos_fx, neg_fx, scored = {}, [], []
    for p in positives:
        fp = FX.fixture_path(p.id, cfg_key)
        if not fp.exists():
            return None
        fx = FX.load_fixture(fp)
        FX.assert_hash_binding(fx, fp.name)
        pos_fx[p.id] = fx
        gold = [by_id[g].text for g in p.gold_passage_ids]
        scored.append(G.score_positive(fx, gold))
    for n in negatives:
        fp = FX.fixture_path(n.id, cfg_key)
        if not fp.exists():
            return None
        fx = FX.load_fixture(fp)
        FX.assert_hash_binding(fx, fp.name)
        neg_fx.append(fx)
    agg = G.aggregate_generation(scored)
    agg["not_found_honesty"] = TM.not_found_honesty(neg_fx)
    agg["requirement_coverage"] = TM.requirement_coverage(
        pos_fx, subset_ids, expected_by_id)
    return agg


def build_report() -> dict:
    corpus = load_corpus()
    positives = load_positives()
    negatives = load_negatives()
    by_id = index_by_id()
    subset_ids = load_labeled_subset()["requirement_coverage_ids"]
    expected_by_id = {p.id: p.expected_requirements for p in positives}

    configs = []
    for strat, mt, ov in SCORED_CONFIGS:
        from tests.evals.harness.chunking import STRATEGIES
        cfg_key = FX.config_key(strat, mt, ov)
        idx = BM25Index(chunk_corpus(corpus, strat, mt, ov))
        entry = {
            "strategy": strat,
            "max_tokens": mt,
            "overlap_pct": ov,
            "config_key": cfg_key,
            "deploy_equivalent": STRATEGIES[strat],
            "retrieval": _retrieval(idx, positives, by_id),
            "generation": _generation(
                cfg_key, positives, negatives, by_id,
                subset_ids, expected_by_id),
        }
        configs.append(entry)

    eligible = [
        c for c in configs
        if c["deploy_equivalent"]
        and c["generation"] is not None
        and not c["generation"]["any_forged"]
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
        "selection_rule": (
            "max context-recall@k subject to faithfulness >= 0.95 over "
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
        "faithfulness | hallucination | citation | not-found | req-cov |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in report["configs"]:
        r = c["retrieval"]
        g = c["generation"]
        def f(x):
            return f"{x:.3f}" if isinstance(x, (int, float)) else "—"
        g = g or {}
        lines.append(
            f"| {c['config_key']} | {c['deploy_equivalent']} | "
            f"{f(r['context_recall'])} | {f(r['context_precision'])} | "
            f"{f(r['mrr'])} | {f(g.get('faithfulness'))} | "
            f"{f(g.get('hallucination'))} | "
            f"{f(g.get('citation_correctness'))} | "
            f"{f(g.get('not_found_honesty'))} | "
            f"{f(g.get('requirement_coverage'))} |")
    lines += ["", f"**Winner (deployable):** `{report['winner']}`",
              "", "_HIERARCHICAL is advisory/non-deployable: "
              "infra/stacks/kb_stack.py emits only fixed-size chunking._",
              ""]
    return "\n".join(lines)


def write_reports(report: dict) -> None:
    REPORT_JSON.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(render_md(report), encoding="utf-8")


def write_cdk_json(winner: dict) -> None:
    text = CDK_JSON.read_text(encoding="utf-8")
    data = json.loads(text)
    ctx = data["context"]
    ctx["chunkingStrategy"] = winner["chunkingStrategy"]
    ctx["chunkMaxTokens"] = int(winner["chunkMaxTokens"])
    ctx["chunkOverlapPercent"] = int(winner["chunkOverlapPercent"])
    CDK_JSON.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> None:  # pragma: no cover - invoked by the live/refresh path
    rep = build_report()
    write_reports(rep)
    if rep["winner"]:
        write_cdk_json(rep["winner"])


if __name__ == "__main__":  # pragma: no cover
    main()
