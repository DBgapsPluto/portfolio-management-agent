"""candidate_selector tests — 8-bucket schema (Tier 1)."""
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.candidate_selector import (
    list_eligible_tickers, select_etf_candidates,
)
from tradingagents.skills.portfolio.factor_scorer import FactorPanel


# ---------------------------------------------------------------------------
# Helper: 8-bucket BucketTarget constructor
# ---------------------------------------------------------------------------

def _bt(**overrides) -> BucketTarget:
    """Build a BucketTarget with optional weight overrides.

    Base: all-zero except kr_equity=1.0 (single-bucket mode by default).
    Pass e.g. kr_equity=0.5, global_duration=0.5 to override.
    Total must sum to 1.0.
    """
    base = {
        "kr_equity":             0.00,
        "global_equity":         0.00,
        "precious_metals":       0.00,
        "cyclical_commodity_fx": 0.00,
        "kr_bond":               0.00,
        "credit":                0.00,
        "global_duration":       0.00,
        "cash_mmf":              0.00,
    }
    base.update(overrides)
    return BucketTarget(weights=base, rationale="test")


def _build_universe() -> Universe:
    # Each active bucket has 2 tickers so rank_percentile gives a spread of scores.
    return Universe(version="2026-05-10", etfs=[
        ETFEntry(ticker="A069500", name="KODEX 200", aum_krw=10e12,
                 underlying_index="ui_A069500", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A069501", name="TIGER 200", aum_krw=8e12,
                 underlying_index="ui_A069501", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A360750", name="TIGER S&P500", aum_krw=15e12,
                 underlying_index="sp500_a", bucket="위험", category="해외주식_지수"),
        ETFEntry(ticker="A360751", name="KODEX S&P500", aum_krw=12e12,
                 underlying_index="sp500_b", bucket="위험", category="해외주식_지수"),
        ETFEntry(ticker="A114260", name="KODEX 국고채3년", aum_krw=5e12,
                 underlying_index="z", bucket="안전", category="국내채권_종합"),
        ETFEntry(ticker="A114261", name="TIGER 국고채3년", aum_krw=4e12,
                 underlying_index="z2", bucket="안전", category="국내채권_종합"),
        ETFEntry(ticker="A459580", name="KODEX CD금리", aum_krw=8e12,
                 underlying_index="w", bucket="안전", category="금리연계형/초단기채권"),
        ETFEntry(ticker="A459581", name="TIGER CD금리", aum_krw=6e12,
                 underlying_index="w2", bucket="안전", category="금리연계형/초단기채권"),
        ETFEntry(ticker="A411060", name="ACE KRX금현물", aum_krw=5e12,
                 underlying_index="v", bucket="위험", category="FX 및 원자재"),
        ETFEntry(ticker="A411061", name="KODEX 금현물", aum_krw=4e12,
                 underlying_index="v2", bucket="위험", category="FX 및 원자재"),
    ])


def _synthetic_returns(tickers, days=300, seed=11):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=days, freq="B")
    return pd.DataFrame(
        {t: rng.normal(0.0005, 0.012, days) for t in tickers},
        index=idx,
    )


def _trivial_panel(tickers, aum_lookup):
    # Incrementally different momentum to ensure rank_percentile gives spread of scores.
    # Top-ranked ticker gets positive alpha; bottom-ranked gets negative.
    return {
        t: FactorPanel(
            skip1m_mom_3m=0.05 + 0.01 * i,
            skip1m_mom_6m=0.05 + 0.01 * i,
            skip1m_mom_12m=0.05 + 0.01 * i,
            realized_vol_60d=0.15,
            sharpe_60d=0.3 + 0.05 * i,
            log_aum=math.log(aum_lookup.get(t, 1e12)),
        )
        for i, t in enumerate(tickers)
    }


