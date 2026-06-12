"""Knowledge-base stack: the data-bearing, slow-to-recreate resources.

Holds the encryption key, the corpus + access-log buckets, the Aurora
Serverless v2 pgvector store, and (added next) the Bedrock Knowledge
Base and ingestion path. `knowledge_base` stays None until it exists,
so the agent stack can be wired by reference without a circular import.

The Aurora vector store is built from native CDK resources rather than
the gen-ai-cdk-constructs helper: that helper requires a running
Docker daemon at synth and cannot set Serverless v2 min capacity to 0.
Spec section 3.1 locked Aurora pgvector specifically for its
scale-to-zero idle cost, so we build the cluster directly to control
capacity and bootstrap pgvector over the RDS Data API (no Docker, no
driver, no in-VPC Lambda).
"""
import pathlib

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    aws_bedrock as bedrock,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_ec2 as ec2,
    aws_events as events,
    aws_events_targets as events_targets,
    aws_iam as iam,
    aws_kms as kms,
    aws_lambda as lambda_,
    aws_lambda_destinations as lambda_destinations,
    aws_rds as rds,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sns as sns,
    aws_sqs as sqs,
    triggers,
)
from constructs import Construct

# Titan Text Embeddings v2 produces 1024-dim vectors. The table's
# vector column and the Knowledge Base embedding model must agree.
_TITAN_V2_DIMS = 1024

# The table contract Bedrock expects for an RDS (Aurora pgvector)
# vector store. Kept here so the bootstrap DDL and the Knowledge Base
# rdsConfiguration (next step) reference one definition.
PGVECTOR_SCHEMA = "bedrock_integration"
PGVECTOR_TABLE = "bedrock_kb"
PGVECTOR_PK = "id"
PGVECTOR_VECTOR_FIELD = "embedding"
PGVECTOR_TEXT_FIELD = "chunks"
PGVECTOR_METADATA_FIELD = "metadata"
PGVECTOR_DB = "kb"

# Asset paths are anchored to this module, not the process cwd, so
# `cdk` (run from infra/) and pytest (run from the repo root) both
# resolve the Lambda source.
_INGEST_ASSET = str(
    (pathlib.Path(__file__).parent.parent / "lambdas" / "ingest").resolve()
)

# Each statement runs on its own (the Data API takes one statement per
# call). All are IF NOT EXISTS so the bootstrap is safe to re-run.
_BOOTSTRAP_SQL = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    f"CREATE SCHEMA IF NOT EXISTS {PGVECTOR_SCHEMA}",
    (
        f"CREATE TABLE IF NOT EXISTS {PGVECTOR_SCHEMA}.{PGVECTOR_TABLE} ("
        f"{PGVECTOR_PK} uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        f"{PGVECTOR_VECTOR_FIELD} vector({_TITAN_V2_DIMS}), "
        f"{PGVECTOR_TEXT_FIELD} text, "
        f"{PGVECTOR_METADATA_FIELD} json, "
        f"custom_metadata jsonb)"
    ),
    (
        f"CREATE INDEX IF NOT EXISTS bedrock_kb_embedding_idx ON "
        f"{PGVECTOR_SCHEMA}.{PGVECTOR_TABLE} USING hnsw "
        f"({PGVECTOR_VECTOR_FIELD} vector_cosine_ops)"
    ),
    (
        f"CREATE INDEX IF NOT EXISTS bedrock_kb_chunks_fts_idx ON "
        f"{PGVECTOR_SCHEMA}.{PGVECTOR_TABLE} USING gin "
        f"(to_tsvector('simple', {PGVECTOR_TEXT_FIELD}))"
    ),
    (
        f"CREATE INDEX IF NOT EXISTS bedrock_kb_custom_md_idx ON "
        f"{PGVECTOR_SCHEMA}.{PGVECTOR_TABLE} USING gin (custom_metadata)"
    ),
]

