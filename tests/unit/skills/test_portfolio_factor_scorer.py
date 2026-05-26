"""Unit tests for the multi-factor scorer (조합 1: A + B)."""
import math

import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.portfolio.factor_scorer import (
    REGIME_FACTOR_WEIGHTS,
    blend_regime_weights,
    compute_factor_panel,
    score_candidates,
    select_diverse,
)


class TestBlendRegimeWeights:
    def test_full_confidence_yields_regime_weights(self):
        w = blend_regime_weights("recession_disinflation", confidence=1.0)
        expected = REGIME_FACTOR_WEIGHTS["recession_disinflation"]
        for k in expected:
            assert math.isclose(w[k], expected[k], abs_tol=1e-9)

    def test_zero_confidence_yields_equal_weights(self):
        w = blend_regime_weights("growth_disinflation", confidence=0.0)
        for k in w:
            assert math.isclose(w[k], 0.25, abs_tol=1e-9)

    def test_half_confidence_blends(self):
        w = blend_regime_weights("growth_disinflation", confidence=0.5)
        # mom: 0.5*0.50 + 0.5*0.25 = 0.375
        assert math.isclose(w["mom"], 0.375, abs_tol=1e-9)

    def test_unknown_quadrant_falls_back_to_equal(self):
        w = blend_regime_weights("alien_regime", confidence=0.9)
        for k in w:
            assert math.isclose(w[k], 0.25, abs_tol=1e-9)

    def test_none_quadrant_falls_back(self):
        w = blend_regime_weights(None, confidence=0.9)
        for k in w:
            assert math.isclose(w[k], 0.25, abs_tol=1e-9)

    def test_weights_normalize_to_one(self):
        for q in REGIME_FACTOR_WEIGHTS:
            w = blend_regime_weights(q, confidence=0.7)
            assert math.isclose(sum(w.values()), 1.0, abs_tol=1e-9)

    def test_confidence_clamped(self):
        w_high = blend_regime_weights("growth_disinflation", confidence=2.5)
        w_full = blend_regime_weights("growth_disinflation", confidence=1.0)
        for k in w_high:
            assert math.isclose(w_high[k], w_full[k], abs_tol=1e-9)


class TestComputeFactorPanel:
    def _series(self, returns: list[float]) -> pd.Series:
        return pd.Series(returns, index=pd.date_range("2024-01-01", periods=len(returns), freq="B"))

    def test_short_history_returns_none_for_windows(self):
        # only 30 days — none of the windows hit
        r = self._series([0.001] * 30)
        p = compute_factor_panel(r, aum_krw=1e12)
        assert p.skip1m_mom_3m is None
        assert p.skip1m_mom_6m is None
        assert p.skip1m_mom_12m is None
        assert p.realized_vol_60d is None  # needs 60
        assert p.sharpe_60d is None
        assert p.log_aum > 0

    def test_sufficient_history_yields_factors(self):
        rng = np.random.default_rng(42)
        r = self._series(rng.normal(0.0005, 0.01, 300).tolist())
        p = compute_factor_panel(r, aum_krw=5e12)
        assert p.skip1m_mom_3m is not None
        assert p.skip1m_mom_6m is not None
        assert p.skip1m_mom_12m is not None
        assert p.realized_vol_60d is not None and p.realized_vol_60d > 0
        assert p.sharpe_60d is not None

    def test_skip_1m_excludes_recent_data(self):
        # Construct a series where the LAST 21 days have a huge spike,
        # but the prior 63 days (= 3m window) are flat zero. skip-1m m3 should
        # be near zero, confirming the spike is excluded.
        flat = [0.0] * 273  # 3m skip-1m needs window+21 = 63+21 = 84 returns
        spike = [0.10] * 21
        r = self._series(flat + spike)
        p = compute_factor_panel(r, aum_krw=1e12)
        # skip-1m 3m: cumulative return over 63 days ending at t-21, all zeros
        assert p.skip1m_mom_3m is not None
        assert abs(p.skip1m_mom_3m) < 1e-9


