"""Unit tests for statistics.py — paired-t, Cohen's d, regime decomp, drawdown."""
import numpy as np
import pytest

from tradingagents.backtest.statistics import (
    cohens_d,
    drawdown_analysis,
    paired_t_vs_benchmark,
    regime_decomposition,
)


def test_paired_t_calibrated_strictly_higher_returns_low_p() -> None:
    """Calibrated 의 모든 fold OOS Sharpe 가 benchmark 보다 크면 p << 0.5."""
    calibrated = np.array([0.8, 0.9, 1.0, 1.1, 0.85, 0.95, 1.05])
    benchmark = np.array([0.3, 0.4, 0.5, 0.4, 0.35, 0.45, 0.5])
    result = paired_t_vs_benchmark(calibrated, benchmark)
    assert result["paired_t_p"] < 0.05
    assert result["mean_diff"] > 0


def test_paired_t_same_distributions_returns_high_p() -> None:
    """동일 분포 → p ≈ 0.5."""
    rng = np.random.default_rng(42)
    a = rng.standard_normal(20)
    b = a.copy()
    result = paired_t_vs_benchmark(a, b)
    assert result["mean_diff"] == pytest.approx(0.0)
    assert result["paired_t_p"] >= 0.49


def test_cohens_d_zero_for_identical_distributions() -> None:
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert cohens_d(a, b) == pytest.approx(0.0)


def test_cohens_d_positive_for_higher_calibrated() -> None:
    a = np.array([2.0, 3.0, 4.0])
    b = np.array([0.0, 1.0, 2.0])
    d = cohens_d(a, b)
    assert d > 0
    assert d > 0.8


def test_regime_decomposition_separates_recession_returns() -> None:
    """recession mask = True 인 sample 의 return 으로 별도 Sharpe."""
    returns = {"calibrated": np.array([0.05, -0.10, 0.08, -0.15, 0.04, 0.06])}
    recession = np.array([False, True, False, True, False, False])
    result = regime_decomposition(returns, recession)
    assert "calibrated" in result
    assert result["calibrated"]["expansion_mean"] > 0
    assert result["calibrated"]["recession_mean"] < 0
    assert result["calibrated"]["expansion_n"] == 4
    assert result["calibrated"]["recession_n"] == 2


def test_drawdown_analysis_max_drawdown_recovery() -> None:
    """returns [0.1, -0.5, 0.2, 0.3] — drawdown at q=1, recovery not achieved."""
    returns = np.array([0.1, -0.5, 0.2, 0.3])
    result = drawdown_analysis(returns)
    assert result["max_drawdown"] == pytest.approx(-0.50, abs=1e-3)
    assert result["drawdown_peak_idx"] == 0
    assert result["drawdown_trough_idx"] == 1
    assert result["recovery_idx"] is None


def test_drawdown_analysis_recovered() -> None:
    """returns [0.1, -0.5, 0.5, 0.5] — recovery achieved at end."""
    returns = np.array([0.1, -0.5, 0.5, 0.5])
    result = drawdown_analysis(returns)
    assert result["recovery_idx"] == 3