_BOOTSTRAP_CODE = '''
import json, os, boto3

rds = boto3.client("rds-data")
STATEMENTS = json.loads(os.environ["STATEMENTS"])

def handler(event, context):
    # Runs once after the cluster exists (triggers.TriggerFunction).
    # Every statement is idempotent, so a re-run is harmless.
    for sql in STATEMENTS:
        rds.execute_statement(
            resourceArn=os.environ["CLUSTER_ARN"],
            secretArn=os.environ["SECRET_ARN"],
            database=os.environ["DB_NAME"],
            sql=sql,
        )
    return {"statements": len(STATEMENTS)}
'''


class ComplianceKbStack(cdk.Stack):
    """Corpus, encryption, vector store, and the Bedrock Knowledge Base."""

    def __init__(self, scope: Construct, construct_id: str, *,
                 notification_topic: sns.ITopic | None = None,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # R-KMS. One customer-managed key for the corpus and (later)
        # the report bucket. Rotation on so a long-lived key still
        # re-keys yearly without us tracking it.
        self.corpus_key = kms.Key(
            self,
            "CorpusKey",
            enable_key_rotation=True,
            alias="alias/compliance-corpus",
            description="Encrypts the compliance regulatory-PDF corpus",
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # Where S3 writes server access logs. Kept separate from the
        # corpus so the audit trail can't be tampered with by a write
        # to the corpus itself. OBJECT_WRITER ownership because S3 log
        # delivery writes with the LogDeliveryWrite ACL, which the
        # bucket-owner-enforced setting would reject.
        access_logs = s3.Bucket(
            self,
            "AccessLogs",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # R-S3-CORPUS. The bucket *is* the compliance evidence trail
        # (spec section 3.1): versioned so a replaced PDF never loses
        # the version that grounded an earlier report, customer-KMS
        # encrypted, TLS-only, never public, and access-logged. RETAIN
        # so deleting the stack can never destroy regulatory evidence.
        self.corpus_bucket = s3.Bucket(
            self,
            "Corpus",
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.corpus_key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            server_access_logs_bucket=access_logs,
            server_access_logs_prefix="corpus/",
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # VPC for the vector store. No NAT gateways: the Knowledge Base
        # reaches Aurora inside the VPC and nothing here needs egress
        # to the internet, so a NAT would be pure idle cost.
        self.vpc = ec2.Vpc(
            self,
            "KbVpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                )
            ],
        )

        # R-AURORA-VEC. Aurora PostgreSQL Serverless v2, min capacity
        # 0 ACU so it pauses to ~zero cost between report runs — the
        # whole reason Aurora beat OpenSearch Serverless here (spec
        # section 3.1, locked; do not relitigate). Storage encrypted
        # with the corpus key. Data API on so the pgvector bootstrap
        # needs no driver and no in-VPC Lambda.
        self.db_cluster = rds.DatabaseCluster(
            self,
            "VectorDb",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_6
            ),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            serverless_v2_min_capacity=0,
            serverless_v2_max_capacity=4,
            writer=rds.ClusterInstance.serverless_v2("writer"),
            credentials=rds.Credentials.from_generated_secret(
                "kbadmin", secret_name="compliance/kb-aurora"
            ),
            default_database_name=PGVECTOR_DB,
            storage_encrypted=True,
            storage_encryption_key=self.corpus_key,
            enable_data_api=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        self.db_secret = self.db_cluster.secret

        # Bootstrap pgvector once the cluster exists. Runs OUT of the
        # VPC (the RDS Data API is a regional AWS endpoint reachable
        # from a normal Lambda), inline code so synth needs no Docker.
        bootstrap = triggers.TriggerFunction(
            self,
            "PgvectorBootstrap",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_inline(_BOOTSTRAP_CODE),
            timeout=Duration.minutes(5),
            environment={
                "CLUSTER_ARN": self.db_cluster.cluster_arn,
                "SECRET_ARN": self.db_secret.secret_arn,
                "DB_NAME": PGVECTOR_DB,
                "STATEMENTS": cdk.Stack.of(self).to_json_string(
                    _BOOTSTRAP_SQL
                ),
            },
            execute_after=[self.db_cluster],
        )
        # grant_data_api_access wires rds-data:* on the cluster and
        # secret read on the generated secret — no wildcard policy.
        self.db_cluster.grant_data_api_access(bootstrap)

        # The embedding model the Knowledge Base uses. Comes from CDK
        # context so the RAG-eval sub-project can change it without a
        # code edit (spec section 3.1). Titan v2 -> 1024 dims, which
        # must match the vector() column above.
        embedding_model = self.node.try_get_context("embeddingModel") or (
            "amazon.titan-embed-text-v2:0"
        )
        embedding_model_arn = (
            f"arn:aws:bedrock:{self.region}::foundation-model/"
            f"{embedding_model}"
        )

        # Service role the Bedrock Knowledge Base assumes. Scoped to
        # exactly what RDS-backed ingestion/query needs: invoke the
        # embedding model, talk to this cluster over the Data API,
        # read its secret, and read the (KMS-encrypted) corpus. The
        # SourceAccount condition blocks the confused-deputy case.
        self.kb_role = iam.Role(
            self,
            "KbRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account}
                },
            ),
            description="Bedrock Knowledge Base service role",
        )
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[embedding_model_arn],
            )
        )
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "rds-data:ExecuteStatement",
                    "rds-data:BatchExecuteStatement",
                ],
                resources=[self.db_cluster.cluster_arn],
            )
        )
        self.db_secret.grant_read(self.kb_role)
        self.corpus_bucket.grant_read(self.kb_role)
        self.corpus_key.grant_decrypt(self.kb_role)

        # R-KB. The Knowledge Base itself, backed by the Aurora
        # pgvector store. Raw L1 (the gen-ai-cdk-constructs equivalent
        # needs Docker at synth, see module docstring). field_mapping
        # mirrors the columns the bootstrap DDL created.
        self.knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "KnowledgeBase",
            name="compliance-knowledge-base",
            role_arn=self.kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=embedding_model_arn
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="RDS",
                rds_configuration=bedrock.CfnKnowledgeBase.RdsConfigurationProperty(
                    resource_arn=self.db_cluster.cluster_arn,
                    credentials_secret_arn=self.db_secret.secret_arn,
                    database_name=PGVECTOR_DB,
                    table_name=f"{PGVECTOR_SCHEMA}.{PGVECTOR_TABLE}",
                    field_mapping=bedrock.CfnKnowledgeBase.RdsFieldMappingProperty(
                        primary_key_field=PGVECTOR_PK,
                        vector_field=PGVECTOR_VECTOR_FIELD,
                        text_field=PGVECTOR_TEXT_FIELD,
                        metadata_field=PGVECTOR_METADATA_FIELD,
                    ),
                ),
            ),
        )
        # The table must exist before the KB validates its store, and
        # the cluster before that. Order both explicitly.
        self.knowledge_base.node.add_dependency(self.db_cluster)
        self.knowledge_base.node.add_dependency(bootstrap)

        # R-KB-DS. The corpus bucket as the KB's data source. Chunking
        # comes from CDK context, not a literal: spec section 3.1 makes
        # the real value an eval-driven decision owned by the RAG-eval
        # sub-project, so it stays a config knob here. RETAIN deletion
        # policy so dropping the data source never wipes the vectors
        # that grounded an audited report.
        chunk_strategy = self.node.try_get_context("chunkingStrategy") or (
            "FIXED_SIZE"
        )
        # This stack only emits a fixed-size chunking configuration, so a
        # non-FIXED_SIZE context value would synthesize a data source
        # whose declared strategy does not match its configuration. Fail
        # synth loudly rather than deploy a mislabeled chunker. The RAG
        # eval harness enforces the same deploy-equivalence invariant.
        if chunk_strategy != "FIXED_SIZE":
            raise ValueError(
                f"chunkingStrategy={chunk_strategy!r} unsupported: this "
                "stack emits only FIXED_SIZE chunking. Extend the data "
                "source before selecting another strategy."
            )
        chunk_max_tokens = int(
            self.node.try_get_context("chunkMaxTokens") or 512
        )
        chunk_overlap = int(
            self.node.try_get_context("chunkOverlapPercent") or 20
        )
        data_source = bedrock.CfnDataSource(
            self,
            "CorpusDataSource",
            name="compliance-corpus",
            knowledge_base_id=self.knowledge_base.attr_knowledge_base_id,
            data_deletion_policy="RETAIN",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=self.corpus_bucket.bucket_arn
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy=chunk_strategy,
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=chunk_max_tokens,
                        overlap_percentage=chunk_overlap,
                    ),
                )
            ),
        )

        ingest_dlq = sqs.Queue(
            self,
            "IngestDlq",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            retention_period=Duration.days(14),
        )
        # Re-index when a PDF is uploaded. Inline-dir asset (zipped,
        # not Docker-built). IAM scoped to StartIngestionJob on this
        # KB only — no wildcard.
        ingest_fn = lambda_.Function(
            self,
            "IngestFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(_INGEST_ASSET),
            timeout=Duration.minutes(1),
            environment={
                "KB_ID": self.knowledge_base.attr_knowledge_base_id,
                "DATA_SOURCE_ID": data_source.attr_data_source_id,
            },
            dead_letter_queue=ingest_dlq,
        )
        lambda_.EventInvokeConfig(
            self,
            "IngestFnInvokeConfig",
            function=ingest_fn,
            max_event_age=Duration.hours(6),
            retry_attempts=2,
            on_failure=lambda_destinations.SqsDestination(ingest_dlq),
        )
        ingest_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:StartIngestionJob"],
                resources=[self.knowledge_base.attr_knowledge_base_arn],
            )
        )
        self.corpus_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(ingest_fn),
        )

        ingest_error_alarm = cloudwatch.Alarm(
            self,
            "IngestLambdaErrorsAlarm",
            alarm_name="compliance-ingest-lambda-errors",
            alarm_description="The ingest Lambda raised an error.",
            metric=ingest_fn.metric_errors(
                period=Duration.minutes(5), statistic="sum"
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        ingest_dlq_alarm = cloudwatch.Alarm(
            self,
            "IngestDlqDepthAlarm",
            alarm_name="compliance-ingest-dlq-depth",
            alarm_description="The ingest Lambda dead-letter queue is non-empty.",
            metric=ingest_dlq.metric_approximate_number_of_messages_visible(
                period=Duration.minutes(5), statistic="Average"
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        if notification_topic is not None:
            action = cloudwatch_actions.SnsAction(notification_topic)
            ingest_error_alarm.add_alarm_action(action)
            ingest_dlq_alarm.add_alarm_action(action)

            events.Rule(
                self,
                "IngestionJobFailureRule",
                description="Notify when a Bedrock KB ingestion job fails or stops.",
                event_pattern=events.EventPattern(
                    source=["aws.bedrock"],
                    detail={
                        "knowledgeBaseId": [self.knowledge_base.attr_knowledge_base_id],
                        "dataSourceId": [data_source.attr_data_source_id],
                        "status": ["FAILED", "STOPPED"],
                    },
                ),
                targets=[events_targets.SnsTopic(notification_topic)],
            )

        cdk.CfnOutput(self, "CorpusBucketName", value=self.corpus_bucket.bucket_name)
        cdk.CfnOutput(
            self,
            "KnowledgeBaseId",
            value=self.knowledge_base.attr_knowledge_base_id,
        )