class TestScoreCandidates:
    def _panel(self, mom: float, vol: float, sharpe: float, aum: float):
        from tradingagents.skills.portfolio.factor_scorer import FactorPanel
        return FactorPanel(
            skip1m_mom_3m=mom, skip1m_mom_6m=mom, skip1m_mom_12m=mom,
            realized_vol_60d=vol, sharpe_60d=sharpe, log_aum=math.log(aum),
        )

    def _panel_none(self, aum: float):
        from tradingagents.skills.portfolio.factor_scorer import FactorPanel
        return FactorPanel(log_aum=math.log(aum))

    def test_higher_momentum_wins_in_growth(self):
        panels = {
            "A": self._panel(mom=0.20, vol=0.15, sharpe=1.0, aum=1e12),
            "B": self._panel(mom=0.05, vol=0.15, sharpe=1.0, aum=1e12),
        }
        scores = score_candidates(panels, "growth_disinflation", regime_confidence=1.0)
        assert scores["A"] > scores["B"]

    def test_lower_vol_wins_in_recession(self):
        panels = {
            "A": self._panel(mom=0.10, vol=0.30, sharpe=0.5, aum=1e12),
            "B": self._panel(mom=0.10, vol=0.10, sharpe=0.5, aum=1e12),
        }
        scores = score_candidates(panels, "recession_disinflation", regime_confidence=1.0)
        assert scores["B"] > scores["A"]  # B has lower vol → higher score

    def test_empty_returns_empty(self):
        assert score_candidates({}, "growth_disinflation", regime_confidence=1.0) == {}

    def test_handles_none_factors(self):
        from tradingagents.skills.portfolio.factor_scorer import FactorPanel
        panels = {
            "A": FactorPanel(log_aum=math.log(1e12)),  # all factors None
            "B": FactorPanel(
                skip1m_mom_3m=0.1, skip1m_mom_6m=0.1, skip1m_mom_12m=0.1,
                realized_vol_60d=0.15, sharpe_60d=0.5, log_aum=math.log(2e12),
            ),
        }
        scores = score_candidates(panels, "growth_disinflation", regime_confidence=1.0)
        assert "A" in scores and "B" in scores


class TestSelectDiverse:
    def _returns(self, corr_matrix: dict) -> pd.DataFrame:
        # Build returns DF where corr_matrix dictates pairwise correlation roughly
        np.random.seed(7)
        base = np.random.normal(0, 0.01, 200)
        cols = {}
        for ticker, corr_with_base in corr_matrix.items():
            noise = np.random.normal(0, 0.01, 200)
            cols[ticker] = corr_with_base * base + math.sqrt(1 - corr_with_base ** 2) * noise
        return pd.DataFrame(cols)

    def test_keeps_uncorrelated_assets(self):
        ret = self._returns({"A": 1.0, "B": 0.0, "C": 0.0})
        # All ~uncorrelated; select 3 of 3
        result = select_diverse(["A", "B", "C"], ret, n=3, correlation_threshold=0.85)
        assert set(result) == {"A", "B", "C"}

    def test_drops_highly_correlated_then_pads(self):
        # A and B nearly identical → B should be dropped, padded later
        ret = self._returns({"A": 1.0, "B": 0.99, "C": 0.0})
        result = select_diverse(["A", "B", "C"], ret, n=2, correlation_threshold=0.85)
        # Greedy: A picked first; B dropped (too correlated); C picked
        assert "A" in result and "C" in result
        assert "B" not in result

    def test_pads_when_all_correlated(self):
        # All three are correlated; can't fill n=3 with diverse only → pads.
        ret = self._returns({"A": 1.0, "B": 0.99, "C": 0.99})
        result = select_diverse(["A", "B", "C"], ret, n=3, correlation_threshold=0.85)
        assert len(result) == 3

    def test_missing_ticker_in_returns_accepted(self):
        ret = self._returns({"A": 1.0})
        # B not in returns — accepted as orthogonal
        result = select_diverse(["A", "B"], ret, n=2, correlation_threshold=0.85)
        assert result == ["A", "B"]

    def test_n_zero_returns_empty(self):
        ret = self._returns({"A": 1.0})
        assert select_diverse(["A"], ret, n=0) == []


# ---------- Stage 3: timing overlay ----------


from tradingagents.schemas.technical import (
    ExtendedIndicatorPanel, RiskAdjustedMetrics, TrendState,
)
from tradingagents.skills.portfolio.factor_scorer import (
    TIMING_CAP, _timing_overlay,
)


