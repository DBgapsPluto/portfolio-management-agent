"""Stage 3 attribution 로깅 — factor_scorer breakdown + candidate_selector trace."""
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
from tradingagents.skills.portfolio.factor_scorer import (
    FactorPanel, _rank_normalize, _zscore,
    score_candidates, score_candidates_with_components, select_diverse,
)


def _panels(specs):
    """specs: list of (ticker, mom, vol, sharpe, log_aum)."""
    return {
        t: FactorPanel(
            skip1m_mom_3m=m, skip1m_mom_6m=m, skip1m_mom_12m=m,
            realized_vol_60d=v, sharpe_60d=s, log_aum=la,
        ) for (t, m, v, s, la) in specs
    }


def test_score_candidates_with_components_matches_score_candidates():
    panels = _panels([
        ("A", 0.10, 0.15, 1.2, 30.0),
        ("B", 0.05, 0.20, 0.6, 31.0),
        ("C", 0.20, 0.10, 2.0, 29.5),
    ])
    scores_only = score_candidates(panels, "growth_disinflation", 1.0)
    scores, breakdown, weights = score_candidates_with_components(
        panels, "growth_disinflation", 1.0,
    )
    assert set(scores) == set(scores_only) == {"A", "B", "C"}
    for t in scores:
        assert scores[t] == pytest.approx(scores_only[t], abs=1e-12)
    # breakdown keys 정합 — Stage 3 family enrichment 이후 normalized 에 sub-composite
    # 메타(mom_core/qual_core/mom_extras/qual_extras) 가 추가될 수 있어 superset 단언.
    for t in scores:
        b = breakdown[t]
        assert set(b["raw"]) == {"mom_value", "vol_value", "sharpe_value", "size_value"}
        assert {"mom", "vol", "qual", "size"}.issubset(b["normalized"])
        assert set(b["contributions"]) == {"mom", "lowvol", "qual", "size"}
        assert b["base_score"] == pytest.approx(sum(b["contributions"].values()), abs=1e-12)
    assert set(weights) == {"mom", "lowvol", "qual", "size"}
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_score_components_z_score_correctness():
    """A는 모멘텀 1등 → z_mom > 0, vol 1등 → z_vol > 0 (음수화해서 contribution 양수)."""
    panels = _panels([
        ("A", 0.30, 0.10, 1.0, 30.0),  # 가장 좋은 mom, 가장 낮은 vol
        ("B", 0.10, 0.20, 0.5, 30.0),
        ("C", 0.00, 0.30, 0.2, 30.0),
    ])
    scores, breakdown, _ = score_candidates_with_components(panels, "unknown", 0.5)
    assert breakdown["A"]["normalized"]["mom"] > breakdown["B"]["normalized"]["mom"]
    assert breakdown["A"]["normalized"]["mom"] > breakdown["C"]["normalized"]["mom"]
    # vol 낮은 A는 z_vol이 음수 → lowvol contribution 양수
    assert breakdown["A"]["normalized"]["vol"] < 0
    assert breakdown["A"]["contributions"]["lowvol"] > 0


def test_score_components_empty_panels():
    scores, breakdown, weights = score_candidates_with_components({}, None, 0.0)
    assert scores == {}
    assert breakdown == {}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_select_diverse_populates_trace():
    """selection_trace dict가 모든 walked ticker에 대해 채워져야."""
    tickers = ["A", "B", "C", "D"]
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    # A와 B는 corr ≈ 1.0 (같은 베이스 신호 + 작은 노이즈) → B는 corr로 reject
    base = rng.normal(0, 0.01, 200)
    returns = pd.DataFrame({
        "A": base,
        "B": base + rng.normal(0, 0.0001, 200),    # 거의 동일
        "C": rng.normal(0, 0.01, 200),
        "D": rng.normal(0, 0.01, 200),
    }, index=idx)
    trace: dict = {}
    chosen = select_diverse(tickers, returns, n=3, correlation_threshold=0.85,
                             selection_trace=trace)
    # A는 무조건 선정 (1순위), B는 corr로 reject, C/D는 통과
    assert chosen[0] == "A"
    assert "B" not in chosen[:3] or trace.get("B", {}).get("reason", "").startswith("padding")
    assert trace["A"]["selected"] is True
    assert trace["A"]["reason"] == "first pick"
    assert "B" in trace
    # B는 corr-rejected (보통) or padding으로 다시 채택됨
    assert isinstance(trace["B"]["corr_with"], list)


def test_select_diverse_padding_fallback():
    """corr 통과 후보 < n이면 ranking 순으로 보충."""
    tickers = ["A", "B", "C"]
    # 전부 같은 시리즈 → 전부 corr=1.0
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=100, freq="B")
    base = rng.normal(0, 0.01, 100)
    returns = pd.DataFrame({t: base.copy() for t in tickers}, index=idx)
    trace: dict = {}
    chosen = select_diverse(tickers, returns, n=3, selection_trace=trace)
    assert len(chosen) == 3
    # 모두 selected=True (padding으로 채워짐)
    assert all(trace[t]["selected"] for t in tickers)
    # padding fallback 표시 확인
    padding_ones = [t for t in tickers if "padding" in trace[t]["reason"]]
    assert len(padding_ones) >= 2


