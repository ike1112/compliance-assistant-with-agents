# Feature: Observability + SLOs (test-enforced)

## Summary

Make the crew observable and its reliability contract machine-checked,
without leaking sensitive data on ANY emitted path. Add (1)
`docs/SLOs.md` — numeric per-stage + end-to-end latency p50/p95,
quality SLOs reusing the Phase-3 0.95 faithfulness/citation bars,
run-success availability, each with a 30-day error budget AND an
explicit CloudWatch metric contract (namespace/metric/statistic/period/
evaluation/comparator); (2) `src/compliance_assistant/tracing.py` that
wires CrewAI step/task callbacks to emit exactly three stage spans
mapped to the PRD names researcher / writer / designer, each with
non-empty input + output and a faithfully-captured `tool_calls` field
(non-empty only for the researcher, which is the only agent with a
tool — see the recorded owner CHECK-intent ruling in Notes), passed
through a Luhn-validated PAN + email redaction filter, with a
provenance/hash-bound recorded fixture replayed offline (opt-in live
recorder, mirroring the Phase-3 harness); (3) a new
`ComplianceObservabilityStack` that creates a CloudWatch log group, a
Bedrock model-invocation-logging configuration via a CDK
`AwsCustomResource` **with content-bearing data delivery disabled** so
raw prompts/responses are never written to CloudWatch, a CloudWatch
dashboard, and one alarm **per SLO parsed from `docs/SLOs.md`** bound to
that SLO's concrete metric; (4) `infra/tests` that parse both
`docs/SLOs.md` and the synthesized template and cross-check
alarm-count == SLO-count, each alarm's full metric binding == its SLO
contract, the Bedrock-logging custom resource present with raw-content
delivery OFF, dashboard present, and the IAM-wildcard accounting; (5) a
README decision record + cfn-lint/cfn-guard handling mirroring Phase-4.
The Phase-2 (`agent_ids.py`) and Phase-3 (`tests/evals/gold/`,
`citations.py`) frozen surfaces are not touched.

## User Story

As the operator of the compliance assistant
I want per-agent traces, metadata-only model-invocation logging, and SLO-bound alarms derived from a single documented contract
So that I can monitor input/output at each agent level and detect SLO violations automatically, with a guarantee that no PAN/email leaks on any emitted path and that every alarm provably watches the SLO's real metric.

## Problem Statement

The crew runs blind: no per-agent input/output trace, no Bedrock
invocation logging, no SLOs, no alarms, and no guarantee an alarm
matches a documented target or that logs are PAN-safe. Phase 5 must
close GAP-OPS-02 (observability), GAP-SEC-03 (sensitive-data redaction
on every emitted path) and GAP-OPS-03 (SLOs) as synth-time + offline
verifiable artifacts, with the alarm↔SLO correspondence and the
no-raw-content invariant machine-proven.

## Solution Statement

Single source of truth: `docs/SLOs.md`, where each row carries BOTH the
numeric target/budget AND the CloudWatch metric contract. A
deterministic parser (`infra/stacks/slo_contract.py`) yields structured
SLO records; the stack builds exactly one alarm per record bound to
that metric, so the cross-check test proves a semantic binding, not a
threshold-only tautology. Redaction is enforced on BOTH emitted paths:
the in-process span sink (Luhn-validated PAN + email filter) AND the
Bedrock model-invocation-logging path, by configuring the logging
custom resource with text/image/embedding/video data delivery DISABLED
(metadata only — raw prompts/responses are never delivered to
CloudWatch). The tracer never changes crew output (mirrors the
`CREW_VERBOSE` "output unchanged" contract). Bedrock model-invocation
logging has no native CFN resource, so a CDK `AwsCustomResource`
(`install_latest_aws_sdk=False`, offline/deterministic synth) is used;
its account-level API gets one justified inline `Resource:"*"` exactly
like the Phase-4 ecr token, AND the plan explicitly accounts for the
CDK provider-framework singleton Lambda's `AWSLambdaBasicExecutionRole`
managed policy (a known, logs-only CDK pattern) as a documented,
test-asserted, README-justified exception — the "sole wildcard" claim
is scoped to the stack's own inline statements.

## Metadata

| Field            | Value                                                                 |
| ---------------- | --------------------------------------------------------------------- |
| Type             | NEW_CAPABILITY                                                        |
| Complexity       | HIGH (crew callback instrumentation, dual-path redaction, custom-resource IaC, SLO↔alarm semantic binding) |
| Systems Affected | `src/compliance_assistant/` (new tracing module), `tests/` (new tracing+redaction tests + provenance-bound fixture), `infra/` (new stack, app wiring, tests, README), `docs/SLOs.md` |
| Dependencies     | `aws-cdk-lib>=2.254.0,<3.0.0` (`custom_resources.AwsCustomResource`, `aws_cloudwatch`, `aws_logs`), `crewai[tools]>=0.105.0` (Crew `step_callback`/`task_callback`), `pytest>=8.0`, `cfn-lint>=1.0` — no new runtime dependency |
| Implementation items | 9 |

