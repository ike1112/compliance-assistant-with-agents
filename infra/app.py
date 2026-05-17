#!/usr/bin/env python
"""CDK entry point for the compliance-assistant Bedrock knowledge layer.

Three stacks, split by blast radius. The knowledge-base stack holds the
data-bearing, slow-to-recreate resources (corpus bucket, vector store,
the Knowledge Base itself) and uses RETAIN so a stack delete never
destroys regulatory evidence. The agent stack holds the cheap,
fast-to-iterate resources (Guardrail, Agent, alias) so prompt changes
never put the corpus at risk. The runtime stack hosts the crew on
AgentCore Runtime + its versioned report bucket. The agent stack reads
the Knowledge Base from the kb stack by reference, so the KB is defined
exactly once; the runtime stack is ordered after the agent stack
because the crew resolves the agent ids from SSM at container start.
"""
import os

import aws_cdk as cdk

from stacks.kb_stack import ComplianceKbStack
from stacks.agent_stack import ComplianceAgentStack
from stacks.runtime_stack import ComplianceRuntimeStack

app = cdk.App()

# Account/region come from the standard CDK env vars when deploying;
# region falls back to us-east-1, the account that holds the existing
# Bedrock model access (see infra/README.md).
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

# Termination protection on the data-bearing stack: it holds the
# corpus, the vector store, and the Knowledge Base, none of which
# should be deletable by an accidental `cdk destroy`.
kb_stack = ComplianceKbStack(
    app, "ComplianceKbStack", env=env, termination_protection=True
)

agent_stack = ComplianceAgentStack(
    app,
    "ComplianceAgentStack",
    env=env,
    knowledge_base=kb_stack.knowledge_base,
)

# The runtime hosts the crew; the crew reads the agent ids from SSM at
# container start, so the SSM parameters (published by the agent stack)
# must exist first. Enforce the deploy order explicitly.
runtime_stack = ComplianceRuntimeStack(
    app,
    "ComplianceRuntimeStack",
    env=env,
)
runtime_stack.add_dependency(agent_stack)

app.synth()
