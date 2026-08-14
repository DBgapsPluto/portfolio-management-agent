from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.observability.replay import restore_state


def test_restore_state_funnels_portfolio_dials_use_bl_true(tmp_path):
    # C4: restore_state built state via _create_empty_state, which never sets
    # portfolio_dials — so replayed allocator runs always silently took the
    # use_bl=False fallback (old project_to_band path) instead of the live
    # BL-default path, regardless of the live config. Mirror
    # TradingAgentsGraph.run's funnel (trading_graph.py:141-143) here too.
    (tmp_path / "2026-06-20").mkdir()
    state, missing = restore_state(
        "2026-06-20", "allocator", "universe.json", base=tmp_path,
    )
    assert state["portfolio_dials"] == dict(DEFAULT_CONFIG["rebalance"])
    assert state["portfolio_dials"]["use_bl"] is True