---

## UX Design

### Before State
```
operator → crew.kickoff() → output/*.md   (no trace, no logs, no SLOs)
PAIN: no per-agent I/O visibility; no Bedrock invocation logging; no
      numeric reliability targets; an alarm (if any) could silently
      drift from the target or watch the wrong metric; raw PAN/email
      could land in logs
```

### After State
```
operator → crew.kickoff() ─► step/task callbacks ─► 3 redacted spans
              │ (output byte-unchanged)   researcher/writer/designer
              ▼
  Bedrock model-invocation logging → CloudWatch (METADATA ONLY —
              text/image/embedding/video delivery DISABLED)
              ▼
  docs/SLOs.md (target + 30d budget + metric contract)
       └─parse─► ComplianceObservabilityStack
                  • CloudWatch dashboard
                  • exactly N alarms, one per SLO, threshold == the
                    SLOs.md number, bound to the SLO's real metric
  infra tests parse SLOs.md + synthesized template → assert
  alarm-count == SLO-count, full metric binding per SLO, raw-content
  delivery OFF, IAM-wildcard accounting
VALUE: per-agent I/O observable; invocations logged WITHOUT raw
       content; SLOs numeric + budgeted; alarms provably watch the
       right metric; fake PAN/email masked on every emitted path
```

### Interaction Changes
| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| crew run | no trace | 3 redacted per-agent spans (offline fixture in gate; opt-in live) | input/output observable per agent |
| Bedrock | no logging | metadata-only invocation logging (no raw prompt/response) | every call auditable, PAN-safe |
| `infra/app.py` | 4 stacks | + `ComplianceObservabilityStack` | `cdk synth --all` emits it |
| `docs/SLOs.md` | absent | numeric SLOs + 30d budgets + metric contracts | reliability contract explicit + machine-checked |

---

## Mandatory Reading

| Priority | File | Why |
|----------|------|-----|
| P0 | `src/compliance_assistant/crew.py` (full) | `@crew` `Crew(...)` is where `step_callback`/`task_callback` attach; the 3 agent/task method names (`regulation_researcher`/`report_writer`/`solution_designer`) are the span sources to MAP to PRD names; `_VERBOSE` "output unchanged" contract to preserve; only `regulation_researcher` has a tool |
| P0 | `src/compliance_assistant/startup.py` | `crew_verbose_enabled` env-flag pattern to MIRROR for `TRACING_LIVE`; import-time-side-effect-free rule |
| P0 | `tests/evals/harness/recorder.py` + `fixtures_io.py` + `tests/evals/conftest.py` | The live-only recorder + provenance fields (`recorded_at_commit`, `model_id`, `harness_version`) + `assert_hash_binding` + offline socket/subprocess guard to MIRROR for the tracing fixture (NOT a hand-authored JSON) |
| P0 | `infra/stacks/runtime_stack.py` + `runtime_ecr_stack.py` | dedicated-stack + `R-<NAME>` + RETAIN + scoped-IAM + sole-inline-wildcard pattern; note these are Lambda-FREE (their sole-wildcard test holds because no provider Lambda) — this stack is NOT Lambda-free (see IAM accounting) |
| P0 | `infra/tests/test_runtime_stack.py` | `Template.from_stack` / `has_resource_properties` / `find_resources` / `Match.object_like` / no-wildcard / context→ValueError patterns to MIRROR + ADAPT for the provider-Lambda |
| P1 | `infra/app.py` (full) | how a 5th stack is instantiated |
| P1 | `infra/README.md` "AgentCore Runtime hosting decision" + "Accepted cfn-guard exceptions" | decision-record + Reasoning-Gate phrasing to MIRROR for the model-invocation-logging decision + the justified custom-resource wildcard + the provider-framework managed-policy exception |
| P1 | `src/compliance_assistant/citations.py` | Phase-5 mutation target — confirm this plan does NOT modify it (kill-rate ≥0.80 stays) |
| P2 | `docs/evals.md` | tone/structure to mirror for `docs/SLOs.md` |
| P2 | `.claude/review-gate.config.json` phase "5" | mutation `citations.py` @0.80, coverage 0.90, no exemption — do NOT edit (BASE) |

