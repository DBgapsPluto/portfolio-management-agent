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
    impl = compute_impl_score(panels, volume_per_aum={"A111111": 1e10, "A222222": 1e8})
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
        panels, premium_discount={"A111111": 0.001, "A222222": -0.05},
    )
    # |0.001| < |-0.05| → A111111 우대
    assert impl["A111111"] > impl["A222222"]


def test_impl_score_empty_panels():
    assert compute_impl_score({}) == {}


def test_impl_score_missing_ticker_in_signal_neutral():
    # volume_per_aum 에 한 ticker만 있어도 깨지지 않음, 누락은 None → neutral
    panels = {"A111111": _panel_for(aum=1e12), "A222222": _panel_for(aum=1e12)}
    impl = compute_impl_score(panels, volume_per_aum={"A111111": 1e10})
    assert "A111111" in impl and "A222222" in impl


# ---------- Phase 2a Task 7: impl_score 4-요소 weighted composite ----------


def test_impl_score_weight_magnitudes_sum_to_one():
    """IMPL_SCORE_WEIGHTS 의 절댓값 합 = 1.0."""
    from tradingagents.skills.portfolio.factor_scorer import IMPL_SCORE_WEIGHTS
    total = sum(abs(v) for v in IMPL_SCORE_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9


def test_impl_score_4factor_composite():
    """4-요소 가중치 합성 — log_aum + TE + |pd| + volume/AUM."""
    import math

    from tradingagents.skills.portfolio.factor_scorer import (
        FactorPanel, compute_impl_score,
    )

    panels = {
        "A": FactorPanel(log_aum=math.log(10_000_000_000_000)),  # 10조
        "B": FactorPanel(log_aum=math.log(1_000_000_000_000)),   # 1조
        "C": FactorPanel(log_aum=math.log(100_000_000_000)),     # 1000억
    }
    # A 최고 quality, C 최저 quality
    tracking_error = {"A": 0.05, "B": 0.20, "C": 0.50}
    premium_discount = {"A": 0.001, "B": 0.005, "C": 0.020}
    volume_per_aum = {"A": 0.005, "B": 0.001, "C": 0.0001}
    impl = compute_impl_score(
        panels,
        tracking_error=tracking_error,
        premium_discount=premium_discount,
        volume_per_aum=volume_per_aum,
    )
    assert impl["A"] > impl["B"] > impl["C"]


def test_impl_score_missing_signals_falls_back_to_log_aum():
    """모든 metrics 신호 None → impl_score 가 log_aum 단독 ordering."""
    import math

    from tradingagents.skills.portfolio.factor_scorer import (
        FactorPanel, compute_impl_score,
    )

    panels = {
        "A": FactorPanel(log_aum=math.log(10_000_000_000_000)),
        "B": FactorPanel(log_aum=math.log(1_000_000_000_000)),
        "C": FactorPanel(log_aum=math.log(100_000_000_000)),
    }
    impl_no_metrics = compute_impl_score(panels)
    assert impl_no_metrics["A"] > impl_no_metrics["B"] > impl_no_metrics["C"]


def test_impl_score_high_te_lowers_score():
    """동일 log_aum 일 때 TE 높은 ETF 가 낮은 impl."""
    import math

    from tradingagents.skills.portfolio.factor_scorer import (
        FactorPanel, compute_impl_score,
    )

    panels = {
        "low_te": FactorPanel(log_aum=math.log(1_000_000_000_000)),
        "high_te": FactorPanel(log_aum=math.log(1_000_000_000_000)),
    }
    tracking_error = {"low_te": 0.05, "high_te": 0.50}
    premium_discount = {"low_te": 0.001, "high_te": 0.001}
    volume_per_aum = {"low_te": 0.001, "high_te": 0.001}
    impl = compute_impl_score(
        panels, tracking_error=tracking_error,
        premium_discount=premium_discount,
        volume_per_aum=volume_per_aum,
    )
    assert impl["low_te"] > impl["high_te"]


def test_impl_score_high_premium_discount_lowers_score():
    """동일 log_aum 일 때 |괴리율| 큰 ETF 가 낮은 impl."""
    import math

    from tradingagents.skills.portfolio.factor_scorer import (
        FactorPanel, compute_impl_score,
    )

    panels = {
        "low_pd": FactorPanel(log_aum=math.log(1_000_000_000_000)),
        "high_pd": FactorPanel(log_aum=math.log(1_000_000_000_000)),
    }
    premium_discount = {"low_pd": 0.0005, "high_pd": 0.020}
    tracking_error = {"low_pd": 0.05, "high_pd": 0.05}
    volume_per_aum = {"low_pd": 0.001, "high_pd": 0.001}
    impl = compute_impl_score(
        panels, premium_discount=premium_discount,
        tracking_error=tracking_error,
        volume_per_aum=volume_per_aum,
    )
    assert impl["low_pd"] > impl["high_pd"]


def test_impl_score_high_volume_per_aum_raises_score():
    """동일 log_aum 일 때 volume/AUM 큰 ETF 가 높은 impl."""
    import math

    from tradingagents.skills.portfolio.factor_scorer import (
        FactorPanel, compute_impl_score,
    )

    panels = {
        "high_vol": FactorPanel(log_aum=math.log(1_000_000_000_000)),
        "low_vol": FactorPanel(log_aum=math.log(1_000_000_000_000)),
    }
    volume_per_aum = {"high_vol": 0.010, "low_vol": 0.0001}
    tracking_error = {"high_vol": 0.05, "low_vol": 0.05}
    premium_discount = {"high_vol": 0.001, "low_vol": 0.001}
    impl = compute_impl_score(
        panels, volume_per_aum=volume_per_aum,
        tracking_error=tracking_error,
        premium_discount=premium_discount,
    )
    assert impl["high_vol"] > impl["low_vol"]


# ---------- Phase 2b Task 1: compute_adaptive_n_max ----------


def test_compute_adaptive_n_max_alpha_cap():
    """양수 alpha 후보 수가 가장 작으면 그 값이 n_max."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=3,
        bucket_weight=0.30,
        capital_krw=1_000_000_000_000,
    )
    assert n == 3


def test_compute_adaptive_n_max_weight_cap():
    """작은 bucket weight → weight cap."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=100,
        bucket_weight=0.05,
        capital_krw=1_000_000_000_000,
    )
    assert n == 2


