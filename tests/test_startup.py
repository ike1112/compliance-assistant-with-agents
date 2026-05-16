"""Startup config hardening: fail-fast validation, env-gated verbosity,
.env.example parity, lockfile tracking.

Mirrors tests/test_agent_ids.py monkeypatch conventions. The agent-id
leg stubs sys.modules['boto3'] exactly as that file does — the
agent-id resolution algorithm is owned/covered there; this phase only
checks that the startup contract exercises it.

.env.example parity convention: a literal env-key read is one of
os.getenv("K"), os.environ.get("K")/os.environ["K"], or
<recv>.get("K")/<recv>["K"] where <recv> is the conventional name
`env` or `environ` (e.g. an injected env Mapping parameter). Any such
key under src/ must appear in .env.example.
"""
import ast
import importlib
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from compliance_assistant.startup import (
    crew_verbose_enabled,
    validate_startup_config,
)

# compliance_assistant.main imports the crew stack (crewai / crewai_tools),
# which is not present in the documented base test interpreter
# (PYTHONPATH=src python -m pytest). Stub that chain in sys.modules so the
# entry-point control-flow tests run anywhere — same sys.modules-stub
# convention tests/test_agent_ids.py uses for boto3. None of these tests
# exercise crewai itself; they assert main.py's own validation ordering.
_CREW_PKGS = (
    "crewai",
    "crewai.project",
    "crewai.tasks",
    "crewai.tasks.conditional_task",
    "crewai_tools",
    "crewai_tools.aws",
    "crewai_tools.aws.bedrock",
    "crewai_tools.aws.bedrock.agents",
    "crewai_tools.aws.bedrock.agents.invoke_agent_tool",
)


def _install_crew_stubs(monkeypatch):
    for name in _CREW_PKGS:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    _passthru = lambda x: x  # noqa: E731 - decorator identity
    crewai = sys.modules["crewai"]
    crewai.Agent = crewai.Crew = crewai.Task = type("_Stub", (), {})
    proj = sys.modules["crewai.project"]
    proj.CrewBase = proj.agent = proj.crew = proj.task = _passthru
    sys.modules["crewai.tasks.conditional_task"].ConditionalTask = type(
        "ConditionalTask", (), {}
    )
    sys.modules[
        "crewai_tools.aws.bedrock.agents.invoke_agent_tool"
    ].BedrockInvokeAgentTool = type("BedrockInvokeAgentTool", (), {})


@pytest.fixture
def cli(monkeypatch):
    """compliance_assistant.main, imported fresh with the crew stack
    stubbed so importing it has no heavy/real dependency."""
    _install_crew_stubs(monkeypatch)
    import compliance_assistant.crew as crew_mod
    import compliance_assistant.main as main_mod

    importlib.reload(crew_mod)
    importlib.reload(main_mod)
    return main_mod


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"

_VALID_AGENT_ENV = {"AGENT_ID": "AG123", "AGENT_ALIAS_ID": "AL456"}


def _good_env(**overrides):
    env = {"TOPIC": "PCI DSS", "MODEL": "bedrock/x"}
    env.update(overrides)
    return env


# --- CHECK 1: startup raises for missing/blank/whitespace/placeholder ---
# for TOPIC, MODEL, and the agent-id resolution path -----------------------

@pytest.mark.parametrize("var", ["TOPIC", "MODEL"])
@pytest.mark.parametrize(
    "bad",
    ["", "   ", "\t\n", "replace-with-something"],
    ids=["empty", "whitespace", "ws-tabs", "placeholder"],
)
def test_blank_or_placeholder_required_var_is_rejected(var, bad):
    env = _good_env(**{var: bad})
    with pytest.raises(RuntimeError):
        validate_startup_config(env)


@pytest.mark.parametrize("var", ["TOPIC", "MODEL"])
def test_missing_required_var_is_rejected(var):
    env = _good_env()
    del env[var]
    with pytest.raises(RuntimeError):
        validate_startup_config(env)


def test_agent_id_resolution_path_placeholder_is_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setenv("AGENT_ID", "replace-with-your-amazon-bedrock-agent-id")
    monkeypatch.setenv("AGENT_ALIAS_ID", "whatever")
    with pytest.raises(RuntimeError):
        validate_startup_config(_good_env())


def test_agent_id_resolution_path_missing_is_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_ALIAS_ID", raising=False)
    with pytest.raises(RuntimeError):
        validate_startup_config(_good_env())


