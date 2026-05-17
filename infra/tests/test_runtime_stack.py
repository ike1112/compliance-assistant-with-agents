"""Synth-time contract for the runtime stack. Mirrors test_kb_stack.py.

These run at synth (no AWS calls). The wildcard test is a real guard,
not a rubber stamp: it asserts the SOLE literal Resource:"*" statement
is exactly the AWS-documented account-level ecr:GetAuthorizationToken
token op — any other wildcard fails.
"""
import json

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template, Match

from stacks.runtime_stack import (
    ComplianceRuntimeStack,
    _MAX_LIFETIME_CEIL,
)
from stacks.runtime_ecr_stack import ComplianceRuntimeEcrStack


def _runtime(app: cdk.App) -> ComplianceRuntimeStack:
    # The ECR repo lives in its own stack (deployed first so the image
    # is pushable before the runtime is created against it); the runtime
    # stack imports it by reference.
    ecr_stack = ComplianceRuntimeEcrStack(app, "TestRtEcr")
    return ComplianceRuntimeStack(
        app, "TestRt", ecr_repository=ecr_stack.repository
    )


def _template(context: dict | None = None) -> Template:
    app = cdk.App(context=context or {})
    return Template.from_stack(_runtime(app))


def _iam_statements(t: Template) -> list[dict]:
    stmts: list[dict] = []
    for pol in t.find_resources("AWS::IAM::Policy").values():
        stmts.extend(pol["Properties"]["PolicyDocument"]["Statement"])
    return stmts


def _as_list(v) -> list:
    return v if isinstance(v, list) else [v]


def test_agentcore_runtime_present_and_shaped():
    t = _template()
    t.resource_count_is("AWS::BedrockAgentCore::Runtime", 1)
    t.has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        Match.object_like(
            {
                "ProtocolConfiguration": "HTTP",
                "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
                "AgentRuntimeName": "compliance_assistant_runtime",
            }
        ),
    )


def test_runtime_max_lifetime_is_context_driven_not_hardcoded():
    # Default (no context) yields the AWS-documented 8h ceiling...
    _template().has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        Match.object_like(
            {"LifecycleConfiguration": {"MaxLifetime": _MAX_LIFETIME_CEIL}}
        ),
    )
    # ...and a context override actually changes it (proves it is not a
    # hardcoded literal — the M-003 guard).
    _template({"runtimeMaxLifetimeSeconds": 3600}).has_resource_properties(
        "AWS::BedrockAgentCore::Runtime",
        Match.object_like(
            {"LifecycleConfiguration": {"MaxLifetime": 3600}}
        ),
    )


def test_out_of_range_max_lifetime_is_rejected():
    # Mirrors test_kb_stack's context->ValueError guard: an out-of-range
    # value must fail synth, not synthesize a value the service rejects.
    app = cdk.App(context={"runtimeMaxLifetimeSeconds": 30})
    ecr_stack = ComplianceRuntimeEcrStack(app, "TestRtBadEcr")
    with pytest.raises(ValueError, match="out of range"):
        ComplianceRuntimeStack(
            app, "TestRtBadLifetime", ecr_repository=ecr_stack.repository
        )