def test_compute_adaptive_n_max_capital_cap():
    """1B 자본 + 10% bucket → 100M / 50M = 2."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=10,
        bucket_weight=0.10,
        capital_krw=1_000_000_000,
    )
    assert n == 2


def test_compute_adaptive_n_max_abs_max():
    """모든 cap 큼 → 8."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=20,
        bucket_weight=0.50,
        capital_krw=100_000_000_000,
    )
    assert n == 8


def test_compute_adaptive_n_max_zero_bucket_weight():
    """bucket_weight = 0 → 0."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=10, bucket_weight=0.0, capital_krw=1_000_000_000,
    )
    assert n == 0


def test_compute_adaptive_n_max_zero_positive_alpha():
    """positive_alpha = 0 → 0."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=0, bucket_weight=0.30, capital_krw=1_000_000_000,
    )
    assert n == 0


# ---------- Phase 2b Task 2: _enb_equal_weight ----------


def test_enb_equal_weight_single_ticker():
    """1 종목 → ENB = 1.0."""
    import pandas as pd
    import numpy as np
    from tradingagents.skills.portfolio.factor_scorer import _enb_equal_weight

    sigma = pd.DataFrame(
        np.eye(3) * 0.04,
        index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    assert _enb_equal_weight(["A"], sigma) == 1.0


def test_enb_equal_weight_empty():
    """0 종목 → 0.0."""
    import pandas as pd
    import numpy as np
    from tradingagents.skills.portfolio.factor_scorer import _enb_equal_weight

    sigma = pd.DataFrame(np.eye(2) * 0.04, index=["A", "B"], columns=["A", "B"])
    assert _enb_equal_weight([], sigma) == 0.0


def test_enb_equal_weight_uncorrelated_pair_close_to_two():
    """2 종목 uncorrelated → ENB ≈ 2."""
    import pandas as pd
    import numpy as np
    from tradingagents.skills.portfolio.factor_scorer import _enb_equal_weight

    sigma = pd.DataFrame(
        np.eye(2) * 0.04,
        index=["A", "B"], columns=["A", "B"],
    )
    enb = _enb_equal_weight(["A", "B"], sigma)
    assert 1.95 < enb < 2.05


# ---------- Phase 2b Task 3: select_by_enb_greedy ----------


def _make_diag_sigma(tickers, vol=0.04):
    import pandas as pd
    import numpy as np
    n = len(tickers)
    return pd.DataFrame(np.eye(n) * vol, index=tickers, columns=tickers)


def _make_dup_sigma(tickers, vol=0.04, rho=0.999):
    import pandas as pd
    import numpy as np
    n = len(tickers)
    corr = np.full((n, n), rho)
    np.fill_diagonal(corr, 1.0)
    return pd.DataFrame(corr * vol, index=tickers, columns=tickers)


def test_select_by_enb_greedy_seed_from_top_composite():
    """Seed = (alpha_impl_blend × z(alpha) + (1 - blend) × z(impl)) 1등."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C"]
    alpha = {"A": 0.1, "B": 0.5, "C": 0.3}
    impl = {"A": 0.0, "B": 0.0, "C": 0.0}
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=1,
    )
    assert chosen == ["B"]


def test_select_by_enb_greedy_alpha_floor_only_positive():
    """음수 alpha 제외."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C", "D"]
    alpha = {"A": 0.5, "B": -0.1, "C": -0.2, "D": -0.3}
    impl = {t: 0.0 for t in eligible}
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=4,
    )
    assert chosen == ["A"]