def test_fully_valid_config_passes(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setenv("AGENT_ID", _VALID_AGENT_ENV["AGENT_ID"])
    monkeypatch.setenv("AGENT_ALIAS_ID", _VALID_AGENT_ENV["AGENT_ALIAS_ID"])
    assert validate_startup_config(_good_env()) is None


# --- CHECK 1: entry points validate first, before building the crew, ------
# and import is side-effect-free ------------------------------------------

class _Sentinel(Exception):
    pass


@pytest.mark.parametrize("entry", ["run", "train", "replay", "test"])
def test_entry_point_validates_before_building_crew(entry, cli, monkeypatch):
    built = []

    class _Spy:
        def __init__(self, *a, **k):
            built.append(True)

    def _raise(_env):
        raise _Sentinel()

    monkeypatch.setattr(cli, "validate_startup_config", _raise)
    monkeypatch.setattr(cli, "ComplianceAssistant", _Spy)
    monkeypatch.setattr(sys, "argv", [entry, "1", "x"])

    with pytest.raises(_Sentinel):
        getattr(cli, entry)()
    assert built == [], f"{entry}() built the crew before validating config"


def test_importing_main_has_no_validation_side_effect(cli, monkeypatch):
    # With TOPIC unset, a module-level validation would raise on import.
    # Function-scoped validation must let the (re)import succeed cleanly.
    monkeypatch.delenv("TOPIC", raising=False)
    importlib.reload(cli)  # re-executes the module body; must not raise


# --- CHECK 2: crew verbosity follows an env flag, defaults OFF -------------

def test_crew_verbose_defaults_off():
    assert crew_verbose_enabled({}) is False


@pytest.mark.parametrize("val", ["", "   ", "0", "false", "no", "off", "maybe"])
def test_crew_verbose_off_values(val):
    assert crew_verbose_enabled({"CREW_VERBOSE": val}) is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "Yes", " on "])
def test_crew_verbose_on_values(val):
    assert crew_verbose_enabled({"CREW_VERBOSE": val}) is True


# --- CHECK 3: .env.example parity -----------------------------------------

_ENV_RECEIVERS = {"env", "environ"}


def _is_os_environ(node: ast.AST) -> bool:
    # matches the `os.environ` attribute access
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _const_str(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _env_keys_in_source(tree: ast.AST) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(tree):
        # os.getenv("K") / os.environ.get("K") / <recv>.get("K")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            fn = node.func
            recv = fn.value
            is_getenv = (
                fn.attr == "getenv"
                and isinstance(recv, ast.Name)
                and recv.id == "os"
            )
            is_mapping_get = fn.attr == "get" and (
                _is_os_environ(recv)
                or (isinstance(recv, ast.Name) and recv.id in _ENV_RECEIVERS)
            )
            if (is_getenv or is_mapping_get) and node.args:
                k = _const_str(node.args[0])
                if k is not None:
                    keys.add(k)
        # os.environ["K"] / env["K"]
        elif isinstance(node, ast.Subscript):
            recv = node.value
            if _is_os_environ(recv) or (
                isinstance(recv, ast.Name) and recv.id in _ENV_RECEIVERS
            ):
                k = _const_str(node.slice)
                if k is not None:
                    keys.add(k)
    return keys


def _scanned_src_env_keys() -> set[str]:
    keys: set[str] = set()
    for py in _SRC.rglob("*.py"):
        keys |= _env_keys_in_source(ast.parse(py.read_text(encoding="utf-8")))
    return keys


def _env_example_keys() -> set[str]:
    keys = set()
    for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"([A-Z][A-Z0-9_]*)=", line)
        if m:
            keys.add(m.group(1))
    return keys


def test_env_example_parity():
    scanned = _scanned_src_env_keys()
    documented = _env_example_keys()
    missing = scanned - documented
    assert not missing, (
        f"env keys read under src/ but absent from .env.example: "
        f"{sorted(missing)}"
    )


def test_parity_scanner_sees_this_phase_keys():
    # Guards the exact failure mode an adversarial review flagged: if the
    # scanner ever stops seeing the injected-`env` Mapping reads, CHECK 3
    # would silently go vacuous for this phase's own keys.
    scanned = _scanned_src_env_keys()
    for key in ("CREW_VERBOSE", "MODEL", "TOPIC"):
        assert key in scanned, f"parity scanner failed to detect {key}"


# --- CHECK 4 (tracked half): uv.lock is git-tracked -----------------------

def test_uv_lock_is_git_tracked():
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "uv.lock"],
            cwd=_REPO_ROOT,
            capture_output=True,
        )
    except (FileNotFoundError, OSError):
        pytest.skip("git not available")
    if proc.returncode != 0 and not (_REPO_ROOT / ".git").exists():
        pytest.skip("not a git work tree")
    assert proc.returncode == 0, "uv.lock is not tracked by git"
