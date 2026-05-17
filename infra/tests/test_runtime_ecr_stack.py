"""Synth-time contract for the runtime ECR stack.

The repo is split into its own stack so the operator can push the
linux/arm64 crew image before the runtime is created against it (a
runtime created against a not-yet-pushed image fails). The name must
be deterministic so the push target is knowable without a stack output.
"""
import aws_cdk as cdk
from aws_cdk.assertions import Template, Match

from stacks.runtime_ecr_stack import (
    ComplianceRuntimeEcrStack,
    RUNTIME_REPO_NAME,
)


def _template() -> Template:
    return Template.from_stack(
        ComplianceRuntimeEcrStack(cdk.App(), "TestRtEcr")
    )


def test_one_ecr_repo_with_deterministic_name():
    t = _template()
    t.resource_count_is("AWS::ECR::Repository", 1)
    t.has_resource_properties(
        "AWS::ECR::Repository",
        Match.object_like({"RepositoryName": RUNTIME_REPO_NAME}),
    )


def test_repo_is_immutable_and_scans_on_push():
    _template().has_resource_properties(
        "AWS::ECR::Repository",
        Match.object_like(
            {
                "ImageTagMutability": "IMMUTABLE",
                "ImageScanningConfiguration": {"ScanOnPush": True},
            }
        ),
    )


def test_repo_is_retained_on_stack_delete():
    # The audited image must survive a runtime teardown.
    t = _template()
    repo = list(t.find_resources("AWS::ECR::Repository").values())[0]
    assert repo["DeletionPolicy"] == "Retain", repo.get("DeletionPolicy")


def test_no_runtime_or_iam_in_the_ecr_stack():
    # Blast-radius split: the ECR stack is repo-only so it can deploy
    # before the runtime without dragging the runtime/role with it.
    t = _template()
    t.resource_count_is("AWS::BedrockAgentCore::Runtime", 0)
    t.resource_count_is("AWS::IAM::Role", 0)
