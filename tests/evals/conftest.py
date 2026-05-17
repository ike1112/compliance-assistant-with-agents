"""Offline enforcement for the whole gate.

Any test marked `gate` runs with network + subprocess egress blocked, so
the deterministic-offline guarantee is structural (not a single
monkeypatch in one file). Non-gate tests (e.g. the gold-frozen
provenance guard, which legitimately shells out to `git`) are
unaffected.
"""
from __future__ import annotations

import os
import socket
import subprocess

import pytest


def _blocked_net(*_a, **_k):
    raise AssertionError("gate attempted network I/O (must be offline)")


def _blocked_proc(*_a, **_k):
    raise AssertionError(
        "gate attempted to spawn a subprocess (must be offline/local)")


# Every documented egress primitive, so the offline guarantee is not
# bypassable through an un-patched named API.
_NET_ATTRS = ("socket", "create_connection", "getaddrinfo")
_PROC_ATTRS = ("run", "Popen", "call", "check_call", "check_output")
_OS_PROC_ATTRS = ("system", "popen")


@pytest.fixture(autouse=True)
def _offline_for_gate(request, monkeypatch):
    if request.node.get_closest_marker("gate") is None:
        return
    for a in _NET_ATTRS:
        monkeypatch.setattr(socket, a, _blocked_net)
    for a in _PROC_ATTRS:
        monkeypatch.setattr(subprocess, a, _blocked_proc)
    for a in _OS_PROC_ATTRS:
        monkeypatch.setattr(os, a, _blocked_proc)
