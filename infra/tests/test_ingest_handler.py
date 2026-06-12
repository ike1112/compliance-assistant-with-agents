"""Unit tests for the ingest Lambda handler."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


_HANDLER = (
    Path(__file__).resolve().parents[1] / "lambdas" / "ingest" / "handler.py"
)
_SPEC = importlib.util.spec_from_file_location("ingest_handler", _HANDLER)
handler = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(handler)


def test_manual_resync_starts_one_ingestion_job(monkeypatch, capsys):
    class _FakeBedrock:
        def start_ingestion_job(self, **kwargs):
            assert kwargs["knowledgeBaseId"] == "kb-123"
            assert kwargs["dataSourceId"] == "ds-456"
            return {"ingestionJob": {"ingestionJobId": "job-1", "status": "STARTING"}}

    monkeypatch.setenv("KB_ID", "kb-123")
    monkeypatch.setenv("DATA_SOURCE_ID", "ds-456")
    monkeypatch.setattr(handler, "_bedrock", _FakeBedrock())

    result = handler.handler({"resync": True}, None)

    assert result["ingestionJobId"] == "job-1"
    assert result["status"] == "STARTING"
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    log = lines[-1]
    assert log["eventType"] == "manual-resync"
    assert log["knowledgeBaseId"] == "kb-123"


def test_failure_is_logged_with_context_and_re_raised(monkeypatch, capsys):
    class _FakeBedrock:
        def start_ingestion_job(self, **kwargs):
            raise RuntimeError("bedrock exploded")

    event = {
        "Records": [{
            "s3": {"bucket": {"name": "corpus"}, "object": {"key": "docs/pci.pdf"}}
        }]
    }
    monkeypatch.setenv("KB_ID", "kb-123")
    monkeypatch.setenv("DATA_SOURCE_ID", "ds-456")
    monkeypatch.setattr(handler, "_bedrock", _FakeBedrock())

    with pytest.raises(RuntimeError, match="bedrock exploded"):
        handler.handler(event, None)

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[-1]["status"] == "failed"
    assert lines[-1]["bucket"] == "corpus"
    assert lines[-1]["key"] == "docs/pci.pdf"
    assert "bedrock exploded" in lines[-1]["error"]
