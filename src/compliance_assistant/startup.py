"""Fail-fast startup configuration checks for the local CLI.

Before any crew command spends a model call, this rejects required
config that is missing, blank, whitespace-only, or still a
.env.example placeholder, with one clear RuntimeError. The crew used
to validate only TOPIC (and only for None), then fail deep inside a
Bedrock call for everything else; this makes the contract explicit and
up front.

The env mapping is passed in (not read from os.environ here) so tests
drive it deterministically. Validation is invoked per CLI entry point,
never at import time: validate_startup_config calls resolve_agent_ids,
which probes SSM via boto3, and import-time AWS I/O would make a bare
`import compliance_assistant.main` do network/credential work and
poison test collection.
"""
from collections.abc import Mapping

from compliance_assistant.agent_ids import (
    reject_missing_or_placeholder,
    resolve_agent_ids,
)

_TRUTHY = {"1", "true", "yes", "on"}


def crew_verbose_enabled(env: Mapping[str, str]) -> bool:
    """Whether the crew should print agent steps. Off unless CREW_VERBOSE
    is set truthy (1/true/yes/on, case-insensitive). Default OFF."""
    return env.get("CREW_VERBOSE", "").strip().lower() in _TRUTHY


def validate_startup_config(env: Mapping[str, str]) -> None:
    """Reject missing/blank/placeholder required config, fast and clear.

    TOPIC and MODEL are stripped first, so a whitespace-only value is
    treated as empty and rejected. The strip lives here on purpose, not
    in the agent_ids primitive (which the quality gate mutation-tests
    and must stay byte-identical). The agent-id resolution path
    (SSM-first, env fallback) is then exercised via resolve_agent_ids,
    which raises on a missing/placeholder id; its values are not
    stripped — that algorithm is owned elsewhere.
    """
    reject_missing_or_placeholder("TOPIC", env.get("TOPIC", "").strip())
    reject_missing_or_placeholder("MODEL", env.get("MODEL", "").strip())
    resolve_agent_ids()