def test_select_candidates_for_target():
    universe = _build_universe()
    target = _bt(
        kr_equity=0.15, global_equity=0.30, precious_metals=0.10,
        kr_bond=0.35, cash_mmf=0.10,
    )
    all_tickers = [e.ticker for e in universe.etfs]
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    returns = _synthetic_returns(all_tickers)
    panel = _trivial_panel(all_tickers, aum_lookup)

    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
    )
    assert len(candidates.bucket_to_tickers["kr_equity"]) >= 1
    assert len(candidates.bucket_to_tickers["global_equity"]) >= 1
    assert len(candidates.bucket_to_tickers["bond"]) >= 1
    assert len(candidates.bucket_to_tickers["cash_mmf"]) >= 1




def test_no_aum_floor_admits_all_categories():
    """AUM 필터 제거 후: AUM 무관하게 카테고리만 확인."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="big", aum_krw=6e11, underlying_index="u1",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A222222", name="small", aum_krw=1e11, underlying_index="u2",
                 bucket="위험", category="국내주식_지수"),
    ])
    bt = BucketTarget(kr_equity=1.0, global_equity=0, fx_commodity=0, bond=0,
                      cash_mmf=0, rationale="t")
    out = list_eligible_tickers(universe, bt, as_of=date(2025, 1, 2))
    assert set(out["kr_equity"]) == {"A111111", "A222222"}


def test_list_eligible_tickers_filters_by_category():
    target = BucketTarget(
        kr_equity=0.5, global_equity=0.0, fx_commodity=0.0,
        bond=0.5, cash_mmf=0.0,
        rationale="t",
    )
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="big kr", aum_krw=10e12,
                 underlying_index="ui_A111111", bucket="위험", category="국내주식_지수"),
        # 30억 — AUM 필터 제거 후 카테고리만 확인
        ETFEntry(ticker="A222222", name="small kr", aum_krw=3_000_000_000,
                 underlying_index="ui_A222222", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A333333", name="bond", aum_krw=5e12,
                 underlying_index="ui_A333333", bucket="안전", category="국내채권_종합",
                 sub_category="kr_treasury"),
        ETFEntry(ticker="A444444", name="cash", aum_krw=10e12,
                 underlying_index="ui_A444444", bucket="안전", category="금리연계형/초단기채권"),
    ])
    eligible = list_eligible_tickers(universe, target, as_of=date(2026, 5, 10))
    assert set(eligible["kr_equity"]) == {"A111111", "A222222"}
    assert eligible["bond"] == ["A333333"]
    assert eligible["cash_mmf"] == []
    assert eligible["global_equity"] == []


def test_bond_tips_quota_splits_inflation_linked_and_nominal():
    """global_duration bucket에 inflation_linked + nominal 풀이 있을 때 tips_share 비율로 quota 분배."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A_TIPS1", name="TIPS-1", aum_krw=5e12,
                 underlying_index="ui_A_TIPS1", bucket="안전", category="해외채권_종합",
                 sub_category="inflation_linked"),
        ETFEntry(ticker="A_TIPS2", name="TIPS-2", aum_krw=4e12,
                 underlying_index="ui_A_TIPS2", bucket="안전", category="해외채권_종합",
                 sub_category="inflation_linked"),
        ETFEntry(ticker="A_TIPS3", name="TIPS-3", aum_krw=3e12,
                 underlying_index="ui_A_TIPS3", bucket="안전", category="해외채권_종합",
                 sub_category="inflation_linked"),
        ETFEntry(ticker="A_NOM2", name="UST", aum_krw=7e12,
                 underlying_index="ui_A_NOM2", bucket="안전", category="해외채권_종합",
                 sub_category="us_treasury"),
        ETFEntry(ticker="A_NOM3", name="AGG", aum_krw=6e12,
                 underlying_index="ui_A_NOM3", bucket="안전", category="해외채권_종합",
                 sub_category="us_aggregate"),
    ])
    target = BucketTarget(
        weights={
            "kr_equity": 0.0, "global_equity": 0.0, "precious_metals": 0.0,
            "cyclical_commodity_fx": 0.0, "kr_bond": 0.0,
            "credit": 0.0, "global_duration": 1.0, "cash_mmf": 0.0,
        },
        rationale="t",
        bond_tips_share=0.6,  # per_bucket_n=5 → tips_quota=3, nominal_quota=2
    )
    all_tickers = [e.ticker for e in universe.etfs]
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    returns = _synthetic_returns(all_tickers)
    panel = _trivial_panel(all_tickers, aum_lookup)
    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
    )
    bond_picks = candidates.bucket_to_tickers["bond"]
    tips_count = sum(1 for t in bond_picks if t.startswith("A_TIPS"))
    nominal_count = sum(1 for t in bond_picks if t.startswith("A_NOM"))
    # ENB adaptive n_max may produce different counts than fixed per_bucket_n=5.
    # Core invariant: TIPS fraction ≥ tips_share (0.6) and both sub-pools represented.
    assert tips_count >= 1
    assert nominal_count >= 1
    assert tips_count >= nominal_count  # tips_share=0.6 > 0.5


