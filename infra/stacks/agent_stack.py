"""Agent stack: the cheap, fast-to-iterate Bedrock resources.

Holds the Guardrail, the Bedrock Agent (associated with the Knowledge
Base from the kb stack), the agent alias, and the SSM parameters the
crew reads to find the agent. Separated from the kb stack so iterating
on the agent prompt or guardrail never risks the corpus.

The Guardrail/Agent/alias/SSM resources are added next; for now this
is a valid empty stack that accepts the Knowledge Base by reference so
the whole app synthesizes while the build is still in progress.
"""
import aws_cdk as cdk
from constructs import Construct


class ComplianceAgentStack(cdk.Stack):
    """Guardrail-attached Bedrock Agent + alias, ids published to SSM."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        knowledge_base=None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Taken by reference so the Knowledge Base is defined exactly
        # once (in the kb stack). Used when the Agent is added.
        self._knowledge_base = knowledge_base