**External documentation:**
| Source | Why |
|--------|-----|
| [Configure Bedrock model-invocation logging via CloudFormation (AWS prescriptive guidance)](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/configure-bedrock-invocation-logging-cloudformation.html) | No native CFN resource → Lambda/custom resource calling `PutModelInvocationLoggingConfiguration` (the documented decision) |
| [PutModelInvocationLoggingConfiguration API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_PutModelInvocationLoggingConfiguration.html) | `loggingConfig` has `textDataDeliveryEnabled` / `imageDataDeliveryEnabled` / `embeddingDataDeliveryEnabled` / `videoDataDeliveryEnabled` toggles → set OFF for PAN-safety; `cloudWatchConfig` needs `logGroupName`+`roleArn`; account-level (no resource ARN) |
| [CDK `custom_resources.AwsCustomResource`](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.custom_resources/AwsCustomResource.html) | Singleton provider Lambda (its role gets `AWSLambdaBasicExecutionRole` — accounted for); `install_latest_aws_sdk=False` (offline/deterministic); `AwsCustomResourcePolicy.from_statements` to avoid default `Resource:"*"` |

---

## Patterns to Mirror

**ENV-FLAG (mirror startup.crew_verbose_enabled):**
```python
_TRUTHY = {"1", "true", "yes", "on"}
def tracing_live_enabled(env) -> bool:
    return env.get("TRACING_LIVE", "").strip().lower() in _TRUTHY
```

**SPAN IDENTITY MAP (repo → PRD names; explicit, asserted):**
```python
# crew.py methods -> PRD CHECK span names
_SPAN_NAME = {
    "regulation_researcher": "researcher",
    "report_writer": "writer",
    "solution_designer": "designer",
}
# tool_calls is ALWAYS a present list; non-empty ONLY for "researcher"
# (the sole agent with a tool, crew.py). NO sentinel entries — an
# empty list for writer/designer is the truthful capture. (Owner
# CHECK-intent ruling, see Notes.)
```

**CREW CALLBACK WIRING (crew.py @crew — additive, output unchanged):**
```python
from compliance_assistant.tracing import build_tracer
_tracer = build_tracer()
return Crew(agents=self.agents, tasks=self.tasks, verbose=_VERBOSE,
            max_rpm=10,
            step_callback=_tracer.on_step, task_callback=_tracer.on_task)
```

**PROVENANCE/HASH-BOUND FIXTURE (mirror tests/evals/harness/fixtures_io):**
```python
# fixture carries: recorder_version, recorded_at_commit, model_id,
# and per-span sha256 of (input|output|tool_calls). The offline test
# RECOMPUTES each sha and asserts binding (a hand-edited fixture fails),
# exactly as assert_hash_binding does for the eval harness.
```

**SINGLE JUSTIFIED INLINE WILDCARD + PROVIDER-FRAMEWORK ACCOUNTING:**
```python
# JUSTIFIED inline: bedrock:Put/DeleteModelInvocationLoggingConfiguration
# are account-level ops with no resource ARN form. Sole literal
# Resource:"*" AMONG THE STACK'S OWN INLINE STATEMENTS.
cr.AwsCustomResourcePolicy.from_statements([
    iam.PolicyStatement(actions=["bedrock:PutModelInvocationLoggingConfiguration",
                                 "bedrock:DeleteModelInvocationLoggingConfiguration"],
                         resources=["*"]),
    iam.PolicyStatement(actions=["iam:PassRole"], resources=[delivery_role.role_arn]),
])
# ACCOUNTED-FOR: the AwsCustomResource provider framework also creates
# a singleton Lambda whose role has the AWS-managed
# AWSLambdaBasicExecutionRole (logs-only, effective Resource:"*" for
# CloudWatch Logs). This is a well-understood CDK pattern, not a
# hand-authored wildcard; the test asserts it is the ONLY managed
# policy and it is exactly AWSLambdaBasicExecutionRole, and README
# records it as an accepted CDK-provider-framework exception with a
# Reasoning-Gate justification.
```

**BEDROCK LOGGING — METADATA ONLY (PAN-safe by construction):**
```python
# loggingConfig: cloudWatchConfig=logGroup+roleArn, and
# textDataDeliveryEnabled / imageDataDeliveryEnabled /
# embeddingDataDeliveryEnabled / videoDataDeliveryEnabled = FALSE.
# => raw prompts/responses are NEVER delivered to CloudWatch, so the
# redaction CHECK ("masked/absent in emitted logs/traces") holds on
# the Bedrock path by construction, not just the span path.
```

---

## Files to Change