def _ext(ticker="A000001", *, rsi_div="none", macd_div="none",
         bb=0.5, mfi=50.0, stoch=50.0):
    return ExtendedIndicatorPanel(
        ticker=ticker, bb_percent_b=bb, bb_bandwidth=0.05, adx=25.0,
        stoch_k=stoch, stoch_d=stoch, obv=0.0, obv_slope_20d=0.0, mfi=mfi,
        rsi_divergence=rsi_div, macd_divergence=macd_div,
        weekly_ma50=100.0, weekly_rsi=50.0, weekly_trend="neutral",
    )


def _ra(ticker, *, sortino=0.0, calmar=0.0, maxdd=-0.1, mr=False):
    return RiskAdjustedMetrics(
        ticker=ticker, sortino_60d=sortino, max_drawdown_12m=maxdd,
        calmar_12m=calmar, skewness_60d=0.0, excess_kurtosis_60d=0.0,
        return_z_30d=0.0, is_mean_reversion_candidate=mr,
    )


def test_timing_penalizes_bearish_divergence():
    base = _timing_overlay("A000001", _ext(), None, None)
    bear = _timing_overlay("A000001", _ext(rsi_div="bearish"), None, None)
    assert bear < base


def test_timing_rewards_bullish_divergence():
    base = _timing_overlay("A000001", _ext(), None, None)
    bull = _timing_overlay("A000001", _ext(rsi_div="bullish"), None, None)
    assert bull > base


def test_timing_penalizes_overbought_bb_or_mfi_or_stoch():
    bb_ob = _timing_overlay("A000001", _ext(bb=1.2), None, None)
    mfi_ob = _timing_overlay("A000001", _ext(mfi=85.0), None, None)
    stoch_ob = _timing_overlay("A000001", _ext(stoch=85.0), None, None)
    assert bb_ob < 0 and mfi_ob < 0 and stoch_ob < 0


def test_timing_bonus_mean_reversion():
    ra_panel = {"A000001": _ra("A000001", mr=True)}
    mr = _timing_overlay("A000001", _ext(), None, ra_panel)
    assert mr > 0


def test_timing_penalizes_breakdown_state():
    bd = _timing_overlay("A000001", _ext(), {"A000001": TrendState.BREAKDOWN}, None)
    assert bd < 0


def test_timing_penalizes_downtrend_state():
    dt = _timing_overlay("A000001", _ext(), {"A000001": TrendState.DOWNTREND}, None)
    assert dt < 0


def test_timing_bounded_by_cap():
    worst = _timing_overlay(
        "A000001",
        _ext(rsi_div="bearish", macd_div="bearish", bb=1.5, mfi=95, stoch=95),
        {"A000001": TrendState.BREAKDOWN}, None,
    )
    assert worst >= -TIMING_CAP - 1e-9
    assert worst <= TIMING_CAP + 1e-9


def test_timing_zero_when_no_panels():
    assert _timing_overlay("A000001", None, None, None) == 0.0


def test_timing_missing_ticker_in_panels_neutral():
    # ticker not in etf_states / risk_adjusted → ignored
    out = _timing_overlay(
        "AMISS01", _ext(), {"AOTHER1": TrendState.BREAKDOWN},
        {"AOTHER1": _ra("AOTHER1", mr=True)},
    )
    assert out == 0.0


# ---------- Stage 3: alpha family enrichment ----------


from tradingagents.schemas.technical import TrendQuantification
from tradingagents.skills.portfolio.factor_scorer import FactorPanel


def _panel_for(mom=0.05, vol=0.15, sharpe=0.5, aum=1e12):
    return FactorPanel(
        skip1m_mom_3m=mom, skip1m_mom_6m=mom, skip1m_mom_12m=mom,
        realized_vol_60d=vol, sharpe_60d=sharpe, log_aum=math.log(aum),
    )


def _tq(t, trend_strength=0.0, accel=0.0):
    return TrendQuantification(
        ticker=t, trend_strength_score=trend_strength,
        time_in_state_days=30, distance_ma200_pct=0.0, distance_ma50_pct=0.0,
        momentum_3m_abs=0.05, momentum_3m_rel=0.0,
        momentum_12m_abs=0.10, momentum_12m_rel=0.0,
        momentum_acceleration=accel, benchmark="KOSPI200",
    )


