"""Synth-time security and cost invariants for the knowledge-base stack.

These run at synth (no AWS calls) and are the canonical assertion
pattern the other stack tests mirror. The OpenSearch-count check is a
deliberate regression guard: spec section 3.1 rejected OpenSearch
Serverless on idle cost, so its presence is a failure, not an option.
"""
import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template, Match

from stacks.kb_stack import ComplianceKbStack
from stacks.observability_stack import ComplianceObservabilityStack


def _template() -> Template:
    app = cdk.App()
    obs = ComplianceObservabilityStack(app, "TestObs")
    stack = ComplianceKbStack(app, "TestKb", notification_topic=obs.notification_topic)
    return Template.from_stack(stack)


def test_non_fixed_size_chunking_strategy_is_rejected():
    # This stack emits only fixed_size_chunking_configuration; a
    # non-FIXED_SIZE context value must fail synth, not deploy a
    # mislabeled chunker (deploy-equivalence invariant the RAG eval
    # harness relies on).
    app = cdk.App(context={"chunkingStrategy": "HIERARCHICAL"})
    with pytest.raises(ValueError, match="unsupported"):
        ComplianceKbStack(app, "TestKbBadChunk")


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


def test_aurora_is_serverless_v2_zero_min_capacity():
    # Spec section 3.1: the whole reason Aurora beat OpenSearch
    # Serverless is scale-to-zero. MinCapacity must be 0.
    _template().has_resource_properties(
        "AWS::RDS::DBCluster",
        {
            "ServerlessV2ScalingConfiguration": Match.object_like(
                {"MinCapacity": 0}
            )
        },
    )


def test_aurora_data_api_enabled():
    # Data API is how pgvector is bootstrapped without a driver or an
    # in-VPC Lambda.
    _template().has_resource_properties(
        "AWS::RDS::DBCluster", {"EnableHttpEndpoint": True}
    )


def test_aurora_storage_encrypted():
    _template().has_resource_properties(
        "AWS::RDS::DBCluster", {"StorageEncrypted": True}
    )


def test_knowledge_base_is_rds_backed():
    t = _template()
    t.resource_count_is("AWS::Bedrock::KnowledgeBase", 1)
    t.has_resource_properties(
        "AWS::Bedrock::KnowledgeBase",
        {
            "StorageConfiguration": Match.object_like({"Type": "RDS"}),
            "KnowledgeBaseConfiguration": Match.object_like(
                {"Type": "VECTOR"}
            ),
        },
    )


def test_s3_data_source_with_configurable_chunking():
    t = _template()
    t.resource_count_is("AWS::Bedrock::DataSource", 1)
    t.has_resource_properties(
        "AWS::Bedrock::DataSource",
        {
            "DataSourceConfiguration": Match.object_like({"Type": "S3"}),
            "VectorIngestionConfiguration": Match.object_like(
                {
                    "ChunkingConfiguration": Match.object_like(
                        {"ChunkingStrategy": "FIXED_SIZE"}
                    )
                }
            ),
        },
    )


def test_kb_role_has_no_wildcard_resources():
    # Every KB-role policy statement must name a concrete resource —
    # a Resource:"*" here is the top cfn-guard finding.
    t = _template()
    for pol in t.find_resources("AWS::IAM::Policy").values():
        for stmt in pol["Properties"]["PolicyDocument"]["Statement"]:
            assert stmt.get("Resource") != "*", "wildcard resource in IAM policy"


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


def test_ingest_lambda_has_dlq_and_async_failure_config():
    t = _template()
    t.resource_count_is("AWS::SQS::Queue", 1)
    t.resource_count_is("AWS::Lambda::EventInvokeConfig", 1)
    cfg = list(t.find_resources("AWS::Lambda::EventInvokeConfig").values())[0]
    dest = cfg["Properties"]["DestinationConfig"]["OnFailure"]["Destination"]
    assert "IngestDlq" in str(dest), dest


def test_ingest_failure_alarms_publish_to_notification_topic():
    t = _template()
    alarms = [
        r["Properties"]
        for r in t.find_resources("AWS::CloudWatch::Alarm").values()
    ]
    names = {a["AlarmName"] for a in alarms}
    assert "compliance-ingest-lambda-errors" in names
    assert "compliance-ingest-dlq-depth" in names
    for alarm in alarms:
        actions = alarm.get("AlarmActions") or []
        assert actions, f"{alarm['AlarmName']}: missing alarm action"
        assert any("NotificationTopic" in str(a) for a in actions), actions


def test_ingestion_job_failure_event_rule_targets_notification_topic():
    t = _template()
    rules = list(t.find_resources("AWS::Events::Rule").values())
    assert len(rules) == 1
    props = rules[0]["Properties"]
    pattern = str(props["EventPattern"])
    assert "aws.bedrock" in pattern
    assert "knowledgeBaseId" in pattern
    assert "dataSourceId" in pattern
    assert "FAILED" in pattern or "STOPPED" in pattern
    targets = props["Targets"]
    assert len(targets) == 1
    assert "NotificationTopic" in str(targets[0]["Arn"])
