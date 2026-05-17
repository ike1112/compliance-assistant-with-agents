"""Runtime stack: the AgentCore Runtime host for the compliance crew.

Holds the report KMS key + versioned report bucket (durable evidence —
the runtime microVM filesystem is ephemeral), the ECR repository the
operator pushes the crew image to, a least-privilege execution role, and
the `AWS::BedrockAgentCore::Runtime` itself. Separated from the kb/agent
stacks by blast radius: redeploying the runtime never touches the corpus
or the agent.

AgentCore Runtime IaC is mature (GA Oct 2025; first-class CloudFormation;
the L1 `aws_bedrockagentcore.CfnRuntime` ships in the pinned
aws-cdk-lib). Long runs use the async pattern in `runtime/server.py`;
`MaxLifetime` (context-driven, default 8h) is the AWS maximum. The image
build/push and `cdk deploy` are the operator HUMAN-GATE — synth only
references the ECR repo + an image tag, so it stays Docker-free and
offline. See infra/README.md for the AgentCore-vs-Fargate decision.
"""
import aws_cdk as cdk
from aws_cdk import (
    aws_bedrockagentcore as agentcore,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_kms as kms,
    aws_s3 as s3,
)
from constructs import Construct

# AgentCore Runtime LifecycleConfiguration bounds (AWS docs): both
# idleRuntimeSessionTimeout and maxLifetime are 60..28800 seconds; the
# maxLifetime default/maximum is 28800 (8 hours).
_MAX_LIFETIME_FLOOR = 60
_MAX_LIFETIME_CEIL = 28800
# AgentRuntimeName must match ^[a-zA-Z][a-zA-Z0-9_]{0,47}$ (no hyphens).
_RUNTIME_NAME = "compliance_assistant_runtime"


