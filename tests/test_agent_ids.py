"""resolve_agent_ids: SSM first, env fallback only when SSM is
genuinely unavailable, fail-closed on a reachable-but-misconfigured
SSM, whitespace-stripped, placeholder rejected.

boto3 is stubbed via sys.modules (the project convention); botocore's
real exception types are used so the SSM error classification is
exercised exactly as in production.
"""
import sys

import pytest
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)

from compliance_assistant import agent_ids


def _client_error(code):
    return ClientError({"Error": {"Code": code}}, "GetParameter")


class _Boto:
    """Stub boto3 whose ssm client returns/raises per construction."""

    def __init__(self, *, agent="AG123", alias="AL456", raises=None):
        self._agent, self._alias, self._raises = agent, alias, raises

    def client(self, _name):
        outer = self

        class _SSM:
            def get_parameter(self, Name):
                if outer._raises is not None:
                    raise outer._raises
                val = outer._agent if Name.endswith("agent-id") else outer._alias
                return {"Parameter": {"Value": val}}

        return _SSM()


# --- reject_missing_or_placeholder primitive (mutation-frozen) ----------

def test_public_name_is_the_alias_target():
    assert agent_ids.reject_missing_or_placeholder is agent_ids._reject_placeholder


def test_empty_string_is_rejected():
    with pytest.raises(RuntimeError, match="X"):
        agent_ids.reject_missing_or_placeholder("X", "")


def test_exact_placeholder_prefix_is_rejected():
    with pytest.raises(RuntimeError):
        agent_ids.reject_missing_or_placeholder("X", "replace-with-")


def test_prefix_plus_one_char_is_rejected():
    with pytest.raises(RuntimeError):
        agent_ids.reject_missing_or_placeholder("X", "replace-with-y")


def test_contains_but_not_prefixed_is_accepted():
    # kills a startswith->in mutant: marker present but not a prefix
    assert (
        agent_ids.reject_missing_or_placeholder("X", "x-replace-with-y")
        == "x-replace-with-y"
    )


def test_valid_value_is_returned_unchanged():
    assert agent_ids.reject_missing_or_placeholder("X", "AG123") == "AG123"


def test_error_message_names_the_offending_var():
    # kills the name-argument string mutants (XXAGENT_IDXX etc.)
    with pytest.raises(RuntimeError, match="AGENT_ID"):
        agent_ids.reject_missing_or_placeholder("AGENT_ID", "")
    with pytest.raises(RuntimeError, match="AGENT_ALIAS_ID"):
        agent_ids.reject_missing_or_placeholder("AGENT_ALIAS_ID", "")


def test_error_echoes_the_rejected_value():
    with pytest.raises(RuntimeError, match=r"replace-with-x"):
        agent_ids.reject_missing_or_placeholder("X", "replace-with-x")


# --- _env_fallback_opt_in ----------------------------------------------

@pytest.mark.parametrize("v", ["1", "true", "TRUE", "Yes", " on "])
def test_opt_in_truthy(monkeypatch, v):
    monkeypatch.setenv("USE_ENV_AGENT_IDS", v)
    assert agent_ids._env_fallback_opt_in() is True


@pytest.mark.parametrize("v", ["", "0", "false", "no", "off", "maybe"])
def test_opt_in_falsy(monkeypatch, v):
    monkeypatch.setenv("USE_ENV_AGENT_IDS", v)
    assert agent_ids._env_fallback_opt_in() is False


def test_opt_in_unset_is_false(monkeypatch):
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)
    assert agent_ids._env_fallback_opt_in() is False


# --- _from_ssm classification ------------------------------------------

def test_ssm_success_returns_ids(monkeypatch):
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)
    monkeypatch.setitem(sys.modules, "boto3", _Boto())
    assert agent_ids._from_ssm() == ("AG123", "AL456")


def test_opt_in_skips_ssm_entirely(monkeypatch):
    monkeypatch.setenv("USE_ENV_AGENT_IDS", "1")
    # boto3 present and working, but opt-in must short-circuit to None
    monkeypatch.setitem(sys.modules, "boto3", _Boto())
    assert agent_ids._from_ssm() is None


def test_no_boto3_falls_back(monkeypatch):
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)
    monkeypatch.setitem(sys.modules, "boto3", None)  # import boto3 -> None
    assert agent_ids._from_ssm() is None


def test_no_credentials_falls_back(monkeypatch):
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)
    monkeypatch.setitem(
        sys.modules, "boto3", _Boto(raises=NoCredentialsError())
    )
    assert agent_ids._from_ssm() is None


