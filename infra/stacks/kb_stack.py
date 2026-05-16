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
from typing import Optional

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    aws_ec2 as ec2,
    aws_kms as kms,
    aws_lambda as lambda_,
    aws_rds as rds,
    aws_s3 as s3,
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

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
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

        # Filled in once the Knowledge Base exists. The agent stack
        # takes this by reference; None here keeps synth working while
        # the stack is still being built up.
        self.knowledge_base: Optional[Construct] = None

        cdk.CfnOutput(self, "CorpusBucketName", value=self.corpus_bucket.bucket_name)