| File | Action | Justification |
|------|--------|---------------|
| `docs/SLOs.md` | CREATE | Per-SLO row: numeric target, 30-day error budget, AND metric contract (namespace/metric/statistic/period/evaluation/comparator). Single source of truth |
| `src/compliance_assistant/tracing.py` | CREATE | Crew callbacks → 3 PRD-named redacted spans; Luhn+boundary PAN + email redaction; live/offline flag; provenance-stamped recorder + hash-bound loader. New module; touches no frozen surface |
| `src/compliance_assistant/crew.py` | UPDATE | Add `step_callback`/`task_callback` only; output + existing behavior byte-unchanged (mirror `_VERBOSE` contract) |
| `tests/test_tracing.py` | CREATE | Offline: recompute per-span hashes + recorder/commit provenance; assert exactly 3 spans named researcher/writer/designer, each non-empty input+output, `tool_calls` present, non-empty only for researcher; live path behind `TRACING_LIVE` |
| `tests/test_redaction.py` | CREATE | Fake PAN (Luhn-valid `4111111111111111`, spaced, dashed) + email masked/absent in spans; AND assert long non-PAN numeric IDs stay visible (anti-over-redaction regression) |
| `tests/tracing/fixtures/run_spans.json` | CREATE | Live-recorder-generated, provenance + per-span sha256; replayed offline (no live Bedrock in gate) |
| `infra/stacks/slo_contract.py` | CREATE | Deterministic `docs/SLOs.md` → `[SLO(slo_id, threshold, namespace, metric, statistic, period_s, eval_periods, comparator, budget_30d)]`; fail-closed on malformed/empty |
| `infra/stacks/observability_stack.py` | CREATE | `ComplianceObservabilityStack`: log group, Bedrock invocation-logging `AwsCustomResource` (raw-content delivery OFF), dashboard, one metric-bound alarm per SLO |
| `infra/app.py` | UPDATE | Instantiate `ComplianceObservabilityStack`; standalone (no bulk-runtime-deploy coupling); update docstring (five stacks) |
| `infra/tests/test_observability_stack.py` | CREATE | Parse SLOs.md + template; assert alarm-count==SLO-count; per-alarm full metric binding (Namespace/MetricName/Statistic/Period/EvaluationPeriods/ComparisonOperator/Threshold) == SLO; Bedrock-logging custom resource present with all data-delivery flags FALSE; dashboard present; exactly one inline `Resource:"*"` (the Bedrock op); the only managed policy is `AWSLambdaBasicExecutionRole` on the provider role; empty-SLOs → ValueError |
| `infra/README.md` | UPDATE | "Model-invocation logging decision (current-docs verified)" record; the justified Bedrock-logging inline wildcard AND the CDK-provider-framework managed-policy exception in "Accepted cfn-guard exceptions"; cfn-lint region-scope note |

---

## NOT Building (Scope Limits)

- **No modification of `agent_ids.py` (Phase-2 frozen), `citations.py`
  (Phase-5 mutation target, must stay ≥0.80), or `tests/evals/gold/`
  (Phase-3 frozen).** Tracing is a NEW module; `crew.py` change is
  additive callbacks only (no agent/task/output/`_has_grounded_findings`
  change).
- **No raw-content Bedrock logging.** Content delivery flags are OFF —
  invocation metadata only. (This is what makes the redaction CHECK
  honestly satisfiable on the Bedrock path.)
- **No sentinel/fake tool-call entries.** `tool_calls` is the truthful
  capture: non-empty for the researcher, empty (but present) for
  writer/designer. (Owner CHECK-intent ruling — Notes.)
- **No native Bedrock-logging CFN resource** (none exists);
  `AwsCustomResource`, `install_latest_aws_sdk=False`.
- **No new runtime dependency**; stdlib + already-present CDK modules.
- **No edit of `review_gate/` or `.claude/review-gate.config.json`**
  (BASE, integrity-protected). No X-Ray.
- **No giving writer/designer new tools** (would change crew design /
  risk the Phase-2/3 output contract — out of scope per owner ruling).

---

## Implementation

Execute in order. Each item is atomic and independently verifiable.
(Intent-led headings — no positional labels, per the durable-artefact rule.)

### Author `docs/SLOs.md` with target + budget + metric contract
- **ACTION**: One row per SLO in a parser-stable table:
  `| slo_id | description | namespace | metric | statistic | period_s | eval_periods | comparator | threshold | 30d_error_budget |`.
