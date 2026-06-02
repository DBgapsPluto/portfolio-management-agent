"""Regression: candidate-selection covariance must survive a recently-listed ETF.

Backtest 2023-04-14 / 2024-08-14 FAILED ("Too few candidates"). Root cause: the
allocator built the candidate-selection sigma with
`returns.dropna(axis=0, how="any").cov()`. When the eligible set contains a
recently-listed ETF (NaN before its listing date), `dropna(how="any")` keeps only
rows where EVERY ticker has data → the common window collapses to ~0 rows → the
cov is degenerate/NaN. Downstream, `select_etf_candidates` drops every ticker
whose sigma row is all-NaN, so positive-alpha tickers vanish and 0 candidates are
chosen.

The fix (in portfolio_allocator.py ~line 131) uses a pairwise-complete cov with a
positive-floored diagonal so no ticker is dropped. This test pins both halves:
the OLD approach is degenerate, the NEW approach is NaN-free, full-index, and
accepted by `minimum_torsion_matrix` (the downstream consumer).
"""
import numpy as np
import pandas as pd

from tradingagents.agents.allocator.portfolio_allocator import MIN_COV_OBS_CANDIDATE
from tradingagents.skills.portfolio.diversification import minimum_torsion_matrix


def _make_returns_with_short_history(overlap: int = 1) -> pd.DataFrame:
    """10 tickers, 250 rows; ONE ticker has data only in the last `overlap` rows.

    Default overlap=1 models an ETF listed days before `as_of`: the common-data
    window collapses to a single row, so the OLD `dropna(how="any").cov()` hits
    "Degrees of freedom <= 0" / "divide by zero" and yields a NaN covariance.
    """
    rng = np.random.default_rng(42)
    n_rows, n_full = 250, 9
    data = {f"A{i:06d}": rng.normal(0.0, 0.01, n_rows) for i in range(n_full)}
    df = pd.DataFrame(data)
    short = np.full(n_rows, np.nan)
    short[-overlap:] = rng.normal(0.0, 0.01, overlap)
    df["A999999"] = short
    return df


def _fix_sigma(returns: pd.DataFrame) -> pd.DataFrame:
    """Exact pairwise-complete sigma expression used in portfolio_allocator.py."""
    sigma = returns.cov(min_periods=MIN_COV_OBS_CANDIDATE)
    _var = returns.var()
    _diag = _var.reindex(sigma.index).to_numpy()
    _diag = np.where(np.isfinite(_diag) & (_diag > 0), _diag, 1e-8)
    sigma = sigma.fillna(0.0)
    np.fill_diagonal(sigma.values, _diag)
    return sigma


def test_old_dropna_how_any_cov_is_degenerate():
    """The OLD approach collapses to the short ETF's 20-row window and degenerates."""
    returns = _make_returns_with_short_history()

    common = returns.dropna(axis=0, how="any")
    # Common-data window collapses to the short ETF's single overlapping row.
    assert common.shape[0] <= 1

    old_sigma = common.cov()  # RuntimeWarning: DoF<=0 / divide by zero
    # Degenerate: NaN present (DoF<=0 / empty-slice) OR a non-positive diagonal,
    # either of which starves candidate selection downstream.
    diag = np.diag(old_sigma.to_numpy())
    assert bool(np.isnan(old_sigma.to_numpy()).any()) or bool((diag <= 0).any())


def test_fix_sigma_is_nanfree_full_index_and_torsion_accepts():
    """The NEW pairwise-complete sigma keeps every ticker and is torsion-ready."""
    returns = _make_returns_with_short_history()

    sigma = _fix_sigma(returns)

    # No NaN anywhere.
    assert not bool(np.isnan(sigma.to_numpy()).any())
    # No ticker dropped — index/columns match the full returns universe.
    assert list(sigma.index) == list(returns.columns)
    assert list(sigma.columns) == list(returns.columns)
    # Strictly-positive diagonal → minimum_torsion_matrix accepts it (no raise).
    assert bool((np.diag(sigma.to_numpy()) > 0).all())
    # Symmetric + positive diagonal: the real downstream consumer must not raise.
    T = minimum_torsion_matrix(sigma.to_numpy())
    assert T.shape == (len(returns.columns), len(returns.columns))


def test_red_green_old_sigma_rejected_by_torsion():
    """RED→GREEN pin: the OLD sigma would crash/NaN the downstream path the fix saves."""
    returns = _make_returns_with_short_history()

    old_sigma = returns.dropna(axis=0, how="any").cov()
    old_arr = old_sigma.to_numpy()
    # The fix is necessary precisely because the old sigma is NOT usable downstream:
    # either it contains NaN, or minimum_torsion_matrix raises on its bad diagonal.
    old_unusable = bool(np.isnan(old_arr).any())
    if not old_unusable:
        try:
            minimum_torsion_matrix(old_arr)
        except ValueError:
            old_unusable = True
    assert old_unusable

    # The fix is usable: NaN-free and torsion-accepted.
    minimum_torsion_matrix(_fix_sigma(returns).to_numpy())  # must not raise
