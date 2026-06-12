"""Observability stack: model-invocation logging, dashboard, SLO alarms.

Three concerns, one stack (its own blast radius, mirroring the Phase-4
split):

- **Model-invocation logging.** Amazon Bedrock has *no* native
  CloudFormation resource for `PutModelInvocationLoggingConfiguration`
  (verified against current AWS docs — AWS's own pattern uses a
  Lambda/custom resource). So a CDK `AwsCustomResource`
  (`install_latest_aws_sdk=False`, deterministic/offline synth) calls
  it on create/update and `DeleteModelInvocationLoggingConfiguration`
  on delete. Raw text/image/embedding/video data delivery is
  **disabled** — only invocation metadata reaches CloudWatch, so a PAN
  or email in a prompt/response is never written there. The redaction
  CHECK holds on the Bedrock path by construction (and on the
  in-process span path via `compliance_assistant.tracing.redact`).
- **Dashboard.** One CloudWatch dashboard over the SLO metrics.
- **SLO alarms.** `docs/SLOs.md` is the single source of truth; this
  stack creates exactly one alarm per SLO, bound to that SLO's real
  metric (namespace/metric/statistic/period) with that SLO's
  threshold/comparator. The synth-contract test re-parses the same
  file and cross-checks, so the alarms cannot drift from the document
  and cannot watch the wrong metric.

IAM note (recorded in infra/README.md): the sole literal
`Resource:"*"` among this stack's *own* inline statements is the
account-level `bedrock:Put/DeleteModelInvocationLoggingConfiguration`
op (no resource-ARN form — the Phase-4 `ecr:GetAuthorizationToken`
pattern). The CDK `AwsCustomResource` provider framework additionally
attaches the AWS-managed `AWSLambdaBasicExecutionRole` (logs-only) to
its singleton Lambda — a well-understood CDK pattern, accounted for and
asserted by the test, justified in the README.
"""
import os
import pathlib

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_iam as iam,
    aws_logs as logs,
    aws_sns as sns,
    aws_sns_subscriptions as subscriptions,
    custom_resources as cr,
)
from constructs import Construct

from stacks.slo_contract import SLOS_MD, parse_slos

_CMP = {
    "GreaterThanThreshold":
        cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    "GreaterThanOrEqualToThreshold":
        cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
    "LessThanThreshold":
        cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
    "LessThanOrEqualToThreshold":
        cloudwatch.ComparisonOperator.LESS_THAN_OR_EQUAL_TO_THRESHOLD,
}