def test_report_bucket_versioned_kms_blockpublic():
    t = _template()
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {"VersioningConfiguration": {"Status": "Enabled"}},
    )
    for logical_id, bucket in t.find_resources("AWS::S3::Bucket").items():
        cfg = bucket["Properties"].get("PublicAccessBlockConfiguration")
        assert cfg == {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        }, f"{logical_id} does not fully block public access"
    # The report bucket encrypts with aws:kms.
    kms_buckets = [
        b
        for b in t.find_resources("AWS::S3::Bucket").values()
        for rule in b["Properties"]
        .get("BucketEncryption", {})
        .get("ServerSideEncryptionConfiguration", [])
        if rule.get("ServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
        == "aws:kms"
    ]
    assert kms_buckets, "expected the report bucket to use aws:kms"


def test_report_buckets_enforce_tls():
    t = _template()
    policies = t.find_resources("AWS::S3::BucketPolicy")
    assert policies, "expected TLS-enforcing bucket policies"
    for pol in policies.values():
        stmts = pol["Properties"]["PolicyDocument"]["Statement"]
        assert any(
            s.get("Effect") == "Deny"
            and s.get("Condition", {}).get("Bool", {}).get(
                "aws:SecureTransport"
            )
            == "false"
            for s in stmts
        ), "missing deny-non-TLS statement"


def test_kms_key_rotates():
    _template().has_resource_properties(
        "AWS::KMS::Key", {"EnableKeyRotation": True}
    )


def test_runtime_stack_has_no_vpc_or_nat():
    # AgentCore PUBLIC network mode is serverless-managed egress; this
    # stack must create no customer VPC and therefore no NAT (the
    # "no NAT" property the Fargate fallback would otherwise require).
    t = _template()
    t.resource_count_is("AWS::EC2::VPC", 0)
    t.resource_count_is("AWS::EC2::NatGateway", 0)


def test_role_can_invoke_the_bedrock_agent():
    # The crew's researcher calls the deployed Bedrock Agent via
    # crewai_tools BedrockInvokeAgentTool; without this grant every run
    # fails closed at the first tool call.
    stmts = _iam_statements(_template())
    invoke_agent = [
        s for s in stmts if "bedrock:InvokeAgent" in _as_list(s.get("Action"))
    ]
    assert invoke_agent, "runtime role missing bedrock:InvokeAgent"
    # Scoped to an agent-alias ARN (rendered as a Fn::Join over the
    # region/account tokens), never a literal wildcard.
    blob = json.dumps(invoke_agent)
    assert "agent-alias/" in blob
    assert all(s.get("Resource") != "*" for s in invoke_agent)


def test_role_reads_exactly_the_two_agent_id_ssm_params():
    # Bind the parameter ARNs to the ssm:GetParameter statement and
    # assert it is scoped to exactly the two named params — no
    # parameter/compliance-assistant/* prefix wildcard, no Resource:"*".
    ssm_stmts = [
        s for s in _iam_statements(_template())
        if "ssm:GetParameter" in _as_list(s.get("Action"))
    ]
    assert ssm_stmts, "runtime role missing ssm:GetParameter"
    blob = json.dumps(ssm_stmts)
    assert "parameter/compliance-assistant/agent-id" in blob
    assert "parameter/compliance-assistant/agent-alias-id" in blob
    assert "parameter/compliance-assistant/*" not in blob, (
        "SSM grant must not use a prefix wildcard"
    )
    for s in ssm_stmts:
        assert s.get("Resource") != "*", "SSM grant must not be Resource:'*'"


def test_report_write_grant_is_least_privilege():
    # codex F-002: bucket.grant_put expands to PutObjectLegalHold /
    # Retention / VersionTagging / Abort* (+ kms:Decrypt from the bucket
    # grant). The shim only PutObjects small files; the role must carry
    # exactly that and no KMS Decrypt.
    stmts = _iam_statements(_template())
    s3_report = [
        s for s in stmts
        if any(a.startswith("s3:") for a in _as_list(s.get("Action")))
    ]
    assert s3_report, "expected an explicit S3 statement for report writes"
    s3_actions = {a for s in s3_report for a in _as_list(s.get("Action"))}
    assert s3_actions == {"s3:PutObject"}, (
        f"report-write S3 actions must be exactly s3:PutObject, "
        f"got {sorted(s3_actions)}"
    )
    kms_actions = {
        a for s in stmts for a in _as_list(s.get("Action"))
        if isinstance(a, str) and a.startswith("kms:")
    }
    assert "kms:Decrypt" not in kms_actions, (
        f"runtime role must not have kms:Decrypt, got {sorted(kms_actions)}"
    )
    assert kms_actions <= {"kms:Encrypt", "kms:GenerateDataKey"}, (
        f"KMS actions must be the minimal write set, got {sorted(kms_actions)}"
    )


def test_app_wires_stacks_and_runtime_deploy_ordering():
    # Deploy-ordering invariants: the runtime is created against an ECR
    # image (the repo stack must exist + the image be pushed first) and
    # the crew resolves agent ids from SSM at container start (agent
    # stack first). Asserted directly because app.py runs only in the
    # cdk-synth subprocess (not visible to pytest coverage).
    import inspect

    from stacks.kb_stack import ComplianceKbStack
    from stacks.agent_stack import ComplianceAgentStack

    app = cdk.App()
    kb = ComplianceKbStack(app, "ComplianceKbStack")
    agent = ComplianceAgentStack(
        app, "ComplianceAgentStack", knowledge_base=kb.knowledge_base
    )
    ecr_stack = ComplianceRuntimeEcrStack(app, "ComplianceRuntimeEcrStack")
    rt = ComplianceRuntimeStack(
        app, "ComplianceRuntimeStack",
        ecr_repository=ecr_stack.repository,
    )
    rt.add_dependency(ecr_stack)
    rt.add_dependency(agent)
    assert ecr_stack in rt.dependencies, (
        "runtime must depend on the ECR stack (image pushable first)"
    )
    assert agent in rt.dependencies, (
        "runtime must depend on the agent stack (SSM agent ids at "
        "container start)"
    )
    # The ctor takes the ECR repo (a real, used cross-stack ref) and
    # must still NOT carry an unused knowledge_base arg (the crew
    # reaches the KB via bedrock:InvokeAgent, not a cross-stack ref).
    params = inspect.signature(ComplianceRuntimeStack.__init__).parameters
    assert "ecr_repository" in params, (
        "ComplianceRuntimeStack must take the ecr_repository cross-stack ref"
    )
    assert "knowledge_base" not in params, (
        "ComplianceRuntimeStack must not take an unused knowledge_base arg"
    )


def test_sole_wildcard_is_the_justified_ecr_token_op():
    # Not a rubber stamp: there must be exactly ONE statement whose
    # Resource is the literal "*", and its only action must be
    # ecr:GetAuthorizationToken (AWS-documented account-level token op,
    # no resource form). Any other literal wildcard fails here.
    wildcard = [
        s for s in _iam_statements(_template()) if s.get("Resource") == "*"
    ]
    assert len(wildcard) == 1, (
        f"expected exactly one Resource:'*' statement, got {len(wildcard)}: "
        f"{wildcard}"
    )
    assert _as_list(wildcard[0]["Action"]) == ["ecr:GetAuthorizationToken"], (
        f"the only wildcard statement must be ecr:GetAuthorizationToken, "
        f"got {wildcard[0]['Action']!r}"
    )