class ComplianceRuntimeStack(cdk.Stack):
    """AgentCore Runtime host + its versioned report bucket and ECR repo.

    Deliberately takes no cross-stack reference: the crew reaches the
    Knowledge Base through the deployed Bedrock Agent (InvokeAgent),
    which the execution role is scoped to by ARN pattern — so this stack
    does not need (and must not carry an unused) `knowledge_base` arg.
    Deploy ordering after the agent stack is enforced in app.py.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # R-RT-KEY. Customer-managed key for the report bucket. Rotation
        # on so a long-lived key re-keys yearly without us tracking it.
        self.report_key = kms.Key(
            self,
            "ReportKey",
            enable_key_rotation=True,
            alias="alias/compliance-report",
            description="Encrypts the compliance crew's report artifacts",
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # Where S3 writes server access logs for the report bucket.
        # OBJECT_WRITER because S3 log delivery writes with the
        # LogDeliveryWrite ACL, which bucket-owner-enforced would reject.
        access_logs = s3.Bucket(
            self,
            "AccessLogs",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # R-RT-REPORT. The crew's report artifacts land here from the
        # ephemeral microVM. Versioned so a re-run never loses the
        # report that grounded an earlier audit, customer-KMS encrypted,
        # TLS-only, never public, access-logged. RETAIN so deleting the
        # stack can never destroy regulatory evidence.
        self.report_bucket = s3.Bucket(
            self,
            "Report",
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.report_key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            server_access_logs_bucket=access_logs,
            server_access_logs_prefix="report/",
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # R-RT-ECR. The operator builds the linux/arm64 crew image
        # (infra/runtime/Dockerfile) and pushes it here at the
        # HUMAN-GATE. Immutable tags so a deployed runtime's image
        # provenance can't be silently overwritten; scan on push.
        self.repo = ecr.Repository(
            self,
            "RuntimeRepo",
            image_scan_on_push=True,
            image_tag_mutability=ecr.TagMutability.IMMUTABLE,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        image_tag = self.node.try_get_context("agentRuntimeImageTag") or "latest"

        # R-RT-ROLE. The role AgentCore Runtime assumes to run the crew.
        # Scoped to exactly what the crew needs. The SourceAccount +
        # SourceArn conditions block the confused-deputy case.
        self.runtime_role = iam.Role(
            self,
            "RuntimeRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:aws:bedrock-agentcore:{self.region}:"
                            f"{self.account}:*"
                        )
                    },
                },
            ),
            description="AgentCore Runtime execution role for the crew",
        )
        # Pull the crew image from this repo only.
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                ],
                resources=[self.repo.repository_arn],
            )
        )
        # JUSTIFIED: ecr:GetAuthorizationToken is an account-level token
        # operation with no resource-level form in IAM (AWS docs:
        # bedrock-agentcore runtime-permissions). It is the SOLE literal
        # Resource:"*" in this stack, isolated in its own statement so an
        # accidental future wildcard still fails the no-wildcard test.
        # Recorded as the single accepted exception in infra/README.md.
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )
        # CloudWatch Logs for the runtime, scoped to the AgentCore
        # runtime log-group ARN (an ARN with a path wildcard — NOT a
        # literal Resource:"*").
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:"
                    f"/aws/bedrock-agentcore/runtimes/*",
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:"
                    f"/aws/bedrock-agentcore/runtimes/*:log-stream:*",
                ],
            )
        )
        # The crew's LLM calls (CrewAI -> Bedrock models).
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/*",
                    f"arn:aws:bedrock:{self.region}:{self.account}:"
                    f"inference-profile/*",
                ],
            )
        )
        # The researcher agent calls the deployed Bedrock Agent via
        # crewai_tools BedrockInvokeAgentTool. Scoped to the agent-alias
        # ARN pattern so the frozen agent_stack need not export the ARN.
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeAgent"],
                resources=[
                    f"arn:aws:bedrock:{self.region}:{self.account}:"
                    f"agent-alias/*"
                ],
            )
        )
        # The crew resolves the agent ids from these two SSM parameters
        # at container start (agent_ids.py). Scoped to exactly them.
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter"
                    f"/compliance-assistant/agent-id",
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter"
                    f"/compliance-assistant/agent-alias-id",
                ],
            )
        )
        # AgentCore workload identity (token vending), scoped to the
        # default workload-identity directory for this account/region.
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                ],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:"
                    f"{self.account}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{self.region}:"
                    f"{self.account}:workload-identity-directory/default"
                    f"/workload-identity/*",
                ],
            )
        )
        # Write the crew's report artifacts to the versioned bucket.
        # Explicit least-privilege rather than bucket.grant_put(): the
        # CDK grant expands to s3:PutObjectLegalHold / PutObjectRetention
        # / PutObjectVersionTagging / Abort* (+ kms:Decrypt from the
        # bucket grant) — none of which the shim's upload_file path
        # uses. The shim only PutObjects small markdown files into an
        # SSE-KMS bucket, so scope to exactly that. Observability
        # (CloudWatch metrics, X-Ray) stays deferred to the
        # observability phase so no other Resource:"*" is introduced.
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"],
                resources=[self.report_bucket.arn_for_objects("reports/*")],
            )
        )
        # SSE-KMS object writes need a data key; no Decrypt (the runtime
        # never reads the reports back).
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:GenerateDataKey", "kms:Encrypt"],
                resources=[self.report_key.key_arn],
            )
        )

        # R-RT-RUNTIME. The AgentCore Runtime. maxLifetime is
        # context-driven so the run ceiling is a config knob, validated
        # against the AWS-documented 60..28800s bound rather than
        # synthesizing an out-of-range value the service would reject.
        max_lifetime = int(
            self.node.try_get_context("runtimeMaxLifetimeSeconds") or 28800
        )
        if not (_MAX_LIFETIME_FLOOR <= max_lifetime <= _MAX_LIFETIME_CEIL):
            raise ValueError(
                f"runtimeMaxLifetimeSeconds={max_lifetime!r} out of range: "
                f"AgentCore Runtime maxLifetime must be "
                f"{_MAX_LIFETIME_FLOOR}..{_MAX_LIFETIME_CEIL} seconds."
            )

        topic = self.node.try_get_context("runtimeTopic") or "PCI DSS"
        model = self.node.try_get_context("runtimeModel") or (
            "bedrock/us.amazon.nova-pro-v1:0"
        )

        self.runtime = agentcore.CfnRuntime(
            self,
            "Runtime",
            agent_runtime_name=_RUNTIME_NAME,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=f"{self.repo.repository_uri}:{image_tag}"
                )
            ),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            role_arn=self.runtime_role.role_arn,
            lifecycle_configuration=agentcore.CfnRuntime.LifecycleConfigurationProperty(
                max_lifetime=max_lifetime,
                idle_runtime_session_timeout=900,
            ),
            protocol_configuration="HTTP",
            environment_variables={
                "TOPIC": topic,
                "MODEL": model,
                "AWS_REGION_NAME": self.region,
                "REPORT_BUCKET": self.report_bucket.bucket_name,
            },
            tags={
                "project": "compliance-assistant",
                "component": "runtime",
            },
        )

        cdk.CfnOutput(
            self, "RuntimeArn", value=self.runtime.attr_agent_runtime_arn
        )
        cdk.CfnOutput(
            self, "ReportBucketName", value=self.report_bucket.bucket_name
        )
        cdk.CfnOutput(
            self, "RuntimeRepoUri", value=self.repo.repository_uri
        )