def _build_universe_with_subcat() -> Universe:
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A1", name="KODEX 200", aum_krw=10e12,
                 underlying_index="x", bucket="위험", category="국내주식_지수",
                 sub_category="index_broad"),
        ETFEntry(ticker="A2", name="KODEX 반도체", aum_krw=5e12,
                 underlying_index="x", bucket="위험", category="국내주식_섹터",
                 sub_category="semiconductor"),
        ETFEntry(ticker="A3", name="TIGER 골드", aum_krw=3e12,
                 underlying_index="x", bucket="위험", category="FX 및 원자재",
                 sub_category="gold"),
    ])


def test_select_etf_candidates_populates_attribution():
    u = _build_universe_with_subcat()
    target = BucketTarget(
        kr_equity=0.5, global_equity=0.0,
        fx_commodity=0.5, bond=0.0, cash_mmf=0.0,
        rationale="t",
    )
    tickers = ["A1", "A2", "A3"]
    rng = np.random.default_rng(11)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    returns = pd.DataFrame(
        {t: rng.normal(0.0005, 0.012, 300) for t in tickers}, index=idx,
    )
    aum_lookup = {e.ticker: e.aum_krw for e in u.etfs}
    panel = {
        t: FactorPanel(skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
                       realized_vol_60d=0.15, sharpe_60d=0.3,
                       log_aum=math.log(aum_lookup[t]))
        for t in tickers
    }
    attr: dict = {}
    sigma = returns.dropna(axis=0, how="any").cov()
    cs = select_etf_candidates(
        u, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=sigma, capital_krw=1_000_000_000,
        # Stage 2 audit (2026-05-26, Task 4): cell-key "D_N_F" path removed
        # by 2026-05-22 PR. Use legacy 7-scenario name "stagflation" which
        # maps to (D, N, F) axes — same gold boost.
        dominant_scenario="stagflation",
        regime_quadrant="recession_inflation", regime_confidence=0.8,
        attribution=attr,
    )
    # 기본 산출은 이전과 같이 정상
    assert "kr_equity" in cs.bucket_to_tickers
    # attribution 구조
    assert attr["config"]["dominant_scenario"] == "stagflation"
    assert attr["config"]["regime_quadrant"] == "recession_inflation"
    assert set(attr["buckets"]) >= {"kr_equity", "fx_commodity"}
    kr = attr["buckets"]["kr_equity"]
    assert kr["eligible_count"] == 2
    assert kr["bond_split"] is False
    assert set(kr["per_ticker"]).issubset({"A1", "A2"})
    # gold ETF에 D 사이클 boost 적용 확인
    fx = attr["buckets"]["fx_commodity"]
    assert "A3" in fx["per_ticker"]
    sb = fx["per_ticker"]["A3"]["scenario_boost"]
    assert sb["scenario"] == "stagflation"
    assert sb["composed_mult"] > 1.0      # gold는 D에서 1.8 boost
    assert sb["log_boost"] > 0


def test_select_etf_candidates_no_scenario_no_boost():
    u = _build_universe_with_subcat()
    target = BucketTarget(
        kr_equity=0.0, global_equity=0.0,
        fx_commodity=1.0, bond=0.0, cash_mmf=0.0,
        rationale="t",
    )
    tickers = [e.ticker for e in u.etfs]
    rng = np.random.default_rng(11)
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    returns = pd.DataFrame(
        {t: rng.normal(0.0005, 0.012, 200) for t in tickers}, index=idx,
    )
    aum_lookup = {e.ticker: e.aum_krw for e in u.etfs}
    panel = {
        t: FactorPanel(skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
                       realized_vol_60d=0.15, sharpe_60d=0.3,
                       log_aum=math.log(aum_lookup[t]))
        for t in tickers
    }
    attr: dict = {}
    sigma = returns.dropna(axis=0, how="any").cov()
    cs = select_etf_candidates(
        u, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=sigma, capital_krw=1_000_000_000,
        dominant_scenario=None,
        attribution=attr,
    )
    # boost 없으면 log_boost=0, composed_mult=1.0
    fx = attr["buckets"]["fx_commodity"]
    pt = fx["per_ticker"]["A3"]
    assert pt["scenario_boost"]["log_boost"] == 0.0
    assert pt["scenario_boost"]["composed_mult"] == 1.0
    assert pt["final_score"] == pytest.approx(pt["base_score"], abs=1e-12)


def test_rank_normalize_bounded_and_uniform():
    """rank_percentile은 항상 [-0.5, +0.5] 안에 있고 분포 균등."""
    values = {f"T{i}": float(i) for i in range(11)}  # 0..10
    out = _rank_normalize(values)
    vs = sorted(out.values())
    # 최소 -0.5, 최대 +0.5
    assert vs[0] == pytest.approx(-0.5)
    assert vs[-1] == pytest.approx(0.5)
    # 균등 분포 (간격 동일)
    diffs = [vs[i+1] - vs[i] for i in range(len(vs) - 1)]
    assert all(d == pytest.approx(diffs[0], abs=1e-9) for d in diffs)


