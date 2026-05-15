"""Knowledge-base stack: the data-bearing, slow-to-recreate resources.

Built up across several steps. Right now it holds the encryption key
and the two buckets (the regulatory-PDF corpus and its access log).
The Aurora vector store, the Knowledge Base, and the ingestion path
are added next. `knowledge_base` stays None until it exists, so the
agent stack can be wired by reference without a circular import.
"""
from typing import Optional

import aws_cdk as cdk
from aws_cdk import (
    aws_kms as kms,
    aws_s3 as s3,
)
from constructs import Construct


class ComplianceKbStack(cdk.Stack):
    """Corpus, encryption, vector store, and the Bedrock Knowledge Base."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # R-KMS. One customer-managed key for the corpus and (later) the
        # report bucket. Rotation on so a long-lived key still re-keys
        # yearly without us tracking it.
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
        # to the corpus itself. S3-managed encryption (a KMS key here
        # would force every log delivery through KMS and is overkill
        # for access logs). OBJECT_WRITER ownership because S3 log
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

        # Filled in once the Knowledge Base exists. The agent stack
        # takes this by reference; None here keeps synth working while
        # the stack is still being built up.
        self.knowledge_base: Optional[Construct] = None

        cdk.CfnOutput(self, "CorpusBucketName", value=self.corpus_bucket.bucket_name)