def test_qual_family_absorbs_sortino_calmar_maxdd():
    # 동일 sharpe, A는 sortino/calmar 우수 + 작은 dd → 더 높은 점수
    panels = {"A123456": _panel_for(sharpe=0.5), "A654321": _panel_for(sharpe=0.5)}
    ra = {
        "A123456": _ra("A123456", sortino=2.0, calmar=2.0, maxdd=-0.05),
        "A654321": _ra("A654321", sortino=-2.0, calmar=-2.0, maxdd=-0.50),
    }
    scores = score_candidates(
        panels, "recession_disinflation", 1.0, risk_adjusted=ra,
    )
    assert scores["A123456"] > scores["A654321"]


def test_mom_family_absorbs_trend_strength_and_accel():
    panels = {"A123456": _panel_for(mom=0.05), "A654321": _panel_for(mom=0.05)}
    tq = {
        "A123456": _tq("A123456", trend_strength=0.9, accel=0.3),
        "A654321": _tq("A654321", trend_strength=-0.9, accel=-0.3),
    }
    scores = score_candidates(panels, "growth_disinflation", 1.0, trend_quant=tq)
    assert scores["A123456"] > scores["A654321"]


def test_extended_panel_applies_timing_in_score():
    # 동일 base panels, A는 bullish divergence, B는 bearish → score(A) > score(B)
    panels = {"A123456": _panel_for(), "A654321": _panel_for()}
    ext = {
        "A123456": _ext(ticker="A123456", rsi_div="bullish"),
        "A654321": _ext(ticker="A654321", rsi_div="bearish"),
    }
    scores = score_candidates(panels, "growth_disinflation", 1.0, extended=ext)
    assert scores["A123456"] > scores["A654321"]


def test_etf_state_breakdown_penalizes_in_score():
    panels = {"A123456": _panel_for(), "A654321": _panel_for()}
    states = {"A123456": TrendState.UPTREND, "A654321": TrendState.BREAKDOWN}
    ext = {"A123456": _ext(ticker="A123456"), "A654321": _ext(ticker="A654321")}
    scores = score_candidates(
        panels, "growth_disinflation", 1.0, extended=ext, etf_states=states,
    )
    assert scores["A123456"] > scores["A654321"]


def test_backward_compat_score_without_new_panels():
    # 신규 panel 미제공 → 현행과 동일 결과 (regression guard)
    panels = {
        "A111111": _panel_for(mom=0.20, vol=0.15, sharpe=1.0, aum=1e12),
        "A222222": _panel_for(mom=0.05, vol=0.15, sharpe=1.0, aum=1e12),
    }
    s_new = score_candidates(panels, "growth_disinflation", 1.0)
    s_legacy = score_candidates(panels, "growth_disinflation", 1.0)
    # 새 인자 미제공 시 두 호출 동일
    assert s_new == s_legacy
    assert s_new["A111111"] > s_new["A222222"]


# ---------- Stage 3: implementation-quality score ----------


from tradingagents.skills.portfolio.factor_scorer import compute_impl_score


def test_impl_score_prefers_larger_aum_phase1():
    panels = {"A111111": _panel_for(aum=5e12), "A222222": _panel_for(aum=5e11)}
    impl = compute_impl_score(panels)
    assert impl["A111111"] > impl["A222222"]


def test_impl_score_adds_adv_when_provided():
    panels = {"A111111": _panel_for(aum=1e12), "A222222": _panel_for(aum=1e12)}
    impl = compute_impl_score(panels, adv={"A111111": 1e10, "A222222": 1e8})
    assert impl["A111111"] > impl["A222222"]


def test_impl_score_penalizes_tracking_error():
    panels = {"A111111": _panel_for(aum=1e12), "A222222": _panel_for(aum=1e12)}
    impl = compute_impl_score(
        panels, tracking_error={"A111111": 0.001, "A222222": 0.02},
    )
    assert impl["A111111"] > impl["A222222"]


