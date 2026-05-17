#!/usr/bin/env python
"""CDK entry point for the compliance-assistant Bedrock knowledge layer.

Four stacks, split by blast radius. The knowledge-base stack holds the
data-bearing, slow-to-recreate resources (corpus bucket, vector store,
the Knowledge Base itself) and uses RETAIN so a stack delete never
destroys regulatory evidence. The agent stack holds the cheap,
fast-to-iterate resources (Guardrail, Agent, alias) so prompt changes
never put the corpus at risk. The runtime-ECR stack holds just the
image repository, deployed first so the operator can push the crew
image before the runtime is created against it. The runtime stack
hosts the crew on AgentCore Runtime + its versioned report bucket. The
agent stack reads the Knowledge Base from the kb stack by reference, so
the KB is defined exactly once; the runtime stack is ordered after both
the ECR stack (its image must be pushable first) and the agent stack
(the crew resolves the agent ids from SSM at container start).
"""
import os

import aws_cdk as cdk

from stacks.kb_stack import ComplianceKbStack
from stacks.agent_stack import ComplianceAgentStack
from stacks.runtime_ecr_stack import ComplianceRuntimeEcrStack
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

# The image repository, in its own stack so the operator can push the
# linux/arm64 crew image before the runtime is created against it (a
# runtime created against a not-yet-pushed image fails).
runtime_ecr_stack = ComplianceRuntimeEcrStack(
    app, "ComplianceRuntimeEcrStack", env=env
)

# The runtime hosts the crew. It is ordered after BOTH: the ECR stack
# (its image must be pushable first) and the agent stack (the crew
# reads the agent ids from SSM, published by the agent stack, at
# container start). It is intentionally NOT part of any bulk deploy —
# the README runbook deploys it last, only after the RAG eval gate
# passes and the image is pushed.
runtime_stack = ComplianceRuntimeStack(
    app,
    "ComplianceRuntimeStack",
    env=env,
    ecr_repository=runtime_ecr_stack.repository,
)
runtime_stack.add_dependency(runtime_ecr_stack)
runtime_stack.add_dependency(agent_stack)

app.synth()