def test_rank_normalize_none_neutral():
    values = {"a": 1.0, "b": None, "c": 3.0}
    out = _rank_normalize(values)
    assert out["b"] == 0.0
    # a < c → a 음수, c 양수
    assert out["a"] < out["c"]


def test_rank_normalize_ties_get_same_rank():
    values = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 5.0}
    out = _rank_normalize(values)
    # 1.0짜리 셋은 같은 평균 rank
    assert out["a"] == out["b"] == out["c"]
    assert out["d"] > out["a"]


def test_rank_normalize_immune_to_extreme_outlier():
    """size dominance 해결 — outlier가 다른 값들의 정규화에 영향 X."""
    normal = {f"T{i}": float(i) for i in range(10)}
    with_outlier = {**normal, "OUTLIER": 1e9}

    n1 = _rank_normalize(normal)
    n2 = _rank_normalize(with_outlier)

    # z-score는 outlier가 분포를 왜곡:
    z1 = _zscore(normal)
    z2 = _zscore(with_outlier)

    # rank: outlier가 +0.5 차지, 나머지는 -0.5 ~ ~0.4까지 균등
    assert n2["OUTLIER"] == pytest.approx(0.5)
    # rank: outlier 추가 후 T0 ~ T9는 상대 순서 유지 (스케일만 변경)
    # 모두 음수 영역으로 압축됨 (outlier가 +0.5 차지하므로)
    assert all(n2[f"T{i}"] < n2["OUTLIER"] for i in range(10))

    # z-score: outlier 영향으로 T0~T9 모두 +0 근처로 압축 (정보 손실)
    # rank: T0~T9 사이 상대적 distinction 유지
    spread_rank = max(n2[f"T{i}"] for i in range(10)) - min(n2[f"T{i}"] for i in range(10))
    spread_z = max(z2[f"T{i}"] for i in range(10)) - min(z2[f"T{i}"] for i in range(10))
    assert spread_rank > spread_z, "rank normalization preserves order better with outliers"


def test_score_candidates_normalization_param_compat():
    """zscore와 rank_percentile 두 옵션 모두 동작."""
    panels = _panels([
        ("A", 0.30, 0.10, 1.0, 30.0),
        ("B", 0.10, 0.20, 0.5, 30.0),
        ("C", 0.00, 0.30, 0.2, 30.0),
    ])
    scores_zscore, br_zscore, _ = score_candidates_with_components(
        panels, "unknown", 1.0, normalization="zscore",
    )
    scores_rank, br_rank, _ = score_candidates_with_components(
        panels, "unknown", 1.0, normalization="rank_percentile",
    )
    # 둘 다 A > B > C 순서 유지 (semantic)
    assert scores_zscore["A"] > scores_zscore["B"] > scores_zscore["C"]
    assert scores_rank["A"] > scores_rank["B"] > scores_rank["C"]
    # rank의 절대값은 더 작음 (bounded)
    assert abs(scores_rank["A"]) < abs(scores_zscore["A"])
    # 둘 다 normalization 필드에 기록
    assert br_zscore["A"]["normalization"] == "zscore"
    assert br_rank["A"]["normalization"] == "rank_percentile"


def test_score_candidates_invalid_normalization_raises():
    panels = _panels([("A", 0.1, 0.1, 0.1, 30.0)])
    with pytest.raises(ValueError, match="unknown normalization"):
        score_candidates_with_components(panels, None, 0.5, normalization="bogus")


def test_attribution_none_behaves_as_no_op():
    """attribution=None이면 기존 동작과 100% 동일 (성능/사이드이펙트 없음)."""
    u = _build_universe_with_subcat()
    target = BucketTarget(
        kr_equity=1.0, global_equity=0.0,
        fx_commodity=0.0, bond=0.0, cash_mmf=0.0,
        rationale="t",
    )
    tickers = ["A1", "A2"]
    rng = np.random.default_rng(11)
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    returns = pd.DataFrame(
        {t: rng.normal(0.0005, 0.012, 200) for t in tickers}, index=idx,
    )
    aum_lookup = {e.ticker: e.aum_krw for e in u.etfs}
    panel = {
        t: FactorPanel(skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
                       realized_vol_60d=0.15, sharpe_60d=0.3,
                       log_aum=math.log(aum_lookup[t]))
        for t in tickers
    }
    sigma = returns.dropna(axis=0, how="any").cov()
    cs1 = select_etf_candidates(
        u, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=sigma, capital_krw=1_000_000_000,
        attribution=None,
    )
    cs2 = select_etf_candidates(
        u, target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        sigma=sigma, capital_krw=1_000_000_000,
        attribution={},
    )
    assert cs1.bucket_to_tickers == cs2.bucket_to_tickers