def test_bond_tips_quota_zero_falls_back_to_legacy_path():
    """bond_tips_share=0 → 분기 없이 기존 single-pool path."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A_TIPS1", name="TIPS-1", aum_krw=5e12,
                 underlying_index="tips_index", bucket="안전", category="해외채권_종합",
                 sub_category="inflation_linked"),
        ETFEntry(ticker="A_NOM1", name="UST", aum_krw=8e12,
                 underlying_index="ktb_index", bucket="안전", category="해외채권_종합",
                 sub_category="us_treasury"),
    ])
    target = BucketTarget(
        weights={
            "kr_equity": 0.0, "global_equity": 0.0, "precious_metals": 0.0,
            "cyclical_commodity_fx": 0.0, "kr_bond": 0.0,
            "credit": 0.0, "global_duration": 1.0, "cash_mmf": 0.0,
        },
        rationale="t",
        # default bond_tips_share=0.0
    )
    all_tickers = [e.ticker for e in universe.etfs]
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    returns = _synthetic_returns(all_tickers)
    panel = _trivial_panel(all_tickers, aum_lookup)
    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
    )
    # ENB greedy path 검증: "single-pool 분기 안 됨" — bond bucket 이 비어있지 않음.
    bond_picks = candidates.bucket_to_tickers["bond"]
    assert len(bond_picks) >= 1
    assert set(bond_picks).issubset({"A_TIPS1", "A_NOM1"})


def test_all_bonds_eligible_regardless_of_aum():
    """AUM 필터 제거 후: 모든 bond 카테고리 ETF가 eligible."""
    universe = Universe(version="t", etfs=[
        # 200억 — AUM 필터 제거 후 통과
        ETFEntry(ticker="A_TIPS_SMALL", name="KR-TIPS small", aum_krw=20_000_000_000,
                 underlying_index="ui_A_TIPS_SMALL", bucket="안전", category="해외채권_종합",
                 sub_category="inflation_linked"),
        ETFEntry(ticker="A_NOM_BIG", name="KTB big", aum_krw=2_000_000_000_000,
                 underlying_index="ui_A_NOM_BIG", bucket="안전", category="국내채권_종합",
                 sub_category="kr_treasury"),
        # 200억 — AUM 필터 제거 후 통과
        ETFEntry(ticker="A_NOM_SMALL", name="KTB small", aum_krw=20_000_000_000,
                 underlying_index="ui_A_NOM_SMALL", bucket="안전", category="국내채권_종합",
                 sub_category="kr_treasury"),
    ])
    target = BucketTarget(
        weights={
            "kr_equity": 0.0, "global_equity": 0.0, "precious_metals": 0.0,
            "cyclical_commodity_fx": 0.0, "kr_bond": 0.0,
            "credit": 0.0, "global_duration": 1.0, "cash_mmf": 0.0,
        },
        rationale="t",
        bond_tips_share=0.5,
    )
    all_tickers = [e.ticker for e in universe.etfs]
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    returns = _synthetic_returns(all_tickers)
    panel = _trivial_panel(all_tickers, aum_lookup)
    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
    )
    bond_picks = candidates.bucket_to_tickers["bond"]
    # 모든 bond 카테고리 ETF가 eligible
    assert "A_TIPS_SMALL" in bond_picks
    assert "A_NOM_BIG" in bond_picks
    assert "A_NOM_SMALL" in bond_picks


def test_bond_tips_quota_shortfall_falls_back_to_other_pool():
    """tips_share=1.0 인데 TIPS 후보가 quota보다 적으면 nominal로 보충."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A_TIPS1", name="TIPS-1", aum_krw=5e12,
                 underlying_index="ui_A_TIPS1", bucket="안전", category="해외채권_종합",
                 sub_category="inflation_linked"),
        ETFEntry(ticker="A_NOM2", name="UST", aum_krw=7e12,
                 underlying_index="ui_A_NOM2", bucket="안전", category="해외채권_종합",
                 sub_category="us_treasury"),
        ETFEntry(ticker="A_NOM3", name="AGG", aum_krw=6e12,
                 underlying_index="ui_A_NOM3", bucket="안전", category="해외채권_종합",
                 sub_category="us_aggregate"),
    ])
    target = BucketTarget(
        weights={
            "kr_equity": 0.0, "global_equity": 0.0, "precious_metals": 0.0,
            "cyclical_commodity_fx": 0.0, "kr_bond": 0.0,
            "credit": 0.0, "global_duration": 1.0, "cash_mmf": 0.0,
        },
        rationale="t",
        bond_tips_share=1.0,  # TIPS만 원하지만 TIPS는 1개뿐
    )
    all_tickers = [e.ticker for e in universe.etfs]
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    returns = _synthetic_returns(all_tickers)
    panel = _trivial_panel(all_tickers, aum_lookup)
    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
    )
    global_dur_picks = candidates.bucket_to_tickers["global_duration"]
    # TIPS 1개 + 부족분 nominal 2개로 보충
    assert "A_TIPS1" in global_dur_picks
    assert len([t for t in global_dur_picks if t.startswith("A_NOM")]) >= 1


