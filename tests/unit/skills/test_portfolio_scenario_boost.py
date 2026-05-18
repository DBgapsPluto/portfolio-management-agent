"""Phase C — sub_category-based scenario boost in candidate_selector."""
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import ETFEntry, Universe
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
from tradingagents.skills.portfolio.factor_scorer import FactorPanel
from tradingagents.skills.portfolio.sub_category import (
    SCENARIO_SUBCATEGORY_BOOST, boost_for_scenario, log_boost,
)


def test_boost_for_scenario_known():
    boost = boost_for_scenario("ai_concentration")
    assert "semiconductor" in boost
    assert boost["us_tech_nasdaq"] >= 1.5


def test_boost_for_scenario_unknown_or_none():
    assert boost_for_scenario(None) == {}
    assert boost_for_scenario("nonexistent") == {}


def test_log_boost_neutral_is_zero():
    assert log_boost(None, None) == 0.0
    assert log_boost("goldilocks", None) == 0.0
    assert log_boost("goldilocks", "unknown_label") == 0.0


def test_log_boost_positive_for_favored_subcategory():
    # ai_concentration → ai_robotics 2.0배 → ln(2) ≈ 0.69
    assert log_boost("ai_concentration", "ai_robotics") == pytest.approx(math.log(2.0), 0.01)


def test_log_boost_penalty_for_disfavored_subcategory():
    # global_credit → us_high_yield 0.3배 → ln(0.3) ≈ -1.20
    assert log_boost("global_credit", "us_high_yield") == pytest.approx(math.log(0.3), 0.01)


def _make_universe_with_subcat() -> Universe:
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="KODEX 반도체", aum_krw=10e12,
                 underlying_index="x", bucket="위험", category="국내주식_섹터",
                 sub_category="semiconductor"),
        ETFEntry(ticker="A222222", name="KODEX 배당", aum_krw=10e12,
                 underlying_index="y", bucket="위험", category="국내주식_섹터",
                 sub_category="factor_value_dividend"),
    ])


def _trivial_returns(tickers):
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    return pd.DataFrame({t: rng.normal(0.0005, 0.012, 200) for t in tickers}, index=idx)


def _trivial_panel(tickers):
    return {
        t: FactorPanel(
            skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
            realized_vol_60d=0.15, sharpe_60d=0.3,
            log_aum=math.log(10e12),
        )
        for t in tickers
    }


def test_ai_scenario_boosts_semiconductor_over_dividend():
    universe = _make_universe_with_subcat()
    target = BucketTarget(
        kr_equity=1.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.0, rationale="t",
    )
    tickers = ["A111111", "A222222"]
    returns = _trivial_returns(tickers)
    panel = _trivial_panel(tickers)

    # 시나리오 없을 때: 두 ETF 점수 비슷 (양쪽 모두 동일 panel)
    no_scenario = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        per_bucket_n=1, returns=returns, factor_panel=panel,
        regime_quadrant="growth_disinflation", regime_confidence=0.8,
        dominant_scenario=None,
    )
    # tie-breaking depends on dict order, just verify both could be picked

    # ai_concentration: semiconductor 강한 boost → A111111 우선
    ai = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        per_bucket_n=1, returns=returns, factor_panel=panel,
        regime_quadrant="growth_disinflation", regime_confidence=0.8,
        dominant_scenario="ai_concentration",
    )
    assert ai.bucket_to_tickers["kr_equity"] == ["A111111"]

    # broad_recession: factor_value_dividend boost → A222222 우선
    rec = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        per_bucket_n=1, returns=returns, factor_panel=panel,
        regime_quadrant="recession_disinflation", regime_confidence=0.8,
        dominant_scenario="broad_recession",
    )
    assert rec.bucket_to_tickers["kr_equity"] == ["A222222"]


def test_no_subcategory_means_no_boost_effect():
    """sub_category가 None인 ETF는 dominant_scenario에 상관없이 영향 없음."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="X", aum_krw=10e12,
                 underlying_index="x", bucket="위험", category="국내주식_섹터",
                 sub_category=None),
        ETFEntry(ticker="A222222", name="Y", aum_krw=10e12,
                 underlying_index="y", bucket="위험", category="국내주식_섹터",
                 sub_category=None),
    ])
    target = BucketTarget(
        kr_equity=1.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.0, rationale="t",
    )
    tickers = ["A111111", "A222222"]
    returns = _trivial_returns(tickers)
    panel = _trivial_panel(tickers)

    chosen_no_scenario = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        per_bucket_n=2, returns=returns, factor_panel=panel,
        dominant_scenario=None,
    ).bucket_to_tickers["kr_equity"]

    chosen_with_scenario = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        per_bucket_n=2, returns=returns, factor_panel=panel,
        dominant_scenario="ai_concentration",
    ).bucket_to_tickers["kr_equity"]

    # sub_category 없으면 boost 효과 없음 — 같은 순서
    assert chosen_no_scenario == chosen_with_scenario


def test_all_boost_values_in_safe_range():
    """모든 boost 값이 [0.3, 2.0] 범위 — 극단 값으로 다른 factor 가리지 않도록."""
    for scenario, boosts in SCENARIO_SUBCATEGORY_BOOST.items():
        for label, value in boosts.items():
            assert 0.3 <= value <= 2.0, (
                f"{scenario}.{label} = {value} outside safe range [0.3, 2.0]"
            )