def test_impl_score_penalizes_abs_deviation():
    panels = {"A111111": _panel_for(aum=1e12), "A222222": _panel_for(aum=1e12)}
    impl = compute_impl_score(
        panels, deviation={"A111111": 0.001, "A222222": -0.05},
    )
    # |0.001| < |-0.05| → A111111 우대
    assert impl["A111111"] > impl["A222222"]


def test_impl_score_empty_panels():
    assert compute_impl_score({}) == {}


def test_impl_score_missing_ticker_in_signal_neutral():
    # adv 에 한 ticker만 있어도 깨지지 않음, 누락은 None → neutral
    panels = {"A111111": _panel_for(aum=1e12), "A222222": _panel_for(aum=1e12)}
    impl = compute_impl_score(panels, adv={"A111111": 1e10})
    assert "A111111" in impl and "A222222" in impl


# ---------- Stage 3: cluster-aware select ----------


from tradingagents.schemas.technical import Cluster
from tradingagents.skills.portfolio.factor_scorer import select_cluster_aware


def test_cluster_aware_within_picks_best_impl_not_alpha():
    # A1/A2 같은 cluster(대체재). A1 alpha 높지만 impl 낮음; A2 alpha 낮지만 impl 높음.
    # 그룹 내 대표 = impl 기준 → A2 선택. B는 singleton.
    alpha = {"A111111": 2.0, "A222222": 0.0, "B111111": 1.0}
    impl = {"A111111": 0.0, "A222222": 2.0, "B111111": 1.0}
    clusters = [Cluster(
        cluster_id="c1", members=["A111111", "A222222"],
        avg_internal_correlation=0.95, category_label="dup",
    )]
    chosen = select_cluster_aware(
        ["A111111", "A222222", "B111111"], alpha, impl, clusters, n=2, returns=None,
    )
    assert "A222222" in chosen and "A111111" not in chosen
    assert "B111111" in chosen


def test_cluster_aware_across_groups_ranked_by_alpha():
    alpha = {"X111111": 2.0, "Y111111": 0.5}
    impl = {"X111111": 0.0, "Y111111": 5.0}
    chosen = select_cluster_aware(
        ["X111111", "Y111111"], alpha, impl, clusters=[], n=1, returns=None,
    )
    assert chosen == ["X111111"]


def test_cluster_aware_pads_when_groups_fewer_than_n():
    # 그룹 1개(A1,A2 대체재), n=2 → 대표 1 + 패딩으로 2개.
    alpha = {"A111111": 2.0, "A222222": 1.0}
    impl = {"A111111": 2.0, "A222222": 0.0}
    clusters = [Cluster(
        cluster_id="c1", members=["A111111", "A222222"],
        avg_internal_correlation=0.95, category_label="dup",
    )]
    chosen = select_cluster_aware(
        ["A111111", "A222222"], alpha, impl, clusters, n=2, returns=None,
    )
    assert len(chosen) == 2
    assert set(chosen) == {"A111111", "A222222"}


def test_cluster_aware_singleton_not_in_any_cluster():
    # X 는 어느 cluster 에도 안 들어감 → singleton 으로 자동 처리
    alpha = {"X111111": 2.0, "A111111": 1.0, "A222222": 0.5}
    impl = {"X111111": 1.0, "A111111": 0.0, "A222222": 2.0}
    clusters = [Cluster(
        cluster_id="c1", members=["A111111", "A222222"],
        avg_internal_correlation=0.95, category_label="dup",
    )]
    chosen = select_cluster_aware(
        ["X111111", "A111111", "A222222"], alpha, impl, clusters, n=2, returns=None,
    )
    # 그룹 간 alpha 순: X(alpha=2.0) > A_group(max alpha=1.0)
    # 그룹 내 대표: X singleton → X / A_group → impl 최고 A222222
    assert set(chosen) == {"X111111", "A222222"}


