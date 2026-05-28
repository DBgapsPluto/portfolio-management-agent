"""Statistical tests for PR2b validation:
- paired_t_vs_benchmark: scipy ttest_rel + mean diff
- cohens_d: standardized mean difference (effect size, important for small N)
- regime_decomposition: per-strategy Sharpe in expansion / recession
- drawdown_analysis: max drawdown + recovery from cumulative returns
"""
from __future__ import annotations

import logging
from typing import Mapping

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


def paired_t_vs_benchmark(
    calibrated_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    alternative: str = "greater",
) -> dict:
    """Paired-t test: H0 mean(calibrated - benchmark) = 0.

    Args:
        calibrated_returns: per-fold or per-quarter return array.
        benchmark_returns: matching length, paired.
        alternative: "greater" (default — calibrated > benchmark) or "two-sided".

    Returns:
        {
            "mean_diff": float (calibrated - benchmark mean),
            "paired_t_stat": float,
            "paired_t_p": float ∈ [0, 1],
            "cohens_d": float (effect size),
            "n": int,
        }
    """
    n = min(len(calibrated_returns), len(benchmark_returns))
    if n < 2:
        return {
            "mean_diff": 0.0, "paired_t_stat": 0.0,
            "paired_t_p": 1.0, "cohens_d": 0.0, "n": n,
        }
    a = np.asarray(calibrated_returns[:n], dtype=float)
    b = np.asarray(benchmark_returns[:n], dtype=float)
    try:
        result = stats.ttest_rel(a, b, alternative=alternative)
        t_stat = float(result.statistic)
        p_value = float(result.pvalue)
        # NaN (identical sequences, zero variance) → no evidence of difference.
        if np.isnan(t_stat):
            t_stat = 0.0
        if np.isnan(p_value):
            p_value = 1.0
    except Exception as e:
        logger.warning("paired-t failed: %s", e)
        t_stat, p_value = 0.0, 1.0
    return {
        "mean_diff": float(np.mean(a - b)),
        "paired_t_stat": t_stat,
        "paired_t_p": p_value,
        "cohens_d": cohens_d(a, b),
        "n": n,
    }


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Cohen's d effect size: (mean_a - mean_b) / pooled_std.

    Interpretation:
        |d| < 0.2  — negligible
        |d| < 0.5  — small
        |d| < 0.8  — medium
        |d| ≥ 0.8  — large

    Important for small N (e.g., NBER recession N=13) where paired-t p
    has low power.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return 0.0
    var_a, var_b = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    pooled = np.sqrt(((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2))
    if pooled <= 0:
        return 0.0
    return float((np.mean(a) - np.mean(b)) / pooled)


def regime_decomposition(
    returns_per_strategy: Mapping[str, np.ndarray],
    recession_mask: np.ndarray,
) -> dict:
    """Per-strategy mean return + Sharpe in expansion vs recession.

    Args:
        returns_per_strategy: {strategy_name: per-quarter return array}.
        recession_mask: bool array, True = recession quarter.

    Returns:
        {strategy: {expansion_mean, expansion_std, expansion_sharpe, expansion_n,
                     recession_mean, recession_std, recession_sharpe, recession_n}}
    """
    rec_mask = np.asarray(recession_mask, dtype=bool)
    exp_mask = ~rec_mask
    out = {}
    for name, returns in returns_per_strategy.items():
        r = np.asarray(returns, dtype=float)
        n = min(len(r), len(rec_mask))
        r = r[:n]
        exp_r = r[exp_mask[:n]]
        rec_r = r[rec_mask[:n]]
        out[name] = {
            "expansion_mean": float(np.mean(exp_r)) if len(exp_r) else 0.0,
            "expansion_std":  float(np.std(exp_r, ddof=1)) if len(exp_r) > 1 else 0.0,
            "expansion_sharpe": _sharpe(exp_r),
            "expansion_n": int(len(exp_r)),
            "recession_mean": float(np.mean(rec_r)) if len(rec_r) else 0.0,
            "recession_std":  float(np.std(rec_r, ddof=1)) if len(rec_r) > 1 else 0.0,
            "recession_sharpe": _sharpe(rec_r),
            "recession_n": int(len(rec_r)),
        }
    return out


def _sharpe(returns: np.ndarray, periods_per_year: int = 4) -> float:
    """Annualized Sharpe (quarterly default). 0.0 if std≤0 or len<2."""
    if len(returns) < 2:
        return 0.0
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    if std <= 0:
        return 0.0
    return mean / std * np.sqrt(periods_per_year)


def drawdown_analysis(returns: np.ndarray) -> dict:
    """Max drawdown + recovery from cumulative wealth.

    Args:
        returns: per-period return array (e.g., quarterly).

    Returns:
        {
            "max_drawdown": float (worst peak-to-trough fractional loss, ≤ 0),
            "drawdown_peak_idx": int (index of peak before max DD),
            "drawdown_trough_idx": int (index of trough at max DD),
            "recovery_idx": int | None (index when cumulative returns to peak),
            "duration_quarters": int (trough - peak),
        }
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 1:
        return {
            "max_drawdown": 0.0, "drawdown_peak_idx": 0,
            "drawdown_trough_idx": 0, "recovery_idx": None,
            "duration_quarters": 0,
        }
    cumulative = np.cumprod(1 + r)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - running_max) / running_max
    trough_idx = int(np.argmin(drawdown))
    max_dd = float(drawdown[trough_idx])
    peak_value = running_max[trough_idx]
    peak_idx = int(np.where(cumulative[:trough_idx + 1] >= peak_value - 1e-12)[0][0]) \
        if trough_idx >= 0 else 0
    recovery_idx = None
    for i in range(trough_idx + 1, len(cumulative)):
        if cumulative[i] >= peak_value - 1e-12:
            recovery_idx = i
            break
    return {
        "max_drawdown": max_dd,
        "drawdown_peak_idx": peak_idx,
        "drawdown_trough_idx": trough_idx,
        "recovery_idx": recovery_idx,
        "duration_quarters": trough_idx - peak_idx,
    }
