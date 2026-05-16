"""resolve_agent_ids: SSM first, env fallback, placeholder rejected."""
import sys

import pytest

from compliance_assistant import agent_ids


def test_ssm_values_are_used(monkeypatch):
    class _SSM:
        def get_parameter(self, Name):
            val = "AG123" if Name.endswith("agent-id") else "AL456"
            return {"Parameter": {"Value": val}}

    class _Boto:
        def client(self, _name):
            return _SSM()

    monkeypatch.setitem(sys.modules, "boto3", _Boto())
    assert agent_ids.resolve_agent_ids() == ("AG123", "AL456")


def test_falls_back_to_env_when_ssm_unavailable(monkeypatch):
    # No boto3 -> _from_ssm returns None -> env is used.
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setenv("AGENT_ID", "ENVAG")
    monkeypatch.setenv("AGENT_ALIAS_ID", "ENVAL")
    assert agent_ids.resolve_agent_ids() == ("ENVAG", "ENVAL")


def test_placeholder_is_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setenv("AGENT_ID", "replace-with-your-amazon-bedrock-agent-id")
    monkeypatch.setenv("AGENT_ALIAS_ID", "whatever")
    with pytest.raises(RuntimeError):
        agent_ids.resolve_agent_ids()


def test_missing_value_is_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_ALIAS_ID", raising=False)
    with pytest.raises(RuntimeError):
        agent_ids.resolve_agent_ids()


# --- the reject primitive, now public and reused by startup.py ------------
# Edge cases that kill likely mutants in the gate's mutation target.

def test_public_name_is_the_alias_target():
    assert agent_ids.reject_missing_or_placeholder is agent_ids._reject_placeholder


def test_empty_string_is_rejected():
    with pytest.raises(RuntimeError):
        agent_ids.reject_missing_or_placeholder("X", "")


def test_exact_placeholder_prefix_is_rejected():
    with pytest.raises(RuntimeError):
        agent_ids.reject_missing_or_placeholder("X", "replace-with-")


def test_prefix_plus_one_char_is_rejected():
    with pytest.raises(RuntimeError):
        agent_ids.reject_missing_or_placeholder("X", "replace-with-y")


def test_contains_but_not_prefixed_is_accepted():
    # kills a startswith->in mutant: the marker is present but not a prefix
    assert (
        agent_ids.reject_missing_or_placeholder("X", "x-replace-with-y")
        == "x-replace-with-y"
    )


def test_valid_value_is_returned_unchanged():
    assert agent_ids.reject_missing_or_placeholder("X", "AG123") == "AG123"


def test_partial_ssm_failure_falls_back_to_env(monkeypatch):
    # One get_parameter raises -> _from_ssm's broad except -> None ->
    # env fallback. Kills mutants that narrow/skip the except.
    class _SSM:
        def get_parameter(self, Name):
            if Name.endswith("agent-id"):
                return {"Parameter": {"Value": "AG_SSM"}}
            raise RuntimeError("alias param missing")

    class _Boto:
        def client(self, _name):
            return _SSM()

    monkeypatch.setitem(sys.modules, "boto3", _Boto())
    monkeypatch.setenv("AGENT_ID", "ENVAG")
    monkeypatch.setenv("AGENT_ALIAS_ID", "ENVAL")
    assert agent_ids.resolve_agent_ids() == ("ENVAG", "ENVAL")
