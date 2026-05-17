"""Runtime image registry: the ECR repo, split out so it deploys first.

`AWS::BedrockAgentCore::Runtime` fails if it is created against an
image URI that has not been pushed yet. The repository therefore lives
in its own stack, deployed before `ComplianceRuntimeStack`, so the
operator can build and push the linux/arm64 crew image into it in
between. The repository name is deterministic so the push target is
knowable from account + region without first reading any stack output.
"""
import aws_cdk as cdk
from aws_cdk import aws_ecr as ecr
from constructs import Construct

# Deterministic so the operator's push target is
# <account>.dkr.ecr.<region>.amazonaws.com/<this>:<tag> without needing
# a stack output. ECR names are lowercase [a-z0-9-_/.].
RUNTIME_REPO_NAME = "compliance-assistant-runtime"


class ComplianceRuntimeEcrStack(cdk.Stack):
    """The ECR repository the AgentCore Runtime pulls the crew image from."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # R-RT-ECR. Immutable tags so a deployed runtime's image
        # provenance cannot be silently overwritten; scan on push;
        # RETAIN so tearing down the runtime never drops the audited
        # image. Empty-on-delete off for the same reason.
        self.repository = ecr.Repository(
            self,
            "RuntimeRepo",
            repository_name=RUNTIME_REPO_NAME,
            image_scan_on_push=True,
            image_tag_mutability=ecr.TagMutability.IMMUTABLE,
            empty_on_delete=False,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        cdk.CfnOutput(
            self, "RuntimeRepoUri", value=self.repository.repository_uri
        )
        cdk.CfnOutput(
            self, "RuntimeRepoName", value=self.repository.repository_name
        )
