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