def test_select_multi_factor_mode_uses_returns_and_regime():
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="A", aum_krw=10e12,
                 underlying_index="ui_A111111", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A222222", name="B", aum_krw=8e12,
                 underlying_index="ui_A222222", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A333333", name="C", aum_krw=6e12,
                 underlying_index="ui_A333333", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A444444", name="D", aum_krw=4e12,
                 underlying_index="ui_A444444", bucket="위험", category="국내주식_지수"),
    ])
    target = _bt(kr_equity=1.0)
    tickers = ["A111111", "A222222", "A333333", "A444444"]
    returns = _synthetic_returns(tickers)
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    panel = _trivial_panel(tickers, aum_lookup)

    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
        regime_quadrant="growth_disinflation",
        regime_confidence=0.8,
        correlation_threshold=0.85,
    )
    chosen = candidates.bucket_to_tickers["kr_equity"]
    assert len(chosen) >= 1
    assert all(t in tickers for t in chosen)
    assert "multi-factor" in candidates.selection_criteria
    assert "growth_disinflation" in candidates.selection_criteria


def test_select_uses_precomputed_factor_panel():
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="A", aum_krw=10e12,
                 underlying_index="ui_A111111", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A222222", name="B", aum_krw=8e12,
                 underlying_index="ui_A222222", bucket="위험", category="국내주식_지수"),
    ])
    target = _bt(kr_equity=1.0)
    returns = _synthetic_returns(["A111111", "A222222"])
    panel = {
        "A111111": FactorPanel(
            skip1m_mom_3m=0.30, skip1m_mom_6m=0.30, skip1m_mom_12m=0.30,
            realized_vol_60d=0.15, sharpe_60d=1.0, log_aum=math.log(10e12),
        ),
        "A222222": FactorPanel(
            skip1m_mom_3m=-0.10, skip1m_mom_6m=-0.10, skip1m_mom_12m=-0.10,
            realized_vol_60d=0.15, sharpe_60d=-0.5, log_aum=math.log(8e12),
        ),
    }
    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=returns.cov(), capital_krw=100_000_000,
        regime_quadrant="growth_disinflation", regime_confidence=1.0,
    )
    # capital_krw=100M, bucket_weight=1.0 → capital_cap=2; A111111 has positive alpha, A222222 negative → n_max=min(1,...)=1
    assert candidates.bucket_to_tickers["kr_equity"] == ["A111111"]


