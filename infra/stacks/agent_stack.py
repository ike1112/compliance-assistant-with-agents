"""Agent stack: the cheap, fast-to-iterate Bedrock resources.

Holds the Guardrail (+ a pinned version), the Bedrock Agent (wired to
the Knowledge Base from the kb stack), the agent alias, and the SSM
parameters the crew reads to find the agent. Separated from the kb
stack so iterating on the agent prompt or guardrail never risks the
corpus. The Knowledge Base is taken by reference so it is defined
exactly once (in the kb stack).
"""
import aws_cdk as cdk
from aws_cdk import (
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_ssm as ssm,
)
from constructs import Construct

_AGENT_INSTRUCTION = (
    "You are a compliance research assistant. Answer only using the "
    "provided sources from the knowledge base. For every requirement "
    "you state, cite the source it came from. If the knowledge base "
    "does not cover something, say so explicitly rather than answering "
    "from general knowledge."
)

# Standard Bedrock content filters. A sensible default set for a
# compliance assistant; tuning the strengths is explicitly out of
# scope for this sub-project.
_FILTER_TYPES = ["HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT", "PROMPT_ATTACK"]


class ComplianceAgentStack(cdk.Stack):
    """Guardrail-attached Bedrock Agent + alias, ids published to SSM."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        knowledge_base: bedrock.CfnKnowledgeBase,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        foundation_model = self.node.try_get_context("foundationModel") or (
            "amazon.nova-pro-v1:0"
        )

        # Guardrail. PROMPT_ATTACK only filters input (Bedrock rejects
        # an output strength on it), so it is configured separately.
        filters = [
            bedrock.CfnGuardrail.ContentFilterConfigProperty(
                type=t, input_strength="HIGH", output_strength="HIGH"
            )
            for t in _FILTER_TYPES
            if t != "PROMPT_ATTACK"
        ]
        filters.append(
            bedrock.CfnGuardrail.ContentFilterConfigProperty(
                type="PROMPT_ATTACK",
                input_strength="HIGH",
                output_strength="NONE",
            )
        )
        guardrail = bedrock.CfnGuardrail(
            self,
            "Guardrail",
            name="compliance-guardrail",
            blocked_input_messaging="This request was blocked by the compliance guardrail.",
            blocked_outputs_messaging="This response was blocked by the compliance guardrail.",
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=filters
            ),
        )
        # Pin a version so the agent points at an immutable guardrail,
        # not the mutable DRAFT.
        guardrail_version = bedrock.CfnGuardrailVersion(
            self,
            "GuardrailVersion",
            guardrail_identifier=guardrail.attr_guardrail_id,
        )

        # Agent service role. Scoped to invoking the foundation model
        # and retrieving from this one Knowledge Base — no wildcard.
        agent_role = iam.Role(
            self,
            "AgentRole",
            role_name="AmazonBedrockExecutionRoleForAgents_compliance",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account}
                },
            ),
            description="Bedrock Agent service role",
        )
        agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/{foundation_model}",
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*",
                ],
            )
        )
        agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:Retrieve"],
                resources=[knowledge_base.attr_knowledge_base_arn],
            )
        )

        agent = bedrock.CfnAgent(
            self,
            "Agent",
            agent_name="compliance-agent",
            foundation_model=foundation_model,
            instruction=_AGENT_INSTRUCTION,
            agent_resource_role_arn=agent_role.role_arn,
            auto_prepare=True,
            knowledge_bases=[
                bedrock.CfnAgent.AgentKnowledgeBaseProperty(
                    knowledge_base_id=knowledge_base.attr_knowledge_base_id,
                    description="Regulatory corpus grounding for compliance answers.",
                    knowledge_base_state="ENABLED",
                )
            ],
            guardrail_configuration=bedrock.CfnAgent.GuardrailConfigurationProperty(
                guardrail_identifier=guardrail.attr_guardrail_id,
                guardrail_version=guardrail_version.attr_version,
            ),
        )

        alias = bedrock.CfnAgentAlias(
            self,
            "AgentAlias",
            agent_alias_name="prod",
            agent_id=agent.attr_agent_id,
        )

        # The crew reads these instead of the old env placeholders.
        ssm.StringParameter(
            self,
            "AgentIdParam",
            parameter_name="/compliance-assistant/agent-id",
            string_value=agent.attr_agent_id,
        )
        ssm.StringParameter(
            self,
            "AgentAliasIdParam",
            parameter_name="/compliance-assistant/agent-alias-id",
            string_value=alias.attr_agent_alias_id,
        )

        cdk.CfnOutput(self, "AgentId", value=agent.attr_agent_id)
        cdk.CfnOutput(self, "AgentAliasId", value=alias.attr_agent_alias_id)
