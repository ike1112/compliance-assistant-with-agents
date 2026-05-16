"""Synth-time contract for the agent stack. Mirrors test_kb_stack.py."""
import aws_cdk as cdk
from aws_cdk.assertions import Template, Match

from stacks.kb_stack import ComplianceKbStack
from stacks.agent_stack import ComplianceAgentStack


def _template() -> Template:
    app = cdk.App()
    kb = ComplianceKbStack(app, "TestKb")
    agent = ComplianceAgentStack(
        app, "TestAgent", knowledge_base=kb.knowledge_base
    )
    return Template.from_stack(agent)


def test_one_agent_wired_to_a_knowledge_base():
    t = _template()
    t.resource_count_is("AWS::Bedrock::Agent", 1)
    t.has_resource_properties(
        "AWS::Bedrock::Agent",
        {"KnowledgeBases": Match.any_value()},
    )


def test_agent_has_guardrail_attached():
    t = _template()
    t.resource_count_is("AWS::Bedrock::Guardrail", 1)
    t.has_resource_properties(
        "AWS::Bedrock::Agent",
        {"GuardrailConfiguration": Match.any_value()},
    )


def test_agent_ids_published_to_ssm():
    t = _template()
    t.resource_count_is("AWS::SSM::Parameter", 2)
    names = {
        p["Properties"]["Name"]
        for p in t.find_resources("AWS::SSM::Parameter").values()
    }
    assert names == {
        "/compliance-assistant/agent-id",
        "/compliance-assistant/agent-alias-id",
    }


def test_agent_role_has_no_wildcard_resources():
    t = _template()
    for pol in t.find_resources("AWS::IAM::Policy").values():
        for stmt in pol["Properties"]["PolicyDocument"]["Statement"]:
            assert stmt.get("Resource") != "*", "wildcard resource in agent IAM policy"