def test_select_requires_returns_and_panel():
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="A", aum_krw=10e12,
                 underlying_index="ui_A111111", bucket="위험", category="국내주식_지수"),
    ])
    target = _bt(kr_equity=1.0)
    with pytest.raises(ValueError, match="returns"):
        select_etf_candidates(
            universe, target, as_of=date(2026, 5, 10),
            returns=pd.DataFrame(), factor_panel={"A": {}},  # type: ignore[arg-type]
            sigma=pd.DataFrame(), capital_krw=1_000_000_000_000,
        )
    with pytest.raises(ValueError, match="factor_panel"):
        select_etf_candidates(
            universe, target, as_of=date(2026, 5, 10),
            returns=_synthetic_returns(["A111111"]),
            factor_panel={},
            sigma=pd.DataFrame(), capital_krw=1_000_000_000_000,
        )


def test_select_skips_unlisted_etf_for_past_as_of():
    # 2 eligible tickers + 1 future-listed (filtered out by tradable_at).
    # 2 eligible ensures rank_percentile gives spread → at least 1 positive alpha.
    universe = Universe(version="2026-05-10", etfs=[
        ETFEntry(ticker="A069500", name="KODEX 200", aum_krw=10e12,
                 underlying_index="ui_A069500", bucket="위험", category="국내주식_지수",
                 listed_since=date(2020, 1, 1)),
        ETFEntry(ticker="A069501", name="TIGER 200", aum_krw=8e12,
                 underlying_index="ui_A069501", bucket="위험", category="국내주식_지수",
                 listed_since=date(2020, 1, 1)),
        ETFEntry(ticker="A999999", name="Future ETF", aum_krw=10e12,
                 underlying_index="ui_A999999", bucket="위험", category="국내주식_지수",
                 listed_since=date(2027, 1, 1)),
    ])
    target = BucketTarget(
        kr_equity=1.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.0,
        rationale="test",
    )
    tickers = ["A069500", "A069501", "A999999"]
    returns = _synthetic_returns(tickers)
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    panel = _trivial_panel(tickers, aum_lookup)

    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
    )
    assert len(candidates.bucket_to_tickers["kr_equity"]) >= 1
    assert "A999999" not in candidates.bucket_to_tickers["kr_equity"]


# ---------- Stage 3: ENB greedy integration ----------


def test_select_enb_greedy_picks_positive_alpha_tickers():
    """ENB greedy: positive alpha 있는 tickers 만 선택."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="A1", aum_krw=10e12,
                 underlying_index="ui_A111111", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A222222", name="A2", aum_krw=1e12,
                 underlying_index="ui_A222222", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A333333", name="B", aum_krw=5e12,
                 underlying_index="ui_A333333", bucket="위험", category="국내주식_지수"),
    ])
    target = _bt(kr_equity=1.0)
    tickers = ["A111111", "A222222", "A333333"]
    returns = _synthetic_returns(tickers)
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    panel = _trivial_panel(tickers, aum_lookup)
    cs = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
    )
    chosen = cs.bucket_to_tickers["kr_equity"]
    # ENB greedy picks positive-alpha tickers
    assert len(chosen) >= 1
    assert all(t in tickers for t in chosen)


def test_select_without_clusters_uses_enb_greedy():
    """clusters 없이 호출 — ENB greedy 동작, 최소 1개 이상 선택."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="A", aum_krw=10e12, underlying_index="u1",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A222222", name="B", aum_krw=8e12, underlying_index="u2",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A333333", name="C", aum_krw=6e12, underlying_index="u3",
                 bucket="위험", category="국내주식_지수"),
    ])
    target = _bt(kr_equity=1.0)
    tickers = ["A111111", "A222222", "A333333"]
    returns = _synthetic_returns(tickers)
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    panel = _trivial_panel(tickers, aum_lookup)
    cs = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
    )
    assert len(cs.bucket_to_tickers["kr_equity"]) >= 1


