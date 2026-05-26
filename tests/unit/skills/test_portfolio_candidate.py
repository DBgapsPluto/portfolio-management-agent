"""candidate_selector tests — Phase A signature (multi-factor only)."""
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.candidate_selector import (
    DEFAULT_MIN_AUM_KRW, list_eligible_tickers, select_etf_candidates,
)
from tradingagents.skills.portfolio.factor_scorer import FactorPanel


def _build_universe() -> Universe:
    return Universe(version="2026-05-10", etfs=[
        ETFEntry(ticker="A069500", name="KODEX 200", aum_krw=10e12,
                 underlying_index="ui_A069500", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A360750", name="TIGER S&P500", aum_krw=15e12,
                 underlying_index="y", bucket="위험", category="해외주식_지수"),
        ETFEntry(ticker="A114260", name="KODEX 국고채3년", aum_krw=5e12,
                 underlying_index="z", bucket="안전", category="국내채권_종합"),
        ETFEntry(ticker="A459580", name="KODEX CD금리", aum_krw=8e12,
                 underlying_index="w", bucket="안전", category="금리연계형/초단기채권"),
        ETFEntry(ticker="A411060", name="ACE KRX금현물", aum_krw=5e12,
                 underlying_index="v", bucket="위험", category="FX 및 원자재"),
    ])


def _synthetic_returns(tickers, days=300, seed=11):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=days, freq="B")
    return pd.DataFrame(
        {t: rng.normal(0.0005, 0.012, days) for t in tickers},
        index=idx,
    )


def _trivial_panel(tickers, aum_lookup):
    return {
        t: FactorPanel(
            skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
            realized_vol_60d=0.15, sharpe_60d=0.3,
            log_aum=math.log(aum_lookup.get(t, 1e12)),
        )
        for t in tickers
    }


def test_select_candidates_for_target():
    universe = _build_universe()
    target = BucketTarget(
        kr_equity=0.15, global_equity=0.30, fx_commodity=0.10,
        bond=0.35, cash_mmf=0.10,
        rationale="defensive recession tilt",
    )
    all_tickers = [e.ticker for e in universe.etfs]
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    returns = _synthetic_returns(all_tickers)
    panel = _trivial_panel(all_tickers, aum_lookup)

    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
    )
    assert "A069500" in candidates.bucket_to_tickers["kr_equity"]
    assert "A360750" in candidates.bucket_to_tickers["global_equity"]
    assert "A114260" in candidates.bucket_to_tickers["bond"]
    assert "A459580" in candidates.bucket_to_tickers["cash_mmf"]


def test_default_floor_is_500eok():
    """Stage 3 D2 — flat ~500억 (현 KR 시장 pool 두께 확보)."""
    assert DEFAULT_MIN_AUM_KRW == 50_000_000_000


