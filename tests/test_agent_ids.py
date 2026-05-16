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