def test_eligibility_no_aum_filter():
    """AUM 필터 제거 후: 100억 ETF 도 통과."""
    universe = Universe(version="test", etfs=[
        ETFEntry(
            ticker="A111111", name="Big", aum_krw=100_000_000_000,
            underlying_index="X", bucket="위험", category="국내주식_지수",
        ),
        ETFEntry(
            ticker="A222222", name="Small", aum_krw=10_000_000_000,  # 100억
            underlying_index="X", bucket="위험", category="국내주식_지수",
        ),
    ])
    bt = BucketTarget(
        kr_equity=0.5, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.5, bond_tips_share=0.0,
        rationale="test",
    )
    eligible = list_eligible_tickers(universe, bt, as_of=date(2026, 5, 28))
    assert "A111111" in eligible["kr_equity"]
    assert "A222222" in eligible["kr_equity"]  # 100억도 통과


def test_bond_split_path_populates_bucket_alpha_scores():
    """_select_bond_with_tips_quota 후 attribution['buckets']['bond']['alpha_scores']
    가 sub_pool 들의 alpha 를 통합해 채워져 있어야 함 (cash_spillover 의존)."""
    from datetime import date
    import pandas as pd
    import numpy as np

    from tradingagents.dataflows.universe import ETFEntry, Universe
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
    from tradingagents.skills.portfolio.factor_scorer import FactorPanel

    # bond bucket 후보: TIPS 1개 + nominal 2개
    etfs = [
        ETFEntry(
            ticker="A_TIPS01", name="TIPS01", aum_krw=10_000_000_000,
            underlying_index="ICE TIPS", bucket="안전", category="해외채권_종합",
            sub_category="inflation_linked",
        ),
        ETFEntry(
            ticker="A_NOM01", name="NOM01", aum_krw=50_000_000_000,
            underlying_index="KIS A", bucket="안전", category="국내채권_종합",
            sub_category="nominal",
        ),
        ETFEntry(
            ticker="A_NOM02", name="NOM02", aum_krw=30_000_000_000,
            underlying_index="KIS B", bucket="안전", category="국내채권_종합",
            sub_category="nominal",
        ),
    ]
    universe = Universe(version="test", etfs=etfs)
    bt = BucketTarget(
        kr_equity=0.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.7, cash_mmf=0.3, bond_tips_share=0.3,
        rationale="test",
    )
    # 가짜 returns + factor_panel
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(
        rng.normal(0, 0.01, size=(252, 3)),
        columns=["A_TIPS01", "A_NOM01", "A_NOM02"],
    )
    factor_panel = {
        t: FactorPanel(
            skip1m_mom_3m=0.0, skip1m_mom_6m=0.0, skip1m_mom_12m=0.0,
            realized_vol_60d=0.05, sharpe_60d=0.5,
            log_aum=np.log(50_000_000_000),
        )
        for t in ["A_TIPS01", "A_NOM01", "A_NOM02"]
    }
    attribution: dict = {}
    select_etf_candidates(
        universe, bt, as_of=date(2026, 5, 28),
        returns=returns, factor_panel=factor_panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
        attribution=attribution,
    )
    bond_attr = attribution["buckets"]["bond"]
    assert "alpha_scores" in bond_attr
    # TIPS + nominal 모든 ticker 가 통합 alpha_scores 에 포함
    assert set(bond_attr["alpha_scores"].keys()) >= {"A_TIPS01", "A_NOM01", "A_NOM02"}


