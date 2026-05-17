"""Offline enforcement for the whole gate.

Any test marked `gate` runs with network + subprocess egress blocked, so
the deterministic-offline guarantee is structural (not a single
monkeypatch in one file). Non-gate tests (e.g. the gold-frozen
provenance guard, which legitimately shells out to `git`) are
unaffected.
"""
from __future__ import annotations

import socket
import subprocess

import pytest


def _blocked_net(*_a, **_k):
    raise AssertionError("gate attempted network I/O (must be offline)")


def _blocked_proc(*_a, **_k):
    raise AssertionError(
        "gate attempted to spawn a subprocess (must be offline/local)")


@pytest.fixture(autouse=True)
def _offline_for_gate(request, monkeypatch):
    if request.node.get_closest_marker("gate") is None:
        return
    monkeypatch.setattr(socket, "socket", _blocked_net)
    monkeypatch.setattr(socket, "create_connection", _blocked_net)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked_net)
    monkeypatch.setattr(subprocess, "run", _blocked_proc)
    monkeypatch.setattr(subprocess, "Popen", _blocked_proc)
    monkeypatch.setattr(subprocess, "check_output", _blocked_proc)