def test_select_by_enb_greedy_handles_no_positive_alpha():
    """양수 alpha 없으면 빈 list."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B"]
    alpha = {"A": -0.1, "B": -0.2}
    impl = {"A": 0.0, "B": 0.0}
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=3,
    )
    assert chosen == []


def test_select_by_enb_greedy_n_max_zero_returns_empty():
    """n_max = 0 → 빈 list."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B"]
    alpha = {"A": 0.5, "B": 0.3}
    impl = {"A": 0.0, "B": 0.0}
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=0,
    )
    assert chosen == []


def test_select_by_enb_greedy_stops_at_n_max():
    """n_max=2 도달 시 중단."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C", "D"]
    alpha = {t: 0.5 for t in eligible}
    impl = {t: 0.0 for t in eligible}
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=2,
    )
    assert len(chosen) == 2


def test_select_by_enb_greedy_duplicates_picked_once():
    """corr ≈ 1 인 3 ETF → seed 1개만."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C"]
    alpha = {t: 0.5 for t in eligible}
    impl = {t: 0.0 for t in eligible}
    sigma = _make_dup_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=3,
    )
    assert len(chosen) == 1


def test_select_by_enb_greedy_attribution_progression_recorded():
    """selection_trace 채움."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C", "D"]
    alpha = {"A": 0.5, "B": 0.3, "C": -0.1, "D": 0.4}
    impl = {t: 0.0 for t in eligible}
    sigma = _make_diag_sigma(eligible)
    trace: dict = {}
    select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=3, selection_trace=trace,
    )
    assert "stop_reason" in trace
    assert "enb_progression" in trace
    assert "rejected" in trace
    assert "alpha_impl_blend_used" in trace
    rejected_alpha_neg = [r for r in trace["rejected"] if r.get("reason") == "alpha_negative"]
    assert any(r["ticker"] == "C" for r in rejected_alpha_neg)


def test_select_by_enb_greedy_alpha_impl_blend_weighting():
    """alpha 동등 → impl 큰 쪽 우선."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B"]
    alpha = {"A": 0.5, "B": 0.5}
    impl = {"A": 0.1, "B": 0.9}
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=1,
    )
    assert chosen == ["B"]


def test_select_by_enb_greedy_stops_at_delta_threshold():
    """corr ≈ 1 시 delta 미달 stop."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C"]
    alpha = {t: 0.5 for t in eligible}
    impl = {t: 0.0 for t in eligible}
    sigma = _make_dup_sigma(eligible)
    trace: dict = {}
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=3, selection_trace=trace,
    )
    assert len(chosen) == 1
    assert trace["stop_reason"] == "delta_below_threshold"
