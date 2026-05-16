"""Resolve the Bedrock agent ids the crew talks to.

The infra stack publishes the agent id and alias id to SSM Parameter
Store, so a deployed run reads them from there. For local development
without the stack deployed, the old AGENT_ID / AGENT_ALIAS_ID env vars
still work as a fallback. Either way, a value that is missing or still
the .env.example placeholder is rejected loudly at startup rather than
failing deep inside a Bedrock call.

Named agent_ids (not config) so it does not collide with the existing
config/ directory of agent and task YAML.
"""
import os

_PLACEHOLDER_PREFIX = "replace-with-"

# Where the infra stack writes the ids. Overridable so a second
# environment can point at differently-named parameters.
_DEFAULT_AGENT_ID_PATH = "/compliance-assistant/agent-id"
_DEFAULT_AGENT_ALIAS_ID_PATH = "/compliance-assistant/agent-alias-id"


def reject_missing_or_placeholder(name: str, value: str) -> str:
    if not value or value.startswith(_PLACEHOLDER_PREFIX):
        raise RuntimeError(
            f"{name} is unset or still a placeholder ({value!r}). "
            f"Deploy the infra stack (it publishes the ids to SSM) or "
            f"set a real value in .env."
        )
    return value


# Backward-compat alias: the missing/placeholder primitive is reused by
# startup.py (config hardening). Public name above; this keeps any
# existing internal/test reference working with no behaviour change.
_reject_placeholder = reject_missing_or_placeholder


def _from_ssm():
    """Return (agent_id, alias_id) from SSM, or None if unavailable."""
    id_path = os.environ.get("AGENT_ID_SSM_PATH", _DEFAULT_AGENT_ID_PATH)
    alias_path = os.environ.get(
        "AGENT_ALIAS_ID_SSM_PATH", _DEFAULT_AGENT_ALIAS_ID_PATH
    )
    try:
        import boto3

        ssm = boto3.client("ssm")
        agent_id = ssm.get_parameter(Name=id_path)["Parameter"]["Value"]
        alias_id = ssm.get_parameter(Name=alias_path)["Parameter"]["Value"]
        return agent_id, alias_id
    except Exception:
        # No creds, no parameter, offline — fall back to env.
        return None


def resolve_agent_ids() -> tuple[str, str]:
    """The agent id and alias id, SSM first then env, never a placeholder."""
    from_ssm = _from_ssm()
    if from_ssm is not None:
        agent_id, alias_id = from_ssm
    else:
        agent_id = os.environ.get("AGENT_ID", "")
        alias_id = os.environ.get("AGENT_ALIAS_ID", "")
    return (
        _reject_placeholder("AGENT_ID", agent_id),
        _reject_placeholder("AGENT_ALIAS_ID", alias_id),
    )
