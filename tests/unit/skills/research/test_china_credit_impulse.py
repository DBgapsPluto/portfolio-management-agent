"""Tests for F12 china_credit_impulse module (Biggs-Mayer-Pick 2010 JMCB)."""
from unittest.mock import patch
from datetime import date
import pandas as pd
from tradingagents.skills.research.china_credit_impulse import compute_china_credit_impulse


def test_biggs_mayer_pick_with_6_quarters():
    # ratio_t = 230, prev = 228, t-4 = 220, t-5 = 218
    # delta_t = 2, delta_{t-4} = 2 → impulse = 0
    series = pd.Series(
        [218.0, 220.0, 222.0, 224.0, 228.0, 230.0],
        index=pd.to_datetime(["2025-09-30", "2025-12-31", "2026-03-31",
                              "2026-06-30", "2026-09-30", "2026-12-31"]),
    )
    with patch("tradingagents.skills.research.china_credit_impulse.fetch_bis_china_credit",
               return_value=series):
        result = compute_china_credit_impulse(date(2026, 12, 31))
    assert result is not None
    assert abs(result["impulse"]) < 0.5
    assert result["ratio"] == 230.0


def test_biggs_mayer_pick_accelerating_credit():
    # delta_t = 4 (faster), delta_{t-4} = 2 (slower) → positive impulse
    # s = [218, 220, 222, 224, 228, 232]
    # delta_t = 232-228 = 4, delta_{t-4} = 220-218 = 2
    # credit_t_minus_4 = 220
    # impulse = (4-2)/220 * 100 = 0.909...
    series = pd.Series(
        [218.0, 220.0, 222.0, 224.0, 228.0, 232.0],
        index=pd.to_datetime(["2025-09-30", "2025-12-31", "2026-03-31",
                              "2026-06-30", "2026-09-30", "2026-12-31"]),
    )
    with patch("tradingagents.skills.research.china_credit_impulse.fetch_bis_china_credit",
               return_value=series):
        result = compute_china_credit_impulse(date(2026, 12, 31))
    assert result is not None
    assert result["impulse"] > 0.5


def test_insufficient_history_returns_none():
    series = pd.Series([220.0], index=pd.to_datetime(["2026-12-31"]))
    with patch("tradingagents.skills.research.china_credit_impulse.fetch_bis_china_credit",
               return_value=series):
        assert compute_china_credit_impulse(date(2026, 12, 31)) is None


def test_fetch_failure_returns_none():
    with patch("tradingagents.skills.research.china_credit_impulse.fetch_bis_china_credit",
               side_effect=ConnectionError("network down")):
        assert compute_china_credit_impulse(date(2026, 12, 31)) is None


def test_result_contains_expected_keys():
    series = pd.Series(
        [210.0, 215.0, 218.0, 221.0, 225.0, 230.0],
        index=pd.to_datetime(["2025-09-30", "2025-12-31", "2026-03-31",
                              "2026-06-30", "2026-09-30", "2026-12-31"]),
    )
    with patch("tradingagents.skills.research.china_credit_impulse.fetch_bis_china_credit",
               return_value=series):
        result = compute_china_credit_impulse(date(2026, 12, 31))
    assert result is not None
    # last_date: staleness stamp 용 실제 분기 말일 (2026-06-04 추가)
    assert set(result.keys()) == {"impulse", "ratio", "yoy", "last_date"}
    assert result["ratio"] == 230.0
    assert pd.Timestamp(result["last_date"]) == pd.Timestamp("2026-12-31")