def test_cluster_aware_fallback_to_corr_when_clusters_empty():
    # clusters 빈 dict + returns 제공 → corr-based fallback grouping.
    # A, B 강상관 (대체재) — 그룹 내 impl 최고 선택.
    import numpy as np, pandas as pd
    rng = np.random.default_rng(0)
    base = rng.normal(0, 0.01, 200)
    df = pd.DataFrame({
        "A111111": base,
        "A222222": base + rng.normal(0, 0.001, 200),  # ~corr 0.99
        "B111111": rng.normal(0, 0.01, 200),
    })
    alpha = {"A111111": 2.0, "A222222": 0.0, "B111111": 1.0}
    impl = {"A111111": 0.0, "A222222": 2.0, "B111111": 1.0}
    chosen = select_cluster_aware(
        ["A111111", "A222222", "B111111"], alpha, impl, clusters=None,
        n=2, returns=df, correlation_threshold=0.85,
    )
    # A 그룹 내 대표 impl 최고 = A222222, B singleton
    assert "A222222" in chosen and "B111111" in chosen
    assert "A111111" not in chosen


def test_cluster_aware_empty_inputs():
    assert select_cluster_aware([], {}, {}, [], n=3, returns=None) == []
    assert select_cluster_aware(["X111111"], {"X111111": 1.0}, {"X111111": 1.0},
                                [], n=0, returns=None) == []


def test_cluster_aware_skips_ticker_without_alpha():
    # alpha 에 없는 ticker는 eligible 에서 자동 제거 (Stage 1 누락 데이터 가드)
    alpha = {"A111111": 1.0}
    impl = {"A111111": 1.0, "A222222": 2.0}
    chosen = select_cluster_aware(
        ["A111111", "A222222"], alpha, impl, clusters=[], n=2, returns=None,
    )
    assert chosen == ["A111111"]


# ---- 2026-05-26 #1 fix: underlying_index 강제 cluster 통합 ----


def test_cluster_aware_underlying_index_forces_merge():
    """동일 underlying_index 의 ETF 가 다른 cluster 였더라도 강제 merge.

    S&P 500 추종 TIGER/KODEX/RISE 3 ETF 시나리오 (실제 backtest 버그).
    correlation cluster 가 분리해도 underlying_lookup 으로 같은 group.
    """
    tickers = ["A360750", "A379800", "A379780", "B999999"]
    alpha = {"A360750": 1.5, "A379800": 1.0, "A379780": 0.8, "B999999": 2.0}
    impl = {"A360750": 1.0, "A379800": 0.8, "A379780": 0.6, "B999999": 1.0}
    # cluster 가 분리 (S&P 500 3개가 singleton 으로 들어감 — 기존 silent bug 시나리오)
    clusters = []  # 빈 cluster
    underlying_lookup = {
        "A360750": "S&P 500",
        "A379800": "S&P 500",
        "A379780": "S&P 500",
        "B999999": "",  # 다른 ETF
    }
    chosen = select_cluster_aware(
        tickers, alpha, impl, clusters, n=4, returns=None,
        underlying_lookup=underlying_lookup,
    )
    # S&P 500 3개 중 1개만 + B999999 = 2개 선택 (n=4 padding 적용)
    sp500_chosen = [t for t in chosen if t in ("A360750", "A379800", "A379780")]
    assert len(sp500_chosen) == 1, f"expected 1 S&P 500 rep, got {sp500_chosen}"
    assert "B999999" in chosen


def test_cluster_aware_underlying_lookup_none_preserves_legacy():
    """underlying_lookup=None 면 기존 동작 그대로 (regression 안전)."""
    tickers = ["A111111", "A222222"]
    alpha = {"A111111": 2.0, "A222222": 1.0}
    impl = {"A111111": 1.0, "A222222": 1.0}
    chosen = select_cluster_aware(
        tickers, alpha, impl, clusters=[], n=2, returns=None,
        underlying_lookup=None,
    )
    assert set(chosen) == {"A111111", "A222222"}


def test_cluster_aware_underlying_empty_string_treated_as_unique():
    """underlying_index 가 빈 문자열인 ticker 는 grouping 안 함 (singleton 유지)."""
    tickers = ["A1", "A2", "A3"]
    alpha = {"A1": 1.0, "A2": 1.0, "A3": 1.0}
    impl = {"A1": 1.0, "A2": 1.0, "A3": 1.0}
    underlying_lookup = {"A1": "", "A2": "", "A3": ""}  # 모두 빈 underlying
    chosen = select_cluster_aware(
        tickers, alpha, impl, clusters=[], n=3, returns=None,
        underlying_lookup=underlying_lookup,
    )
    # 모두 unique → 3개 다 선택됨
    assert set(chosen) == {"A1", "A2", "A3"}