def test_floor_500eok_admits_midcap():
    """1000억 AUM ETF는 새 floor(500억) 통과 — 이전 1조 floor 였으면 탈락."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="big", aum_krw=6e11, underlying_index="u1",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A222222", name="mid", aum_krw=1e11, underlying_index="u2",
                 bucket="위험", category="국내주식_지수"),
    ])
    bt = BucketTarget(kr_equity=1.0, global_equity=0, fx_commodity=0, bond=0,
                      cash_mmf=0, rationale="t")
    out = list_eligible_tickers(universe, bt, as_of=date(2025, 1, 2))
    assert set(out["kr_equity"]) == {"A111111", "A222222"}


def test_list_eligible_tickers_filters_by_aum_and_category():
    target = BucketTarget(
        kr_equity=0.5, global_equity=0.0, fx_commodity=0.0,
        bond=0.5, cash_mmf=0.0,
        rationale="t",
    )
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="big kr", aum_krw=10e12,
                 underlying_index="ui_A111111", bucket="위험", category="국내주식_지수"),
        # 30억 — Stage 3 floor 500억 미달, AUM 필터 단언 유지
        ETFEntry(ticker="A222222", name="small kr", aum_krw=3_000_000_000,
                 underlying_index="ui_A222222", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A333333", name="bond", aum_krw=5e12,
                 underlying_index="ui_A333333", bucket="안전", category="국내채권_종합"),
        ETFEntry(ticker="A444444", name="cash", aum_krw=10e12,
                 underlying_index="ui_A444444", bucket="안전", category="금리연계형/초단기채권"),
    ])
    eligible = list_eligible_tickers(universe, target, as_of=date(2026, 5, 10))
    assert eligible["kr_equity"] == ["A111111"]
    assert eligible["bond"] == ["A333333"]
    assert eligible["cash_mmf"] == []
    assert eligible["global_equity"] == []


def test_bond_tips_quota_splits_inflation_linked_and_nominal():
    """bond bucket에 inflation_linked + nominal 풀이 있을 때 tips_share 비율로 quota 분배."""
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
        ETFEntry(ticker="A_NOM1", name="KTB", aum_krw=8e12,
                 underlying_index="ui_A_NOM1", bucket="안전", category="국내채권_종합",
                 sub_category="kr_treasury"),
        ETFEntry(ticker="A_NOM2", name="UST", aum_krw=7e12,
                 underlying_index="ui_A_NOM2", bucket="안전", category="해외채권_종합",
                 sub_category="us_treasury"),
        ETFEntry(ticker="A_NOM3", name="AGG", aum_krw=6e12,
                 underlying_index="ui_A_NOM3", bucket="안전", category="해외채권_종합",
                 sub_category="us_aggregate"),
    ])
    target = BucketTarget(
        kr_equity=0.0, global_equity=0.0, fx_commodity=0.0,
        bond=1.0, cash_mmf=0.0,
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
    )
    bond_picks = candidates.bucket_to_tickers["bond"]
    tips_count = sum(1 for t in bond_picks if t.startswith("A_TIPS"))
    nominal_count = sum(1 for t in bond_picks if t.startswith("A_NOM"))
    assert tips_count == 3
    assert nominal_count == 2


def test_bond_tips_quota_zero_falls_back_to_legacy_path():
    """bond_tips_share=0 → 분기 없이 기존 single-pool path."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A_TIPS1", name="TIPS-1", aum_krw=5e12,
                 underlying_index="tips_index", bucket="안전", category="해외채권_종합",
                 sub_category="inflation_linked"),
        ETFEntry(ticker="A_NOM1", name="KTB", aum_krw=8e12,
                 underlying_index="ktb_index", bucket="안전", category="국내채권_종합",
                 sub_category="kr_treasury"),
    ])
    target = BucketTarget(
        kr_equity=0.0, global_equity=0.0, fx_commodity=0.0,
        bond=1.0, cash_mmf=0.0, rationale="t",
        # default bond_tips_share=0.0
    )
    all_tickers = [e.ticker for e in universe.etfs]
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    returns = _synthetic_returns(all_tickers)
    panel = _trivial_panel(all_tickers, aum_lookup)
    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
    )
    # both tickers should be eligible (legacy path), no quota split
    assert set(candidates.bucket_to_tickers["bond"]) == {"A_TIPS1", "A_NOM1"}