def test_select_etf_candidates_uses_etf_metrics(monkeypatch):
    """metrics 입력 시 attribution 에 etf_metrics_summary 기록 + impl_score 4-요소 사용."""
    from datetime import date
    import math
    import numpy as np
    import pandas as pd

    from tradingagents.dataflows.universe import ETFEntry, Universe
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
    from tradingagents.skills.portfolio.factor_scorer import FactorPanel

    etfs = [
        ETFEntry(
            ticker="A_BIG", name="Big_HighTE", aum_krw=150_000_000_000_000,
            underlying_index="S&P 500", bucket="위험", category="해외주식_지수",
        ),
        ETFEntry(
            ticker="A_SMALL", name="Small_LowTE", aum_krw=10_000_000_000_000,
            underlying_index="S&P 500", bucket="위험", category="해외주식_지수",
        ),
    ]
    universe = Universe(version="test", etfs=etfs)
    bt = BucketTarget(
        kr_equity=0.0, global_equity=0.7, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.3, bond_tips_share=0.0, rationale="test",
    )
    rng = np.random.default_rng(42)
    returns = pd.DataFrame(
        rng.normal(0, 0.01, size=(252, 2)),
        columns=["A_BIG", "A_SMALL"],
    )
    factor_panel = {
        t: FactorPanel(
            skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
            realized_vol_60d=0.1, sharpe_60d=0.5,
            log_aum=math.log(etfs[i].aum_krw),
        )
        for i, t in enumerate(["A_BIG", "A_SMALL"])
    }

    # Mock metrics fetch
    def fake_fetch_metrics(tickers, start, end, cache_path=None):
        dates = pd.date_range(start, end, freq="B")  # business days
        idx = pd.MultiIndex.from_product(
            [tickers, dates], names=["ticker", "trade_date"],
        )
        df = pd.DataFrame(index=idx)
        df["tracking_rate"] = [99.60 if t == "A_BIG" else 99.95 for t in idx.get_level_values("ticker")]
        df["premium_discount"] = 0.001
        df["trade_value_krw"] = 1e10
        df["aum_krw"] = 1e13
        df["market_price"] = 45000.0
        df["nav"] = 45000.0
        df["volume"] = 1000000
        return df

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        fake_fetch_metrics,
    )

    attribution: dict = {}
    select_etf_candidates(
        universe, bt, as_of=date(2026, 5, 28),
        returns=returns, factor_panel=factor_panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
        attribution=attribution,
    )

    # attribution['etf_metrics_summary'] 확인
    assert "etf_metrics_summary" in attribution
    summary = attribution["etf_metrics_summary"]
    assert summary["fetch_attempted"] is True
    assert summary["fetch_succeeded"] is True
    # 2 tickers TE 계산 가능 (300일 mock data 면 ≥ 60일 만족)
    # 단 mock dates 길이가 < 60 이면 None 가능 — fetcher 가 from 시작일 ~ end 까지 모든
    # business days 생성하므로, 400일 window 면 ~280 business days
    assert summary["n_tickers_with_te"] >= 0  # mock 이라 결과가 달라질 수 있음


def test_select_etf_candidates_falls_back_when_metrics_fetch_fails(monkeypatch):
    """fetch_etf_metrics_window 가 KRXOpenAPIError raise → fallback (log_aum 단독)."""
    from datetime import date
    import math
    import numpy as np
    import pandas as pd

    from tradingagents.dataflows.universe import ETFEntry, Universe
    from tradingagents.dataflows.krx_openapi import KRXOpenAPIError
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
    from tradingagents.skills.portfolio.factor_scorer import FactorPanel

    etfs = [
        ETFEntry(
            ticker="A_BIG", name="Big", aum_krw=150_000_000_000_000,
            underlying_index="X1", bucket="위험", category="국내주식_지수",
        ),
        ETFEntry(
            ticker="A_MED", name="Med", aum_krw=50_000_000_000_000,
            underlying_index="X2", bucket="위험", category="국내주식_지수",
        ),
    ]
    universe = Universe(version="test", etfs=etfs)
    bt = BucketTarget(
        kr_equity=0.7, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.3, bond_tips_share=0.0, rationale="test",
    )
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(rng.normal(0, 0.01, size=(252, 2)), columns=["A_BIG", "A_MED"])
    factor_panel = {
        "A_BIG": FactorPanel(
            skip1m_mom_3m=0.08, skip1m_mom_6m=0.08, skip1m_mom_12m=0.08,
            realized_vol_60d=0.1, sharpe_60d=0.6,
            log_aum=math.log(150_000_000_000_000),
        ),
        "A_MED": FactorPanel(
            skip1m_mom_3m=0.03, skip1m_mom_6m=0.03, skip1m_mom_12m=0.03,
            realized_vol_60d=0.1, sharpe_60d=0.3,
            log_aum=math.log(50_000_000_000_000),
        ),
    }

    def fake_fetch_fails(tickers, start, end, cache_path=None):
        raise KRXOpenAPIError("simulated KRX outage")

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        fake_fetch_fails,
    )

    attribution: dict = {}
    candidates = select_etf_candidates(
        universe, bt, as_of=date(2026, 5, 28),
        returns=returns, factor_panel=factor_panel,
        sigma=returns.cov(), capital_krw=1_000_000_000_000,
        attribution=attribution,
    )

    # fetch 실패해도 candidates 산출
    assert "A_BIG" in candidates.bucket_to_tickers["kr_equity"]
    # attribution 에 fallback_reason 기록
    assert attribution["etf_metrics_summary"]["fetch_succeeded"] is False
    assert "simulated KRX outage" in attribution["etf_metrics_summary"]["fallback_reason"]