- **IMPLEMENT**: per-stage latency p50/p95 (researcher/writer/designer), end-to-end p50/p95, quality (`faithfulness ≥ 0.95`, `citation_correctness ≥ 0.95` — reuse the Phase-3 bars), run-success-rate availability; each with a numeric 30-day error budget and a real CloudWatch metric (namespace e.g. `ComplianceAssistant/Crew`, the metric the tracer/runtime emits, or a documented Bedrock/`AWS/Bedrock` metric for invocation health). Prose explains each; the table is the machine contract.
- **MIRROR**: `docs/evals.md` tone.
- **GOTCHA**: threshold + period + eval_periods are bare numbers; comparator ∈ a fixed enum the parser maps to CDK `ComparisonOperator`.
- **VALIDATE**: `PYTHONPATH=. python -c "from infra.stacks.slo_contract import parse_slos;s=parse_slos('docs/SLOs.md');assert len(s)>=6 and all(x.namespace and x.metric for x in s)"`.

### Create `infra/stacks/slo_contract.py` (structured deterministic parser)
- **ACTION**: `@dataclass SLO` with `slo_id, description, namespace, metric, statistic, period_s:int, eval_periods:int, comparator, threshold:float, budget_30d`; `parse_slos(path)->list[SLO]` ordered, deterministic, raises `ValueError` on malformed/empty/duplicate-id (fail-closed, mirror kb_stack `raise ValueError`).
- **VALIDATE**: `PYTHONPATH=. python -c "from infra.stacks.slo_contract import parse_slos;print(len(parse_slos('docs/SLOs.md')))"` ≥6.

### Create `src/compliance_assistant/tracing.py` (callbacks + dual-safe redaction + provenance)
- **ACTION**: `build_tracer()` → object with `on_step`/`on_task` (accept `*args,**kwargs`, defensively extract) accumulating exactly 3 spans keyed by the `_SPAN_NAME` map → `researcher`/`writer`/`designer`, each `{name,input,output,tool_calls:[...] }`; `redact(text)` masking email and **Luhn-validated** PAN (candidate `(?<!\d)(?:\d[ -]?){13,19}(?!\d)` then strip separators and Luhn-check before masking → `[REDACTED-PAN]`; non-Luvn long IDs stay visible); spans redacted before record; `record(path)` writes provenance (`recorder_version`, `recorded_at_commit` via `git rev-parse HEAD`, `model_id`, per-span `sha256(input|output|tool_calls)`); `load(path)` returns spans; `verify(fixture)` recomputes each sha and asserts binding (mirror `assert_hash_binding`). `tracing_live_enabled(env)` (`TRACING_LIVE`). No import-time crew/boto3 import (lazy seam — Phase-4 lesson).
- **GOTCHA**: crew output byte-unchanged; `tool_calls` present always, non-empty only for `researcher`; NO sentinel.
- **VALIDATE**: `PYTHONPATH=src python -c "import compliance_assistant.tracing"` exits 0.

### Wire callbacks into `src/compliance_assistant/crew.py`
- **ACTION**: lazily `from compliance_assistant.tracing import build_tracer` inside `@crew`; pass `step_callback`/`task_callback`; nothing else changes; keep the "output unchanged either way" comment contract.
- **VALIDATE**: `PYTHONPATH=src python -c "import compliance_assistant.crew"` exits 0; existing `tests/` unaffected.

### Record the provenance-bound offline fixture `tests/tracing/fixtures/run_spans.json`
- **ACTION**: Generate ONLY via the live recorder (`TRACING_LIVE=1`, a real crew run); commit the result with provenance + per-span sha256. The gate replays it offline; `verify()` recompute makes a hand-edited fixture fail.
- **MIRROR**: `tests/evals/harness/recorder.py` live-only + manifest/commit-stamp.
- **VALIDATE**: `python -c "import json;d=json.load(open('tests/tracing/fixtures/run_spans.json'));assert len(d['spans'])==3 and d['recorded_at_commit'] and all('sha256' in s for s in d['spans'])"`.

### Create `tests/test_tracing.py` (offline, hash-bound, opt-in live)
- **ACTION**: offline (no net/subprocess): `load`+`verify` the fixture (recompute per-span sha; recorder_version + recorded_at_commit present); assert exactly 3 spans named `researcher`/`writer`/`designer`, each non-empty `input`+`output`, `tool_calls` PRESENT (list), non-empty only for `researcher`, empty for `writer`/`designer`; assert no raw PAN/email pattern survives in any span. `live` path (skip unless `TRACING_LIVE=1`) re-records.
- **VALIDATE**: `PYTHONPATH=src python -m pytest tests/test_tracing.py -q` passes.

### Create `tests/test_redaction.py`
- **ACTION**: feed Luhn-valid fake PAN (`4111111111111111`, `4111 1111 1111 1111`, `4111-1111-1111-1111`) + email through `redact` AND a built span; assert raw absent / mask present. Anti-over-redaction: assert a 16-digit NON-Luhn id (e.g. `1234567890123456`) and a long request id stay VISIBLE (documents the tradeoff).
- **VALIDATE**: `PYTHONPATH=src python -m pytest tests/test_redaction.py -q` passes.

