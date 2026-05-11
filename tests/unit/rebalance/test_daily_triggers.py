"""Unit tests for daily trigger evaluator."""
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.rebalance.daily_triggers import _ConditionParser


class TestConditionParser:
    def test_simple_gt(self):
        assert _ConditionParser("vix > 30", {"vix": 35}).evaluate() is True
        assert _ConditionParser("vix > 30", {"vix": 25}).evaluate() is False

    def test_simple_lt_negative(self):
        assert _ConditionParser(
            "spread_10y_2y_bps < -50", {"spread_10y_2y_bps": -60}
        ).evaluate() is True
        assert _ConditionParser(
            "spread_10y_2y_bps < -50", {"spread_10y_2y_bps": -40}
        ).evaluate() is False

    def test_or_short_circuit(self):
        ctx = {"vix": 20, "vix_change_1d": 0.25}
        assert _ConditionParser(
            "vix > 30 OR vix_change_1d > 0.20", ctx
        ).evaluate() is True

    def test_or_both_false(self):
        ctx = {"vix": 20, "vix_change_1d": 0.10}
        assert _ConditionParser(
            "vix > 30 OR vix_change_1d > 0.20", ctx
        ).evaluate() is False

    def test_and(self):
        ctx = {"vix": 35, "vkospi": 30}
        assert _ConditionParser(
            "vix > 30 AND vkospi > 25", ctx
        ).evaluate() is True
        ctx2 = {"vix": 35, "vkospi": 20}
        assert _ConditionParser(
            "vix > 30 AND vkospi > 25", ctx2
        ).evaluate() is False

    def test_unknown_var_raises(self):
        with pytest.raises(KeyError):
            _ConditionParser("foo > 1", {}).evaluate()

    def test_malformed_raises(self):
        with pytest.raises(ValueError):
            _ConditionParser("vix bad 30", {"vix": 1}).evaluate()

    def test_no_eval_attempt(self):
        """Parser must reject Python code (no eval/exec)."""
        with pytest.raises(ValueError):
            _ConditionParser(
                "__import__('os').system('echo pwn') > 0", {}
            ).evaluate()


def test_run_no_triggers_fired():
    """All-quiet day: no triggers fire."""
    from tradingagents.rebalance import daily_triggers

    fake_vix = MagicMock(current_value=18.0)
    fake_vkospi = MagicMock(current_value=15.0)

    with patch.object(daily_triggers, "fetch_volatility_index",
                      side_effect=[fake_vix, fake_vkospi]), \
         patch("tradingagents.dataflows.fred.fetch_fred_series") as fred_mock, \
         patch("tradingagents.dataflows.pykrx_data.fetch_etf_snapshot_by_date") \
            as snap_mock:
        import pandas as pd
        # 2-day VIX series for vix_change_1d
        fred_mock.side_effect = [
            pd.Series([18.0, 18.5]),     # vix close 5d
            pd.Series([4.0, 4.0]),        # us_10y
            pd.Series([4.5, 4.5]),        # us_2y
        ]
        snap_mock.return_value = pd.DataFrame()

        result = daily_triggers.run(as_of="2026-06-15")
        assert result.fired == []
        assert result.suggested_action is None


def test_run_vix_spike_fires():
    from tradingagents.rebalance import daily_triggers

    fake_vix = MagicMock(current_value=35.0)  # spike
    fake_vkospi = MagicMock(current_value=15.0)

    with patch.object(daily_triggers, "fetch_volatility_index",
                      side_effect=[fake_vix, fake_vkospi]), \
         patch("tradingagents.dataflows.fred.fetch_fred_series") as fred_mock, \
         patch("tradingagents.dataflows.pykrx_data.fetch_etf_snapshot_by_date") \
            as snap_mock:
        import pandas as pd
        fred_mock.side_effect = [
            pd.Series([35.0, 35.5]),
            pd.Series([4.0, 4.0]),
            pd.Series([4.5, 4.5]),
        ]
        snap_mock.return_value = pd.DataFrame()

        result = daily_triggers.run(as_of="2026-06-15")
        assert "vix_spike" in result.fired


def test_run_vol_normalization_fires():
    """VIX dropped from 28 to 17 over 5 trading days → risk_on_proposal."""
    from tradingagents.rebalance import daily_triggers

    fake_vix = MagicMock(current_value=17.0)  # calm
    fake_vkospi = MagicMock(current_value=15.0)

    with patch.object(daily_triggers, "fetch_volatility_index",
                      side_effect=[fake_vix, fake_vkospi]), \
         patch("tradingagents.dataflows.fred.fetch_fred_series") as fred_mock, \
         patch("tradingagents.dataflows.pykrx_data.fetch_etf_snapshot_by_date") \
            as snap_mock:
        import pandas as pd
        # 6 entries: t-5=28, ..., t=17 → vix_change_5d = (17-28)/28 ≈ -0.39
        fred_mock.side_effect = [
            pd.Series([28.0, 26.0, 23.0, 20.0, 18.0, 17.0]),
            pd.Series([4.0, 4.0]),
            pd.Series([4.5, 4.5]),
        ]
        snap_mock.return_value = pd.DataFrame()

        result = daily_triggers.run(as_of="2026-06-15")
        assert "vol_normalization" in result.fired
        assert result.suggested_action == "risk_on_proposal"


def test_run_vol_normalization_does_not_fire_when_vix_high():
    """VIX dropped 40% but is still 24 (not calm) → does not fire."""
    from tradingagents.rebalance import daily_triggers

    fake_vix = MagicMock(current_value=24.0)
    fake_vkospi = MagicMock(current_value=15.0)

    with patch.object(daily_triggers, "fetch_volatility_index",
                      side_effect=[fake_vix, fake_vkospi]), \
         patch("tradingagents.dataflows.fred.fetch_fred_series") as fred_mock, \
         patch("tradingagents.dataflows.pykrx_data.fetch_etf_snapshot_by_date") \
            as snap_mock:
        import pandas as pd
        # 40 → 24 = -0.40 in 5 days, but vix still 24 (>= 18)
        fred_mock.side_effect = [
            pd.Series([40.0, 36.0, 32.0, 28.0, 26.0, 24.0]),
            pd.Series([4.0, 4.0]),
            pd.Series([4.5, 4.5]),
        ]
        snap_mock.return_value = pd.DataFrame()

        result = daily_triggers.run(as_of="2026-06-15")
        assert "vol_normalization" not in result.fired
