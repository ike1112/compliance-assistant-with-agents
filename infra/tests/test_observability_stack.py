"""Synth-time contract for the observability stack.

Cross-checks the synthesized template against docs/SLOs.md (the single
source of truth): exactly one alarm per SLO, each bound to the SLO's
real metric (namespace/metric/statistic/period/eval/comparator) with
its threshold — a semantic binding, not a threshold-only tautology.
Also asserts the Bedrock model-invocation-logging custom resource
delivers NO raw content, and the IAM-wildcard accounting (one inline
account-level Bedrock-logging wildcard; the only managed policy is the
CDK provider framework's AWSLambdaBasicExecutionRole).
"""
import json

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from stacks.observability_stack import ComplianceObservabilityStack
from stacks.slo_contract import SLOS_MD, parse_slos


def _template() -> Template:
    return Template.from_stack(
        ComplianceObservabilityStack(cdk.App(), "TestObs")
    )


def _as_list(v):
    return v if isinstance(v, list) else [v]


def _join_literal(create) -> str:
    """Reconstruct the literal text of a Fn::Join Create payload
    (ignoring the Ref/GetAtt parts — we only assert on literals)."""
    if isinstance(create, str):
        return create
    parts = create["Fn::Join"][1]
    return "".join(p for p in parts if isinstance(p, str))


def test_one_alarm_per_slo_semantically_bound():
    slos = parse_slos(SLOS_MD)
    t = _template()
    t.resource_count_is("AWS::CloudWatch::Alarm", len(slos))
    alarms = [
        r["Properties"]
        for r in t.find_resources("AWS::CloudWatch::Alarm").values()
    ]
    # Match each SLO to its alarm by (metric, statistic) — several SLOs
    # share a metric (p50 vs p95), so the statistic disambiguates.
    for slo in slos:
        cands = [
            p for p in alarms
            if p.get("Namespace") == slo.namespace
            and p.get("MetricName") == slo.metric
            and (p.get("ExtendedStatistic") == slo.statistic
                 or p.get("Statistic") == slo.statistic)
        ]
        assert len(cands) == 1, (
            f"{slo.slo_id}: expected exactly one alarm bound to "
            f"{slo.namespace}/{slo.metric}/{slo.statistic}, got {len(cands)}"
        )
        p = cands[0]
        assert p["Period"] == slo.period_s, slo.slo_id
        assert p["EvaluationPeriods"] == slo.eval_periods, slo.slo_id
        assert p["ComparisonOperator"] == slo.comparison_operator, slo.slo_id
        assert float(p["Threshold"]) == slo.threshold, slo.slo_id


def test_dashboard_present():
    _template().resource_count_is("AWS::CloudWatch::Dashboard", 1)


def test_notification_topic_present_and_every_slo_alarm_has_an_action():
    t = _template()
    t.resource_count_is("AWS::SNS::Topic", 1)
    topic_arn_refs = json.dumps(t.find_resources("AWS::SNS::Topic"))
    for alarm in t.find_resources("AWS::CloudWatch::Alarm").values():
        actions = alarm["Properties"].get("AlarmActions") or []
        assert actions, "every SLO alarm must publish to SNS"
        assert any("NotificationTopic" in json.dumps(a) for a in actions), (
            f"alarm actions must target the shared notification topic, got {actions}"
        )
    assert "NotificationTopic" in topic_arn_refs


def test_log_group_present_with_retention():
    t = _template()
    t.resource_count_is("AWS::Logs::LogGroup", 1)
    lg = list(t.find_resources("AWS::Logs::LogGroup").values())[0]
    assert lg["Properties"].get("RetentionInDays"), "log group must retain"
    assert lg["DeletionPolicy"] == "Retain"


def test_optional_email_subscription_is_wired_when_configured():
    app = cdk.App(context={"alarmEmail": "alerts@example.com"})
    t = Template.from_stack(ComplianceObservabilityStack(app, "TestObsEmail"))
    subs = list(t.find_resources("AWS::SNS::Subscription").values())
    assert len(subs) == 1
    props = subs[0]["Properties"]
    assert props["Protocol"] == "email"
    assert props["Endpoint"] == "alerts@example.com"


def test_bedrock_logging_present_with_no_raw_content_delivery():
    t = _template()
    cr = t.find_resources("Custom::AWS")
    assert len(cr) == 1, "expected the Bedrock-logging custom resource"
    props = list(cr.values())[0]["Properties"]
    create = _join_literal(props["Create"])
    assert '"action":"putModelInvocationLoggingConfiguration"' in create
    on_delete = _join_literal(props["Delete"])
    assert "deleteModelInvocationLoggingConfiguration" in on_delete
    # PAN-safety by construction: NO raw text/image/embedding/video.
    for flag in (
        "textDataDeliveryEnabled",
        "imageDataDeliveryEnabled",
        "embeddingDataDeliveryEnabled",
        "videoDataDeliveryEnabled",
    ):
        assert f'"{flag}":false' in create, f"{flag} must be false"


def test_sole_inline_wildcard_is_the_justified_bedrock_logging_op():
    t = _template()
    wild = []
    for pol in t.find_resources("AWS::IAM::Policy").values():
        for st in pol["Properties"]["PolicyDocument"]["Statement"]:
            if st.get("Resource") == "*":
                wild.append(st)
    assert len(wild) == 1, (
        f"expected exactly one inline Resource:'*' statement, got {wild}"
    )
    assert set(_as_list(wild[0]["Action"])) == {
        "bedrock:PutModelInvocationLoggingConfiguration",
        "bedrock:DeleteModelInvocationLoggingConfiguration",
    }, wild[0]["Action"]


def test_only_managed_policy_is_the_cdk_provider_framework_basic_exec():
    # The AwsCustomResource provider framework attaches the AWS-managed
    # AWSLambdaBasicExecutionRole (logs-only) to its singleton Lambda
    # role. Assert that is the ONLY managed policy anywhere — no broad
    # managed policy slips in (documented in infra/README.md).
    t = _template()
    seen = []
    for role in t.find_resources("AWS::IAM::Role").values():
        for mp in role["Properties"].get("ManagedPolicyArns", []) or []:
            seen.append(json.dumps(mp))
    assert len(seen) == 1, f"expected exactly one managed policy, got {seen}"
    assert "AWSLambdaBasicExecutionRole" in seen[0], seen[0]


def test_malformed_slos_fails_closed(tmp_path):
    bad = tmp_path / "SLOs.md"
    bad.write_text("# no table here\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ComplianceObservabilityStack(
            cdk.App(), "TestObsBad", slos_path=str(bad)
        )