def test_parameter_not_found_fails_closed(monkeypatch):
    # SSM is reachable and says "no such parameter": that is a configured
    # environment with the stack missing -> fail closed, do not silently
    # use env ids. (Local dev uses USE_ENV_AGENT_IDS=1.)
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)
    monkeypatch.setitem(
        sys.modules, "boto3", _Boto(raises=_client_error("ParameterNotFound"))
    )
    with pytest.raises(RuntimeError, match="Refusing to fall back"):
        agent_ids._from_ssm()


def test_access_denied_fails_closed(monkeypatch):
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)
    monkeypatch.setitem(
        sys.modules, "boto3", _Boto(raises=_client_error("AccessDeniedException"))
    )
    with pytest.raises(RuntimeError, match="Refusing to fall back"):
        agent_ids._from_ssm()


def test_malformed_response_fails_closed(monkeypatch):
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)

    class _BadBoto:
        def client(self, _n):
            class _SSM:
                def get_parameter(self, Name):
                    return {"Parameter": {}}  # missing "Value" -> KeyError
            return _SSM()

    monkeypatch.setitem(sys.modules, "boto3", _BadBoto())
    with pytest.raises(RuntimeError, match="could not be read"):
        agent_ids._from_ssm()


def test_no_endpoint_falls_back(monkeypatch):
    # Genuinely cannot reach SSM (no endpoint) -> env fallback allowed.
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "boto3",
        _Boto(raises=EndpointConnectionError(endpoint_url="https://ssm")),
    )
    assert agent_ids._from_ssm() is None


# --- resolve_agent_ids: end to end -------------------------------------

def test_ssm_values_are_used(monkeypatch):
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)
    monkeypatch.setitem(sys.modules, "boto3", _Boto(agent="AG", alias="AL"))
    assert agent_ids.resolve_agent_ids() == ("AG", "AL")


def test_falls_back_to_env_when_ssm_unavailable(monkeypatch):
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setenv("AGENT_ID", "ENVAG")
    monkeypatch.setenv("AGENT_ALIAS_ID", "ENVAL")
    assert agent_ids.resolve_agent_ids() == ("ENVAG", "ENVAL")


def test_env_opt_in_uses_env_even_with_working_ssm(monkeypatch):
    monkeypatch.setenv("USE_ENV_AGENT_IDS", "1")
    monkeypatch.setitem(sys.modules, "boto3", _Boto(agent="SSMAG"))
    monkeypatch.setenv("AGENT_ID", "ENVAG")
    monkeypatch.setenv("AGENT_ALIAS_ID", "ENVAL")
    assert agent_ids.resolve_agent_ids() == ("ENVAG", "ENVAL")


def test_placeholder_is_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setenv("AGENT_ID", "replace-with-your-amazon-bedrock-agent-id")
    monkeypatch.setenv("AGENT_ALIAS_ID", "whatever")
    with pytest.raises(RuntimeError, match="AGENT_ID"):
        agent_ids.resolve_agent_ids()


def test_missing_value_is_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_ALIAS_ID", raising=False)
    with pytest.raises(RuntimeError):
        agent_ids.resolve_agent_ids()


def test_whitespace_padded_placeholder_is_rejected(monkeypatch):
    # A2: a copied "' replace-with-...'" must not slip past validation.
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setenv("AGENT_ID", "  replace-with-your-amazon-bedrock-agent-id")
    monkeypatch.setenv("AGENT_ALIAS_ID", "real-alias")
    with pytest.raises(RuntimeError, match="AGENT_ID"):
        agent_ids.resolve_agent_ids()


def test_whitespace_padded_valid_value_is_stripped(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setenv("AGENT_ID", "  AG123\t")
    monkeypatch.setenv("AGENT_ALIAS_ID", " AL456 ")
    assert agent_ids.resolve_agent_ids() == ("AG123", "AL456")


def test_reachable_but_denied_ssm_does_not_use_env(monkeypatch):
    # A1: AccessDenied must fail closed even if valid env ids exist.
    monkeypatch.delenv("USE_ENV_AGENT_IDS", raising=False)
    monkeypatch.setitem(
        sys.modules, "boto3", _Boto(raises=_client_error("AccessDeniedException"))
    )
    monkeypatch.setenv("AGENT_ID", "ENVAG")
    monkeypatch.setenv("AGENT_ALIAS_ID", "ENVAL")
    with pytest.raises(RuntimeError, match="Refusing to fall back"):
        agent_ids.resolve_agent_ids()
