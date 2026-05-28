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
    BOOST_BY_CYCLE, BOOST_BY_KR, BOOST_BY_TAIL,
    boost_for_scenario, compose_boost, log_boost,
)


def test_compose_boost_multiplicative():
    # D cycle stagflation × N tail × F → gold 1.8, inflation_linked 1.6
    composed = compose_boost("D", "N", "F")
    assert composed["gold"] == pytest.approx(1.8)
    assert composed["inflation_linked"] == pytest.approx(1.6)

    # C cycle × T tail → us_treasury 1.3 × 1.5 = 1.95
    composed = compose_boost("C", "T", "F")
    assert composed["us_treasury"] == pytest.approx(1.3 * 1.5)


def test_boost_for_scenario_legacy_name_maps_to_cell():
    # legacy "stagflation" → (D, N, F) → D 축의 D-cycle boosts
    boost = boost_for_scenario("stagflation")
    assert "gold" in boost
    assert boost["gold"] >= 1.5


def test_boost_for_scenario_unknown_or_none():
    assert boost_for_scenario(None) == {}
    assert boost_for_scenario("nonexistent_xyz") == {}


def test_log_boost_neutral_is_zero():
    assert log_boost(None, None) == 0.0
    assert log_boost("goldilocks", None) == 0.0
    assert log_boost("goldilocks", "unknown_label") == 0.0


def test_log_boost_positive_for_favored_subcategory():
    # legacy stagflation → (D, N, F) → gold 1.8 → ln(1.8)
    assert log_boost("stagflation", "gold") == pytest.approx(math.log(1.8), abs=0.01)


def test_log_boost_penalty_for_disfavored_subcategory():
    # legacy global_credit → (C, T, F) → us_high_yield 0.4 (T tail) → ln(0.4)
    assert log_boost("global_credit", "us_high_yield") == pytest.approx(math.log(0.4), abs=0.01)


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


def test_kr_boom_scenario_boosts_semiconductor_over_dividend():
    universe = _make_universe_with_subcat()
    target = BucketTarget(
        weights={
            "kr_equity": 1.0, "global_equity": 0.0, "precious_metals": 0.0,
            "cyclical_commodity_fx": 0.0, "kr_bond": 0.0,
            "credit": 0.0, "global_duration": 0.0, "cash_mmf": 0.0,
        },
        rationale="t",
    )
    tickers = ["A111111", "A222222"]
    returns = _trivial_returns(tickers)
    panel = _trivial_panel(tickers)

    # KR boom: semiconductor 1.7배 → A111111 (semiconductor) 우선
    kr_boom = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        per_bucket_n=1, returns=returns, factor_panel=panel,
        regime_quadrant="growth_disinflation", regime_confidence=0.8,
        dominant_scenario="kr_boom",  # legacy 이름, A_N_boom으로 매핑
    )
    assert kr_boom.bucket_to_tickers["kr_equity"] == ["A111111"]

    # broad_recession: factor_value_dividend 1.3 → A222222 우선
    # (Factor model PR: cell key path 제거 — legacy name 만 사용)
    rec = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        per_bucket_n=1, returns=returns, factor_panel=panel,
        regime_quadrant="recession_disinflation", regime_confidence=0.8,
        dominant_scenario="broad_recession",  # legacy name
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
        weights={
            "kr_equity": 1.0, "global_equity": 0.0, "precious_metals": 0.0,
            "cyclical_commodity_fx": 0.0, "kr_bond": 0.0,
            "credit": 0.0, "global_duration": 0.0, "cash_mmf": 0.0,
        },
        rationale="t",
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
        dominant_scenario="kr_boom",
    ).bucket_to_tickers["kr_equity"]

    # sub_category 없으면 boost 효과 없음 — 같은 순서
    assert chosen_no_scenario == chosen_with_scenario


def test_all_axis_boost_values_in_safe_range():
    """3축 boost 모두 [0.3, 2.0]. compose 후 [0.3*0.3, 2*2]=[0.09, 4.0] 가능하나
    실제 caller에서 dominant cell이 한 axis별 single value라 outlier 합성 드묾."""
    for axis_dict in (BOOST_BY_CYCLE, BOOST_BY_KR, BOOST_BY_TAIL):
        for coord, boosts in axis_dict.items():
            for label, value in boosts.items():
                assert 0.3 <= value <= 2.0, (
                    f"{coord}.{label} = {value} outside [0.3, 2.0]"
                )
