"""load_config: typed, validated, fails loud on a malformed bar file."""
import json

import pytest

from review_gate.config import GateConfig, GateConfigError, load_config


def _write(tmp_path, obj):
    p = tmp_path / "review-gate.config.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_loads_typed_config(tmp_path):
    p = _write(tmp_path, {
        "mutation_floor": 0.80,
        "coverage_floor": 0.90,
        "phases": {"3": {"pure_logic_paths": ["a.py"], "frozen_fixture_paths": ["g/"]}},
    })
    cfg = load_config(p)
    assert isinstance(cfg, GateConfig)
    assert cfg.mutation_floor == 0.80
    assert cfg.phases["3"].pure_logic_paths == ["a.py"]
    assert cfg.phases["3"].frozen_fixture_paths == ["g/"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(GateConfigError):
        load_config(tmp_path / "nope.json")


def test_bad_json_raises(tmp_path):
    p = tmp_path / "review-gate.config.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(GateConfigError):
        load_config(p)


@pytest.mark.parametrize("bad", [
    {"coverage_floor": 0.9, "phases": {}},                       # no mutation_floor
    {"mutation_floor": 1.5, "coverage_floor": 0.9, "phases": {}}, # out of range
    {"mutation_floor": 0.8, "coverage_floor": 0.9, "phases": {"3": {}}},  # phase missing keys
    {"mutation_floor": 0.8, "coverage_floor": 0.9},               # no phases
])
def test_schema_violations_raise(tmp_path, bad):
    with pytest.raises(GateConfigError):
        load_config(_write(tmp_path, bad))