class ComplianceObservabilityStack(cdk.Stack):
    """Bedrock model-invocation logging + dashboard + SLO-derived alarms."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        slos_path: pathlib.Path | str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Single source of truth. Fail-closed: a malformed/empty/
        # duplicate-id table raises ValueError at synth (mirrors the
        # kb_stack fail-closed-on-bad-context pattern) rather than
        # shipping a mismatched alarm set.
        slos = parse_slos(slos_path or SLOS_MD)
        alarm_email = (
            self.node.try_get_context("alarmEmail")
            or os.environ.get("ALARM_EMAIL")
        )

        # R-OBS-SNS. Shared notification path for SLO alarms and the KB
        # ingestion alarms/rules in the data-bearing stack.
        self.notification_topic = sns.Topic(
            self,
            "NotificationTopic",
            topic_name="compliance-assistant-alerts",
            display_name="Compliance Assistant alerts",
        )
        if alarm_email:
            self.notification_topic.add_subscription(
                subscriptions.EmailSubscription(alarm_email)
            )

        # R-OBS-LOGS. Where Bedrock delivers invocation metadata.
        # RETAIN so an audit trail is never destroyed by a stack delete.
        log_group = logs.LogGroup(
            self,
            "ModelInvocationLogs",
            log_group_name="/compliance-assistant/bedrock-invocation",
            retention=logs.RetentionDays.SIX_MONTHS,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # R-OBS-ROLE. The role Bedrock assumes to deliver logs. Scoped
        # to writing this log group only; SourceAccount blocks the
        # confused-deputy case.
        delivery_role = iam.Role(
            self,
            "BedrockLoggingRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account}
                },
            ),
            description="Bedrock model-invocation-logging delivery role",
        )
        delivery_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    log_group.log_group_arn,
                    f"{log_group.log_group_arn}:log-stream:*",
                ],
            )
        )

        # R-OBS-CFG. No native CFN resource for model-invocation
        # logging — call the API via a custom resource. Data delivery
        # is DISABLED so raw prompts/responses never reach CloudWatch
        # (PAN-safe by construction; the redaction CHECK's
        # "emitted logs" path is covered here, the "traces" path by
        # tracing.redact). install_latest_aws_sdk=False keeps synth
        # offline/deterministic and the deploy free of an npm fetch.
        logging_config = {
            "loggingConfig": {
                "cloudWatchConfig": {
                    "logGroupName": log_group.log_group_name,
                    "roleArn": delivery_role.role_arn,
                },
                "textDataDeliveryEnabled": False,
                "imageDataDeliveryEnabled": False,
                "embeddingDataDeliveryEnabled": False,
                "videoDataDeliveryEnabled": False,
            }
        }
        self.logging = cr.AwsCustomResource(
            self,
            "BedrockInvocationLogging",
            install_latest_aws_sdk=False,
            on_create=cr.AwsSdkCall(
                service="Bedrock",
                action="putModelInvocationLoggingConfiguration",
                parameters=logging_config,
                physical_resource_id=cr.PhysicalResourceId.of(
                    "compliance-bedrock-invocation-logging"
                ),
            ),
            on_update=cr.AwsSdkCall(
                service="Bedrock",
                action="putModelInvocationLoggingConfiguration",
                parameters=logging_config,
                physical_resource_id=cr.PhysicalResourceId.of(
                    "compliance-bedrock-invocation-logging"
                ),
            ),
            on_delete=cr.AwsSdkCall(
                service="Bedrock",
                action="deleteModelInvocationLoggingConfiguration",
            ),
            # JUSTIFIED: Put/DeleteModelInvocationLoggingConfiguration
            # are account-level Bedrock ops with no resource-ARN form
            # (same class as Phase-4 ecr:GetAuthorizationToken). Sole
            # literal Resource:"*" among this stack's own inline
            # statements; iam:PassRole is scoped to the delivery role.
            policy=cr.AwsCustomResourcePolicy.from_statements(
                [
                    iam.PolicyStatement(
                        actions=[
                            "bedrock:PutModelInvocationLoggingConfiguration",
                            "bedrock:DeleteModelInvocationLoggingConfiguration",
                        ],
                        resources=["*"],
                    ),
                    iam.PolicyStatement(
                        actions=["iam:PassRole"],
                        resources=[delivery_role.role_arn],
                    ),
                ]
            ),
        )
        self.logging.node.add_dependency(delivery_role)

        # R-OBS-ALARM. Exactly one alarm per SLO, bound to the SLO's
        # real metric. Count + every binding facet are derived from
        # docs/SLOs.md so the cross-check test proves a semantic
        # binding, not a threshold-only tautology.
        self.alarms: list[cloudwatch.Alarm] = []
        for slo in slos:
            metric = cloudwatch.Metric(
                namespace=slo.namespace,
                metric_name=slo.metric,
                statistic=slo.statistic,
                period=Duration.seconds(slo.period_s),
            )
            self.alarms.append(
                cloudwatch.Alarm(
                    self,
                    f"Alarm-{slo.slo_id}",
                    alarm_name=f"compliance-{slo.slo_id.replace('_', '-')}",
                    alarm_description=slo.description,
                    metric=metric,
                    threshold=slo.threshold,
                    evaluation_periods=slo.eval_periods,
                    comparison_operator=_CMP[slo.comparison_operator],
                    treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
                )
            )
            self.alarms[-1].add_alarm_action(
                cloudwatch_actions.SnsAction(self.notification_topic)
            )

        # R-OBS-DASH. One dashboard over the SLO metrics.
        dashboard = cloudwatch.Dashboard(
            self,
            "ObservabilityDashboard",
            dashboard_name="compliance-observability",
        )
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="SLO metrics",
                left=[
                    cloudwatch.Metric(
                        namespace=s.namespace,
                        metric_name=s.metric,
                        statistic=s.statistic,
                        period=Duration.seconds(s.period_s),
                    )
                    for s in slos
                ],
            ),
            cloudwatch.AlarmStatusWidget(alarms=self.alarms),
        )

        cdk.CfnOutput(
            self, "ModelInvocationLogGroup",
            value=log_group.log_group_name,
        )
        cdk.CfnOutput(
            self, "SloAlarmCount", value=str(len(self.alarms))
        )
        cdk.CfnOutput(
            self, "NotificationTopicArn", value=self.notification_topic.topic_arn
        )