### Create `infra/stacks/observability_stack.py` + wire `infra/app.py`
- **ACTION**: `ComplianceObservabilityStack`: `R-OBS-LOGS` `logs.LogGroup` (explicit retention, RETAIN); `R-OBS-ROLE` Bedrock delivery `iam.Role(ServicePrincipal("bedrock.amazonaws.com", conditions SourceAccount))` scoped to `logs:CreateLogStream`/`PutLogEvents` on the log-group ARN; `R-OBS-CFG` `cr.AwsCustomResource(install_latest_aws_sdk=False)` onCreate/onUpdate `bedrock.putModelInvocationLoggingConfiguration` with `cloudWatchConfig`=logGroup+roleArn and **`textDataDeliveryEnabled=False, imageDataDeliveryEnabled=False, embeddingDataDeliveryEnabled=False, videoDataDeliveryEnabled=False`**, onDelete `deleteModelInvocationLoggingConfiguration`, policy `from_statements` (the 2 statements in Patterns); `R-OBS-DASH` `cloudwatch.Dashboard`; `R-OBS-ALARM` one `cloudwatch.Alarm` per `parse_slos("docs/SLOs.md")` SLO, each bound to `cloudwatch.Metric(namespace=slo.namespace, metric_name=slo.metric, statistic=slo.statistic, period=Duration.seconds(slo.period_s))`, `threshold=slo.threshold`, `evaluation_periods=slo.eval_periods`, `comparison_operator=` mapped from `slo.comparator`, alarm name derived from `slo_id`. `app.py`: instantiate standalone; update docstring (five stacks). Anchor the SLOs.md path to repo root via `pathlib.Path(__file__)` (mirror kb_stack asset anchoring).
- **GOTCHA**: MUST use `from_statements` (default policy is `Resource:"*"`); `install_latest_aws_sdk=False`; data-delivery flags literally False in the SDK call params.
- **VALIDATE**: `cd infra && npx aws-cdk@latest synth --all -q` exits 0 emitting `ComplianceObservabilityStack`.

### Create `infra/tests/test_observability_stack.py` + README decision record
- **ACTION**: `Template.from_stack`; `slos=parse_slos("docs/SLOs.md")`; assert `resource_count_is("AWS::CloudWatch::Alarm", len(slos))`; for each SLO find its alarm and assert Namespace/MetricName/Statistic/Period/EvaluationPeriods/ComparisonOperator/Threshold ALL equal the SLO record (semantic binding, not threshold-only); `resource_count_is("AWS::CloudWatch::Dashboard",1)`; the Bedrock-logging custom resource present AND its `Create`/`Update` payload has `textDataDeliveryEnabled:false`+image+embedding+video false (parse the `Create` JSON); log group present with a finite retention; **IAM accounting**: exactly one inline policy statement with literal `Resource:"*"` and its actions ⊆ `{bedrock:PutModelInvocationLoggingConfiguration, bedrock:DeleteModelInvocationLoggingConfiguration}`; assert the ONLY `AWS::IAM::ManagedPolicy`/managed-arn attached is `AWSLambdaBasicExecutionRole` on the provider role (no other managed policy); empty/malformed SLOs.md → `pytest.raises(ValueError)` (mirror kb_stack context→ValueError). README: add "Model-invocation logging decision (current-docs verified, 2026-05)" (no native CFN resource → AwsCustomResource; dated; mirror Phase-4 record) + in "Accepted cfn-guard exceptions" the justified inline Bedrock-logging wildcard AND the CDK-provider-framework `AWSLambdaBasicExecutionRole` managed-policy exception (Reasoning-Gate phrasing); note cfn-lint `-r us-east-1` (document E3006 only if it appears).
- **VALIDATE**: `PYTHONPATH=src python -m pytest infra/tests -q` all pass; `cd infra && cfn-lint -r us-east-1 cdk.out/ComplianceObservabilityStack.template.json` 0 errors; `rg -n "Model-invocation logging decision|Reasoning-Gate|AWSLambdaBasicExecutionRole" infra/README.md` matches.

---

## Testing Strategy

| Test | Cases | Validates |
|------|-------|-----------|
| `tests/test_tracing.py` | 3 spans researcher/writer/designer; non-empty input+output; tool_calls present, non-empty only for researcher; hash+provenance bound; redaction applied; live skipped offline | CHECK: tracing spans (owner CHECK-intent ruling) |
| `tests/test_redaction.py` | Luhn PAN spaced/dashed/plain + email masked; non-Luhn 16-digit + request-id stay visible | CHECK: redaction; anti-over-redaction |
| `infra/tests/test_observability_stack.py` | alarm-count==SLO-count; full per-alarm metric binding; raw-content delivery OFF; dashboard present; one inline `*` (bedrock op); only managed policy == AWSLambdaBasicExecutionRole; empty-SLOs→ValueError | CHECK: infra logging+dashboard+alarm cross-check + IAM accounting |
| `infra/tests` (full) | no regression to kb/agent/runtime/runtime-ecr | CHECK: prior suites green |

