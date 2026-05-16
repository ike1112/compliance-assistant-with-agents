"""Resolve the Bedrock agent ids the crew talks to.

The infra stack publishes the agent id and alias id to SSM Parameter
Store, so a deployed run reads them from there. For local development
without the stack, the AGENT_ID / AGENT_ALIAS_ID env vars work as a
fallback when explicitly opted into. Either way, a value that is
missing, blank, whitespace-padded, or still the .env.example
placeholder is rejected loudly at startup rather than failing deep
inside a Bedrock call.

Trust boundary: the env fallback is taken only when SSM is *genuinely*
unreachable (boto3 absent, or no credentials/endpoint at all) or when
explicitly opted into with USE_ENV_AGENT_IDS. If SSM is reachable but
the ids cannot be read (AccessDenied, missing parameter, malformed
response) that fails closed with a clear error — it must never silently
downgrade to env-controlled ids in a configured environment.

Named agent_ids (not config) so it does not collide with the existing
config/ directory of agent and task YAML.
"""
import os

_PLACEHOLDER_PREFIX = "replace-with-"
_TRUTHY = {"1", "true", "yes", "on"}

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


def _env_fallback_opt_in() -> bool:
    """True if the operator explicitly chose env ids over SSM."""
    return os.environ.get("USE_ENV_AGENT_IDS", "").strip().lower() in _TRUTHY


def _ssm_unreachable_types():
    """botocore exceptions meaning 'no SSM here', not 'SSM said no'."""
    try:
        from botocore.exceptions import (
            EndpointConnectionError,
            NoCredentialsError,
        )
    except ImportError:  # pragma: no cover - botocore ships with boto3
        return ()
    return (NoCredentialsError, EndpointConnectionError)


def _from_ssm():
    """Return (agent_id, alias_id) from SSM, or None to allow the env
    fallback.

    None is returned only when SSM is *genuinely* unreachable: explicit
    USE_ENV_AGENT_IDS opt-in, boto3 not installed, or no
    credentials/endpoint at all (a local box with no AWS). Any failure
    once SSM is actually reachable (AccessDenied, missing parameter,
    malformed response) raises: it fails closed rather than silently
    running against env-controlled ids in a configured environment.
    """
    if _env_fallback_opt_in():
        return None
    try:
        import boto3
    except ImportError:
        return None  # SSM tooling absent: local dev without the stack
    id_path = os.environ.get("AGENT_ID_SSM_PATH", _DEFAULT_AGENT_ID_PATH)
    alias_path = os.environ.get(
        "AGENT_ALIAS_ID_SSM_PATH", _DEFAULT_AGENT_ALIAS_ID_PATH
    )
    try:
        ssm = boto3.client("ssm")
        agent_id = ssm.get_parameter(Name=id_path)["Parameter"]["Value"]
        alias_id = ssm.get_parameter(Name=alias_path)["Parameter"]["Value"]
        return agent_id, alias_id
    except _ssm_unreachable_types():
        return None  # no creds/endpoint: genuine local dev, env is fine
    except Exception as exc:
        raise RuntimeError(
            f"SSM is reachable but the agent ids could not be read "
            f"({exc!r}). Refusing to fall back to env ids in a "
            f"configured environment; fix the stack/IAM, or set "
            f"USE_ENV_AGENT_IDS=1 for a deliberate local run."
        ) from exc


def resolve_agent_ids() -> tuple[str, str]:
    """The agent id and alias id, SSM first then env, never a placeholder.

    Values are stripped before validation so a whitespace-padded
    placeholder (e.g. a copied ``" replace-with-..."``) cannot slip past
    the check, and the value used downstream is exactly the one
    validated.
    """
    from_ssm = _from_ssm()
    if from_ssm is not None:
        agent_id, alias_id = from_ssm
    else:
        agent_id = os.environ.get("AGENT_ID", "")
        alias_id = os.environ.get("AGENT_ALIAS_ID", "")
    return (
        reject_missing_or_placeholder("AGENT_ID", agent_id.strip()),
        reject_missing_or_placeholder("AGENT_ALIAS_ID", alias_id.strip()),
    )