def test_relaxed_min_aum_admits_inflation_linked_etf():
    """sub_category='inflation_linked' ETF는 default 500억 미달이라도 100억 이상이면 통과."""
    universe = Universe(version="t", etfs=[
        # 200억 — Stage 3 default 500억 미달이지만 inflation_linked relax(100억) 통과
        ETFEntry(ticker="A_TIPS_SMALL", name="KR-TIPS small", aum_krw=20_000_000_000,
                 underlying_index="ui_A_TIPS_SMALL", bucket="안전", category="국내채권_종합",
                 sub_category="inflation_linked"),
        ETFEntry(ticker="A_NOM_BIG", name="KTB big", aum_krw=2_000_000_000_000,
                 underlying_index="ui_A_NOM_BIG", bucket="안전", category="국내채권_종합",
                 sub_category="kr_treasury"),  # 2조, default 통과
        # 200억 — default 500억 미달, kr_treasury는 relax 비대상 → 탈락
        ETFEntry(ticker="A_NOM_SMALL", name="KTB small", aum_krw=20_000_000_000,
                 underlying_index="ui_A_NOM_SMALL", bucket="안전", category="국내채권_종합",
                 sub_category="kr_treasury"),
    ])
    target = BucketTarget(
        kr_equity=0.0, global_equity=0.0, fx_commodity=0.0,
        bond=1.0, cash_mmf=0.0, rationale="t",
        bond_tips_share=0.5,
    )
    all_tickers = [e.ticker for e in universe.etfs]
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    returns = _synthetic_returns(all_tickers)
    panel = _trivial_panel(all_tickers, aum_lookup)
    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
    )
    bond_picks = candidates.bucket_to_tickers["bond"]
    # inflation_linked는 200억이지만 relaxed threshold(100억)에 의해 통과
    assert "A_TIPS_SMALL" in bond_picks
    # KTB big은 2조 default 통과
    assert "A_NOM_BIG" in bond_picks
    # KTB small은 default 1조 미달이라 탈락 (kr_treasury는 relax 대상 X)
    assert "A_NOM_SMALL" not in bond_picks


