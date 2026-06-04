"""Verify db_gaps.yaml preset loads + all skills are registered."""
from pathlib import Path

import tradingagents.skills._registry_init  # noqa: F401 — register all skills
from tradingagents.presets.loader import PresetLoader


def test_db_gaps_preset_loads():
    preset = PresetLoader.from_yaml(Path("presets/db_gaps.yaml"))
    assert preset.name == "db_gaps"
    assert preset.capital_krw == 1_000_000_000
    # 5 stages (Stage 4 risk_debate 제거): analysts, research_debate, allocation, validation, finalize
    assert len(preset.stages) == 5
    stage_ids = [s.id for s in preset.stages]
    assert stage_ids == [
        "analysts", "research_debate", "allocation",
        "validation", "finalize",
    ]


def test_db_gaps_preset_has_4_analysts():
    preset = PresetLoader.from_yaml(Path("presets/db_gaps.yaml"))
    analysts_stage = next(s for s in preset.stages if s.id == "analysts")
    assert len(analysts_stage.agents) == 4
    agent_ids = {a.id for a in analysts_stage.agents}
    assert agent_ids == {"macro_quant", "market_risk", "technical", "macro_news"}
