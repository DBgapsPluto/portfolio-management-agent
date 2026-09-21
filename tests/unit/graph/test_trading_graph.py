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


def test_run_funnels_live_dials_into_state(tmp_path):
    """LIVE wiring: TradingAgentsGraph.run() copies config['rebalance'] dials
    (incl. use_bl=True) into state['portfolio_dials'] so the allocator runs BL.

    This is the ONLY place a run receives use_bl=True — bare-state callers (unit
    tests) never set portfolio_dials and stay on the node-default old path.
    """
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    # Build a bare instance without running __init__ (avoids LLM/preset wiring).
    tg = TradingAgentsGraph.__new__(TradingAgentsGraph)
    tg.config = dict(DEFAULT_CONFIG)
    tg.config["universe_path"] = "data/universe.json"
    tg.preset_name = "db_gaps"

    captured = {}

    class _FakeGraph:
        def invoke(self, state, config=None):
            captured["state"] = state
            return state

    tg.graph = _FakeGraph()

    # archive_metadata may touch disk — patch it to a no-op.
    with patch("tradingagents.graph.trading_graph.archive_metadata", lambda *a, **k: None):
        tg.run(as_of_date="2026-05-25", capital_krw=1_000_000_000)

    dials = captured["state"]["portfolio_dials"]
    assert dials["use_bl"] is True
    assert dials["bl_turnover_cap"] == 0.50
