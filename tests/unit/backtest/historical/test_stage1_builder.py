"""Unit tests for stage1_builder — date-parameterized minimal-proxy.

Tests are adapted to production schema (plan template assumed an older/different
schema; see decisions.md for the production-schema migration).
"""
from datetime import date

import pandas as pd
import pytest

from tradingagents.backtest.historical.stage1_builder import build_historical_stage1
from tradingagents.schemas.reports import (
    MacroReport, NewsReport, RiskReport, TechnicalReport,
)


def _sample_panel_row(quarter_end: date, overrides: dict | None = None) -> pd.DataFrame:
    """1-row panel for one quarter, with default values."""
    base = {
        "dgs2_pct": 4.0, "dgs5_pct": 4.2, "dgs10_pct": 4.4, "dgs30_pct": 4.6,
        "spread_10y_2y_bps": 40.0, "spread_30y_5y_bps": 40.0,
        "cpi_yoy": 2.5, "core_cpi_yoy": 2.0,
        "pce_yoy": 2.2, "core_pce_yoy": 2.0,
        "cpi_3mo_ann": 2.5,
        "breakeven_5y5y": 2.3, "michigan_1y": 3.0,
        "real_yield_10y_pct": 0.5,
        "cfnai": 0.0, "cfnai_3m_avg": 0.0,
        "nfci": -0.5, "anfci": -0.5, "gdp_nowcast": 2.0,
        "unrate": 4.0, "sahm_rule_triggered": 0.0,
        "baa_aaa_bps": 80.0, "baa_10y_bps": 200.0,
        "usdkrw": 1250.0, "dxy_dtwexm": 100.0,
        "foreign_flow_z": 0.0,
        "vix": 18.0, "skew": 130.0,
        "realized_vol_60d_spx_pct": 15.0, "move_proxy_pct": 80.0,
        "vrp_pct": 0.01, "sector_dispersion": 0.02,
        "kospi200_pbr": 1.0, "kospi200_per": 14.0, "kospi200_div_yield": 2.0,
        "shiller_cape": 25.0, "usrec": 0.0,
        "tb3ms_pct": 4.0,
    }
    if overrides:
        base.update(overrides)
    return pd.DataFrame([base], index=pd.to_datetime([quarter_end]))


def test_build_historical_stage1_returns_4_reports() -> None:
    """Returns dict with 4 _AnalystReport pydantic instances."""
    panel = _sample_panel_row(date(2010, 3, 31))
    state = build_historical_stage1(date(2010, 3, 31), panel)
    assert isinstance(state, dict)
    assert isinstance(state["macro_report"], MacroReport)
    assert isinstance(state["risk_report"], RiskReport)
    assert isinstance(state["technical_report"], TechnicalReport)
    assert isinstance(state["news_report"], NewsReport)


def test_build_historical_stage1_populates_yield_curve() -> None:
    panel = _sample_panel_row(date(2010, 3, 31), {
        "spread_10y_2y_bps": 80.0, "spread_30y_5y_bps": 50.0,
    })
    state = build_historical_stage1(date(2010, 3, 31), panel)
    yc = state["macro_report"].yield_curve
    assert yc.spread_10y_2y_bps == 80.0
    assert yc.spread_30y_5y_bps == 50.0


def test_build_historical_stage1_populates_cfnai() -> None:
    """CFNAI fold-in (PR1 C3) — FinancialConditionsSnapshot.cfnai + cfnai_3m_avg."""
    panel = _sample_panel_row(date(2010, 3, 31), {
        "cfnai": -0.4, "cfnai_3m_avg": -0.3,
    })
    state = build_historical_stage1(date(2010, 3, 31), panel)
    fci = state["macro_report"].financial_conditions
    assert fci.cfnai == -0.4
    assert fci.cfnai_3m_avg == -0.3


def test_build_historical_stage1_news_is_sentinel() -> None:
    """news_report 의 LLM-derived field 는 baseline sentinel."""
    panel = _sample_panel_row(date(2010, 3, 31))
    state = build_historical_stage1(date(2010, 3, 31), panel)
    news = state["news_report"]
    # news_sentiment 의 sentiment_dispersion 은 baseline 0.3
    assert news.news_sentiment.sentiment_dispersion == 0.3
    # release_surprise 의 surprise_index_30d 는 baseline 0.0
    assert news.release_surprise.surprise_index_30d == 0.0


def test_build_historical_stage1_pre_gdpnow_era_uses_default() -> None:
    """GDPNOW 가 2011+ — pre-2011 era 의 panel 에서 NaN → baseline 2.0."""
    panel = _sample_panel_row(date(2005, 3, 31), {"gdp_nowcast": None})
    state = build_historical_stage1(date(2005, 3, 31), panel)
    gdp = state["macro_report"].gdp_nowcast
    assert gdp.nowcast_pct == 2.0  # baseline default