def test_bond_tips_quota_shortfall_falls_back_to_other_pool():
    """tips_share=1.0 인데 TIPS 후보가 quota보다 적으면 nominal로 보충."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A_TIPS1", name="TIPS-1", aum_krw=5e12,
                 underlying_index="ui_A_TIPS1", bucket="안전", category="해외채권_종합",
                 sub_category="inflation_linked"),
        ETFEntry(ticker="A_NOM1", name="KTB", aum_krw=8e12,
                 underlying_index="ui_A_NOM1", bucket="안전", category="국내채권_종합",
                 sub_category="kr_treasury"),
        ETFEntry(ticker="A_NOM2", name="UST", aum_krw=7e12,
                 underlying_index="ui_A_NOM2", bucket="안전", category="해외채권_종합",
                 sub_category="us_treasury"),
    ])
    target = BucketTarget(
        kr_equity=0.0, global_equity=0.0, fx_commodity=0.0,
        bond=1.0, cash_mmf=0.0, rationale="t",
        bond_tips_share=1.0,  # TIPS만 원하지만 TIPS는 1개뿐
    )
    all_tickers = [e.ticker for e in universe.etfs]
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    returns = _synthetic_returns(all_tickers)
    panel = _trivial_panel(all_tickers, aum_lookup)
    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
    )
    bond_picks = candidates.bucket_to_tickers["bond"]
    # TIPS 1개 + 부족분 nominal 2개로 보충
    assert "A_TIPS1" in bond_picks
    assert len([t for t in bond_picks if t.startswith("A_NOM")]) >= 1


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
    target = BucketTarget(
        kr_equity=1.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.0,
        rationale="t",
    )
    tickers = ["A111111", "A222222", "A333333", "A444444"]
    returns = _synthetic_returns(tickers)
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    panel = _trivial_panel(tickers, aum_lookup)

    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        per_bucket_n=2,
        returns=returns, factor_panel=panel,
        regime_quadrant="growth_disinflation",
        regime_confidence=0.8,
        correlation_threshold=0.85,
    )
    chosen = candidates.bucket_to_tickers["kr_equity"]
    assert len(chosen) == 2
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
    target = BucketTarget(
        kr_equity=1.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.0,
        rationale="t",
    )
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
        per_bucket_n=1,
        returns=returns, factor_panel=panel,
        regime_quadrant="growth_disinflation", regime_confidence=1.0,
    )
    assert candidates.bucket_to_tickers["kr_equity"] == ["A111111"]


def test_select_requires_returns_and_panel():
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="A", aum_krw=10e12,
                 underlying_index="ui_A111111", bucket="위험", category="국내주식_지수"),
    ])
    target = BucketTarget(
        kr_equity=1.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.0,
        rationale="t",
    )
    with pytest.raises(ValueError, match="returns"):
        select_etf_candidates(
            universe, target, as_of=date(2026, 5, 10),
            returns=pd.DataFrame(), factor_panel={"A": {}},  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="factor_panel"):
        select_etf_candidates(
            universe, target, as_of=date(2026, 5, 10),
            returns=_synthetic_returns(["A111111"]),
            factor_panel={},
        )


def test_select_skips_unlisted_etf_for_past_as_of():
    universe = Universe(version="2026-05-10", etfs=[
        ETFEntry(ticker="A069500", name="KODEX 200", aum_krw=10e12,
                 underlying_index="ui_A069500", bucket="위험", category="국내주식_지수",
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
    tickers = ["A069500", "A999999"]
    returns = _synthetic_returns(tickers)
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    panel = _trivial_panel(tickers, aum_lookup)

    candidates = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
    )
    assert "A069500" in candidates.bucket_to_tickers["kr_equity"]
    assert "A999999" not in candidates.bucket_to_tickers["kr_equity"]


# ---------- Stage 3: cluster-aware integration ----------


def test_select_threads_clusters_for_within_group_impl():
    """clusters 제공 시 그룹 내 대표는 impl(=AUM proxy) 기준."""
    from tradingagents.schemas.technical import Cluster
    universe = Universe(version="t", etfs=[
        # A1/A2 대체재 (큰/작은 AUM), B 별도 노출
        ETFEntry(ticker="A111111", name="A1", aum_krw=10e12,
                 underlying_index="ui_A111111", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A222222", name="A2", aum_krw=1e12,
                 underlying_index="ui_A222222", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A333333", name="B", aum_krw=5e12,
                 underlying_index="ui_A333333", bucket="위험", category="국내주식_지수"),
    ])
    target = BucketTarget(
        kr_equity=1.0, global_equity=0, fx_commodity=0, bond=0, cash_mmf=0,
        rationale="t",
    )
    tickers = ["A111111", "A222222", "A333333"]
    returns = _synthetic_returns(tickers)
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    panel = _trivial_panel(tickers, aum_lookup)
    clusters = [Cluster(
        cluster_id="c1", members=["A111111", "A222222"],
        avg_internal_correlation=0.95, category_label="dup",
    )]
    cs = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        per_bucket_n=2, clusters=clusters,
    )
    chosen = cs.bucket_to_tickers["kr_equity"]
    # A2(작은 AUM) 탈락, A1 또는 B + 다른 그룹
    assert len(chosen) == 2
    assert "A222222" not in chosen  # 그룹 내 큰 AUM 우대 → A111111 대표
    assert "A111111" in chosen
    assert "A333333" in chosen


def test_select_backward_compat_without_clusters():
    """clusters None → fallback (corr-based grouping) — 결과는 여전히 n개 채워짐."""
    universe = Universe(version="t", etfs=[
        ETFEntry(ticker="A111111", name="A", aum_krw=10e12, underlying_index="u1",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A222222", name="B", aum_krw=8e12, underlying_index="u2",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A333333", name="C", aum_krw=6e12, underlying_index="u3",
                 bucket="위험", category="국내주식_지수"),
    ])
    target = BucketTarget(
        kr_equity=1.0, global_equity=0, fx_commodity=0, bond=0, cash_mmf=0,
        rationale="t",
    )
    tickers = ["A111111", "A222222", "A333333"]
    returns = _synthetic_returns(tickers)
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    panel = _trivial_panel(tickers, aum_lookup)
    cs = select_etf_candidates(
        universe, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel, per_bucket_n=2,
    )
    assert len(cs.bucket_to_tickers["kr_equity"]) == 2
