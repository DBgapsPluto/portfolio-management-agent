"""Test that TradingAgentsGraph instantiates without errors when preset exists."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import yaml

from tradingagents.default_config import DEFAULT_CONFIG


def test_trading_graph_init_smoke(tmp_path, monkeypatch):
    """Verify TradingAgentsGraph builds when preset YAML and skills are available."""
    # Create minimal preset YAML
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir()
    preset_path = preset_dir / "test_preset.yaml"
    preset = {
        "name": "test_preset",
        "universe": "data/universe.json",
        "capital_krw": 1_000_000_000,
        "stages": [
            {
                "id": "analysts", "parallel": True,
                "agents": [
                    {"id": "macro_quant", "skills": ["fetch_fred_series"]},
                ],
            },
        ],
    }
    preset_path.write_text(yaml.dump(preset), encoding="utf-8")

    # Patch config to use tmp preset dir
    test_config = dict(DEFAULT_CONFIG)
    test_config["preset_dir"] = str(preset_dir)
    test_config["llm_provider"] = "openai"
    test_config["deep_think_llm"] = "gpt-4"
    test_config["quick_think_llm"] = "gpt-4-mini"

    # Mock LLM client to avoid real API key requirement
    with patch("tradingagents.graph.trading_graph.create_llm_client") as mock_client:
        mock_client.return_value.get_llm.return_value = MagicMock()
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        tg = TradingAgentsGraph(preset_name="test_preset", config=test_config)
        assert tg.preset.name == "test_preset"
        assert tg.graph is not None
