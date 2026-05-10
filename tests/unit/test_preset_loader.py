from pathlib import Path

import pytest

from tradingagents.presets.loader import PresetLoader, PresetLoadError
from tradingagents.skills.registry import (
    register_skill, clear_registry,
)


@pytest.fixture
def setup_skills():
    clear_registry()

    @register_skill(name="fetch_fred_series", category="macro")
    def f(): pass

    @register_skill(name="classify_regime", category="macro")
    def g(): pass


def test_load_validates_skills_exist(setup_skills):
    p = PresetLoader.from_yaml(Path("tests/fixtures/preset_minimal.yaml"))
    assert p.name == "test_preset"
    assert len(p.stages) == 1


def test_load_rejects_unknown_skill(tmp_path):
    clear_registry()
    bad = tmp_path / "bad.yaml"
    bad.write_text("""
name: bad
universe: x
capital_krw: 1
stages:
  - id: s1
    agents:
      - id: a1
        skills: [nonexistent_skill]
        output_schema: MacroReport
""")
    with pytest.raises(PresetLoadError, match="unknown skill"):
        PresetLoader.from_yaml(bad)