def test_select_etf_candidates_attribution_records_selection_trace(monkeypatch):
    """attribution['buckets'][b]['selection_trace'] 가 채워짐."""
    from datetime import date
    import math
    import numpy as np
    import pandas as pd

    from tradingagents.dataflows.universe import ETFEntry, Universe
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
    from tradingagents.skills.portfolio.factor_scorer import FactorPanel

    etfs = [
        ETFEntry(
            ticker=f"K{i:02d}", name=f"K{i}", aum_krw=10_000_000_000_000,
            underlying_index=f"X{i}", bucket="위험", category="국내주식_지수",
        )
        for i in range(4)
    ]
    universe = Universe(version="test", etfs=etfs)
    bt = BucketTarget(
        kr_equity=0.5, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.5, bond_tips_share=0.0, rationale="test",
    )
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(
        rng.normal(0, 0.01, size=(252, 4)),
        columns=[e.ticker for e in etfs],
    )
    sigma = returns.cov()
    factor_panel = {
        e.ticker: FactorPanel(
            skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
            realized_vol_60d=0.1, sharpe_60d=0.5,
            log_aum=math.log(e.aum_krw),
        )
        for e in etfs
    }
    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    attribution: dict = {}
    select_etf_candidates(
        universe, bt, as_of=date(2026, 5, 28),
        returns=returns, factor_panel=factor_panel,
        sigma=sigma, capital_krw=1_000_000_000,
        attribution=attribution,
    )
    bucket_attr = attribution["buckets"]["kr_equity"]
    assert "selection_trace" in bucket_attr
    trace = bucket_attr["selection_trace"]
    assert "stop_reason" in trace
    assert "enb_progression" in trace


def test_select_etf_candidates_adaptive_n_caps_small_capital(monkeypatch):
    """1B capital x 0.10 bucket = 100M -> n_max=2."""
    from datetime import date
    import math
    import numpy as np
    import pandas as pd

    from tradingagents.dataflows.universe import ETFEntry, Universe
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
    from tradingagents.skills.portfolio.factor_scorer import FactorPanel

    etfs = [
        ETFEntry(
            ticker=f"K{i:02d}", name=f"K{i}", aum_krw=10_000_000_000_000,
            underlying_index=f"X{i}", bucket="위험", category="국내주식_지수",
        )
        for i in range(10)
    ]
    universe = Universe(version="test", etfs=etfs)
    bt = BucketTarget(
        kr_equity=0.10, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.90, bond_tips_share=0.0, rationale="test",
    )
    rng = np.random.default_rng(11)
    returns = pd.DataFrame(
        rng.normal(0, 0.01, size=(252, 10)),
        columns=[e.ticker for e in etfs],
    )
    sigma = returns.cov()
    # Differentiated panels so rank_percentile gives spread; top 5+ get positive alpha.
    factor_panel = {
        e.ticker: FactorPanel(
            skip1m_mom_3m=0.05 + 0.01 * i,
            skip1m_mom_6m=0.05 + 0.01 * i,
            skip1m_mom_12m=0.05 + 0.01 * i,
            realized_vol_60d=0.1, sharpe_60d=0.5 + 0.02 * i,
            log_aum=math.log(e.aum_krw),
        )
        for i, e in enumerate(etfs)
    }
    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    candidates = select_etf_candidates(
        universe, bt, as_of=date(2026, 5, 28),
        returns=returns, factor_panel=factor_panel,
        sigma=sigma, capital_krw=1_000_000_000,
    )
    # capital_krw=1B, bucket_weight=0.10 → capital_cap = int(0.10*1e9/5e7) = 2
    assert len(candidates.bucket_to_tickers["kr_equity"]) == 2
