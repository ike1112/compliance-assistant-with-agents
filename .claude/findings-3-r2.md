# Phase 3 Gate — Round 2 Findings (FAIL: code BLOCKER)

Frozen base `2dd1853..HEAD`. Panel: A codex APPROVE, B PASS, C security
PASS, **D code-reviewer REVISE (1 BLOCKER)**, E regression PASS, F
test-engineer ADVISORY (strong). All round-1 BLOCKER/MAJOR code-path
fixes were verified genuinely remediated; the only blocking item is the
B2 *documentation* half. Round 3 is the final allowed round — the
remediation must be airtight. **Do NOT weaken tests, thresholds,
fixtures, or the frozen gold.**

## BLOCKER

### DR2-1 — B2 residual-trust disclosure must durably exist in a
tracked, in-range artefact
The round-1 B2 spec said to state the residual trust "in `docs/evals.md`
and the rubric". `docs/` is git-ignored (`.gitignore: docs/`), so
`docs/evals.md` is structurally NOT version-controlled and not in the
judged range — it cannot carry the durable disclosure. The tracked
`tests/evals/judge/judge_rubric.md` (in-range) has NO residual-trust
statement.
**Root-cause fix:** add the residual-trust paragraph to the tracked,
in-range `tests/evals/judge/judge_rubric.md`: the recorded judge
faithfulness/hallucination are corroborating evidence only; offline
execution cannot attest an LLM produced `judge_raw_response`; the
binding criterion is recomputed deterministic groundedness ≥ 0.95
against the recomputed BM25 context plus `not any_forged`.
**Constraint:** `judge_rubric.md` is hash-bound (`rubric_sha256` in
every fixture). The recorder sends ONLY `judge_prompt.md` to the model
(`recorder._judge`), never the rubric — the rubric is gate-side
interpretation. So editing the rubric does not change any recorded judge
behaviour or any metric. The fix must therefore also deterministically
refresh `rubric_sha256` in all fixtures + `recording_manifest.json` to
the new committed rubric hash (a pin refresh, not a metric change;
`report.json` parity must still hold). This is legitimate maintenance,
not weakening: the rubric content is owner/builder-controlled committed
text and the pin must track it.

## MINOR / ADVISORY (fold in — round 3 is final, harden now)

- D-MINOR: `test_gate_is_deterministic` pins n=2; the B4 spec asked for
  ≥10× byte-identical canonical JSON. Bump the loop to 10.
- F-advisory-1: add an end-to-end test asserting
  `build_report()["winner"] is None` when BOTH deploy-equivalent configs
  have a forged/ungrounded positive (gate fail-closed proven end-to-end,
  not just the metric).
- F-advisory-2: add a test pinning that an advisory (HIERARCHICAL)
  config can never be selected winner even with superior retrieval.
- F-advisory-3 / codex-MINOR / security-MINOR: conftest also block
  `subprocess.call`/`check_call` and `os.system`/`os.popen` for gate
  tests, with a self-test; add an explicit small length bound in
  `parse_judge` before `json.loads` (clear failure on malformed
  fixture).
- codex-MINOR (already done, no code): `docs/evals.md` selection-rule
  wording corrected (untracked; out of judged range — informational).
- security-MINOR (already done): negative-answer residual-trust
  asymmetry noted in `docs/evals.md`; also covered durably by the
  judge_rubric.md addition above.

## Carried-forward verified-correct (no action — for the record)

B1 anti-circularity bind, B2 deterministic-gate code path, B3
missing-fixture hard-fail, B4 loud render, M2 bounded requirement match,
M3 full report.json parity, M4 offline conftest, configs.py single
source, kb_stack non-FIXED_SIZE guard — all empirically verified correct
by codex + security + code-reviewer. Mutation 0.839 (isolated).