### Edge Cases
- [ ] N SLO rows → exactly N alarms, each bound to its real metric + threshold
- [ ] malformed/empty/dup-id SLOs.md → `ValueError` at synth
- [ ] writer/designer `tool_calls` == `[]` (present, empty, truthful) — no sentinel
- [ ] Luhn PAN (spaced/dashed/plain) + email masked; non-Luhn 16-digit + request id visible
- [ ] Bedrock logging Create payload: all 4 data-delivery flags False
- [ ] exactly one inline `Resource:"*"`; provider role's only managed policy is AWSLambdaBasicExecutionRole
- [ ] tracer no-op sink ⇒ crew output byte-unchanged; imports offline
- [ ] no change under `agent_ids.py`/`citations.py`/`tests/evals/gold/`

---

## Validation Commands

> The phase-gate panel + the PRD CHECK regression leg are the gate of
> record. The lines below are **Phase 5's PRD GATE/CHECK items,
> verbatim** — the only validation contract for this phase. (The owner
> ruled on the tool-call CHECK's *intent*; the PRD text is unchanged.)

- GATE: panel PASS required — same panel as Phase 2 (mutation+coverage / codex / security / code / CHECK-regression), evaluated on this phase's frozen diff before `complete`.
- CHECK: `docs/SLOs.md` exists with **numeric** targets: per-stage + end-to-end latency p50/p95, quality (reuses Phase 3 faithfulness/citation bars), run-success-rate availability, and an explicit 30-day error budget per SLO.
- CHECK: `pytest tests/test_tracing.py -q` passes — a captured run (recorded fixture; opt-in live) emits exactly 3 stage spans (researcher / writer / designer), **each with non-empty input, output, and tool-call list** (this is the owner's "monitor input and output at each agent level", made binary).
- CHECK: `pytest infra/tests` asserts Bedrock model-invocation logging resource present, a CloudWatch dashboard present, and **alarm count == count of SLOs in `SLOs.md`** with **each alarm threshold == the matching `SLOs.md` number** (test parses both and cross-checks).
- CHECK: redaction test — feeding a known fake PAN/email through the logging path asserts it is masked/absent in emitted logs/traces.
- CHECK: cfn-lint 0 errors; cfn-guard compliant or justified; prior suites green.

### Local check commands
```bash
test -f docs/SLOs.md && echo SLOs-ok
PYTHONPATH=src python -m pytest tests/test_tracing.py tests/test_redaction.py -q
cd infra && npx aws-cdk@latest synth --all -q && cd ..
PYTHONPATH=src python -m pytest infra/tests -q
cd infra && cfn-lint -r us-east-1 cdk.out/ComplianceObservabilityStack.template.json
# cfn-guard: COMPLIANT, or the README Reasoning-Gate justification —
# the single inline account-level Bedrock-logging wildcard AND the
# CDK-provider-framework AWSLambdaBasicExecutionRole managed policy
# (logs-only, well-understood) — same accepted path as Phase 1/4.
PYTHONPATH=src python -m pytest infra/tests tests -q -m "not gate and not live"
```
**EXPECT**: all exit 0; the observability template has exactly one
inline `Resource:"*"` (the account-level Bedrock-logging op) and the
provider role's only managed policy is `AWSLambdaBasicExecutionRole`,
both documented in README; the Bedrock-logging Create payload has all
data-delivery flags `false`.

---

## Acceptance Criteria
- [ ] `docs/SLOs.md` exists: numeric per-stage+e2e latency p50/p95, quality (0.95 reuse), availability, 30-day budget per SLO, plus a metric contract per row
- [ ] `pytest tests/test_tracing.py` passes: exactly 3 PRD-named spans, each non-empty input+output, `tool_calls` present (non-empty only for researcher), provenance/hash-bound, offline-deterministic, live opt-in
- [ ] `pytest infra/tests` asserts Bedrock model-invocation logging present (raw-content delivery OFF), dashboard present, alarm-count==SLO-count, full per-alarm metric binding == SLOs.md
- [ ] redaction: Luhn PAN + email masked/absent on span path AND raw content never delivered on the Bedrock path; non-Luhn long IDs stay visible
- [ ] cfn-lint 0 (region-scoped); cfn-guard COMPLIANT or README-justified; exactly one inline IAM `Resource:"*"` (the bedrock-logging op); provider managed policy == only `AWSLambdaBasicExecutionRole`, documented
- [ ] prior suites green; no change under `agent_ids.py`/`citations.py`/`tests/evals/gold/`; `citations.py` mutation ≥0.80 unchanged; changed-line coverage ≥0.90
- [ ] no live AWS spend; no new runtime dependency; no pipeline jargon in any durable artefact

## Completion Checklist
- [ ] Every implementation item completed in order, each validated immediately
- [ ] Phase 5 PRD CHECK regression commands all exit 0
- [ ] Phase-gate panel PASS (codex / mutation+coverage / security / code / regression; test-engineer advisory)

---

## Risks and Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Raw PAN reaches CloudWatch via Bedrock logging (the redaction gap) | — | — | RESOLVED: text/image/embedding/video data delivery DISABLED in the logging config; infra test asserts the Create payload flags are false |
| `AwsCustomResource` provider Lambda adds a 2nd effective wildcard (AWSLambdaBasicExecutionRole) | — | — | RESOLVED: "sole wildcard" scoped to the stack's own INLINE statements; test asserts the provider's only managed policy is exactly AWSLambdaBasicExecutionRole; README records it as an accepted CDK-provider-framework exception |
| Alarm passes count/threshold but watches no real metric (tautology) | — | — | RESOLVED: each SLO row carries a metric contract; alarms bound to that metric; test asserts full Namespace/Metric/Statistic/Period/Eval/Comparator binding |
| Sentinel tool-calls game the CHECK | — | — | RESOLVED: no sentinel; owner CHECK-intent ruling — tool_calls present, non-empty only where a tool exists |
| Hand-authored fixture self-certifies | — | — | RESOLVED: live-recorder-only + provenance + per-span sha256; offline test recomputes (hand-edit fails) |
| Over-aggressive PAN regex hides legit IDs | LOW | MED | Luhn + boundary; anti-over-redaction regression test for non-Luhn 16-digit + request ids |
| CrewAI callback signature varies by version | MED | MED | callbacks accept `*args,**kwargs`, defensive extract; offline fixture is the gate's source of truth |
| SLOs.md path unresolved from the stack at synth | MED | MED | anchor to repo root via `pathlib.Path(__file__)`; parser fail-closes |
| cfn-lint E3006 on a custom resource | LOW | LOW | region-scope `-r us-east-1`; document like Phase-4 if it appears |
| Touching Phase-2/3 frozen surface | LOW | HIGH | tracing is NEW; crew.py additive only; explicit NOT-building + acceptance check |

## Notes
- **Phase-gate deviation (deliberate):** the prp-plan "set PRD Status →
  in-progress" step is skipped — the `complete` chokepoint is the sole
  PRD authority; gate state already tracks this phase (`init`, base
  `0c6399d`).
- **Owner CHECK-intent ruling (2026-05-17), recorded:** the tracing
  CHECK's "each with non-empty … tool-call list" is read as: every span
  has input, output, and a `tool_calls` field PRESENT and faithfully
  captured; **non-empty is required only for agents that actually
  invoke a tool** (the researcher — the sole tool-bearing agent in
  `crew.py`). `report_writer`/`solution_designer` legitimately have an
  empty-but-present list. NO sentinel entries. The PRD CHECK text is
  unchanged (interpretation, not amendment). This closes the
  reviewer-flagged "gaming the CHECK" concern honestly.
- **Revised after adversarial plan review** (codex REVISE 1 BLOCKER/4
  MAJOR + code-reviewer BLOCKER/2 MAJOR): redaction now covers the
  Bedrock-logging path (content delivery OFF), the provider-Lambda
  wildcard is accounted/tested/documented, alarms are semantically
  metric-bound, the fixture is provenance/hash-bound, PAN regex is
  Luhn/boundary, "Steps" framing renamed. No threshold/CHECK/fixture/
  gold weakened.
- Single source of truth = `docs/SLOs.md`; the stack DERIVES alarms
  from it AND binds each to a real metric, so the cross-check proves a
  semantic binding, not a threshold tautology.
- Bedrock model-invocation logging has no native CFN resource (verified
  current AWS docs); the `AwsCustomResource` decision is recorded in
  `infra/README.md` exactly like the Phase-4 AgentCore decision.
- Confidence: **7/10** one-pass — dual-path redaction, semantic
  alarm binding, provenance fixture, and provider-framework IAM
  accounting are now fully specified; residual risk is CrewAI callback
  shape (mitigated: offline fixture authoritative) and exact cfn-guard
  behavior on a custom resource (mitigated: PRD-sanctioned justified
  path).
