"""Synth-time security and cost invariants for the knowledge-base stack.

These run at synth (no AWS calls) and are the canonical assertion
pattern the other stack tests mirror. The OpenSearch-count check is a
deliberate regression guard: spec section 3.1 rejected OpenSearch
Serverless on idle cost, so its presence is a failure, not an option.
"""
import aws_cdk as cdk
from aws_cdk.assertions import Template, Match

from stacks.kb_stack import ComplianceKbStack


def _template() -> Template:
    app = cdk.App()
    stack = ComplianceKbStack(app, "TestKb")
    return Template.from_stack(stack)


def test_corpus_bucket_is_versioned():
    _template().has_resource_properties(
        "AWS::S3::Bucket",
        {"VersioningConfiguration": {"Status": "Enabled"}},
    )


def test_corpus_bucket_uses_kms_encryption():
    t = _template()
    # At least one bucket encrypts with aws:kms (the corpus).
    buckets = t.find_resources("AWS::S3::Bucket")
    kms_buckets = [
        b
        for b in buckets.values()
        for rule in b["Properties"]
        .get("BucketEncryption", {})
        .get("ServerSideEncryptionConfiguration", [])
        if rule.get("ServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
        == "aws:kms"
    ]
    assert kms_buckets, "expected the corpus bucket to use aws:kms encryption"


def test_kms_key_rotates():
    _template().has_resource_properties(
        "AWS::KMS::Key", {"EnableKeyRotation": True}
    )


def test_all_buckets_block_public_access():
    t = _template()
    for logical_id, bucket in t.find_resources("AWS::S3::Bucket").items():
        cfg = bucket["Properties"].get("PublicAccessBlockConfiguration")
        assert cfg == {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        }, f"{logical_id} does not fully block public access"


def test_no_opensearch_serverless_regression():
    # Spec section 3.1: OpenSearch Serverless was rejected on idle
    # cost. If it ever appears, the wrong vector store was wired.
    _template().resource_count_is(
        "AWS::OpenSearchServerless::Collection", 0
    )


def test_buckets_enforce_tls():
    # enforce_ssl adds a deny-non-TLS bucket policy; every bucket
    # must have one.
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
