"""factor_calibration unit tests (synthetic data)."""
from __future__ import annotations

import numpy as np

from tradingagents.skills.research.factor_calibration import (
    HistoricalSample,
    aggregate_median_beta,
    benchmark_60_40_returns,
    compute_sharpe,
    hybrid_calibration,
    simulate_portfolio_returns,
    walk_forward,
)
from tradingagents.skills.research.factor_to_bucket import FACTORS, INITIAL_BETA


def test_historically_unidentifiable_factors_are_f11_f12():
    """F11 (earnings_revision) and F12 (china_credit_impulse) have NO historical
    signal in the panel (all-NaN / constant) — they carry zero gradient and stay
    pinned to prior. The calibration must declare them unidentifiable so the
    overfitting gate's denominator reflects params the data can actually fit."""
    from tradingagents.skills.research.factor_calibration import (
        HISTORICALLY_UNIDENTIFIABLE_FACTORS,
    )
    assert HISTORICALLY_UNIDENTIFIABLE_FACTORS == frozenset(
        {"F11_earnings_revision", "F12_china_credit_impulse"}
    )


def test_count_free_beta_params_excludes_unidentifiable_factors():
    """Honest free-β count = all (factor,bucket) cells minus hard-zeros minus the
    cells of historically-unidentifiable factors (NOT gate-gaming: those cells are
    constants pinned to prior, never fit)."""
    from tradingagents.skills.research.factor_calibration import (
        HARD_ZERO_CELLS,
        HISTORICALLY_UNIDENTIFIABLE_FACTORS,
        count_free_beta_params,
    )
    from tradingagents.skills.research.factor_to_bucket import BUCKETS as _B
    from tradingagents.skills.research.factor_to_bucket import FACTORS as _F
    naive = sum(1 for f in _F for b in _B if (f, b) not in HARD_ZERO_CELLS)
    removed = sum(
        1 for f in HISTORICALLY_UNIDENTIFIABLE_FACTORS for b in _B
        if (f, b) not in HARD_ZERO_CELLS
    )
    assert count_free_beta_params() == naive - removed
    assert count_free_beta_params() < naive  # strictly fewer than the naive 73


def _synthetic_samples(n: int = 50, seed: int = 42) -> list[HistoricalSample]:
    np.random.seed(seed)
    samples = []
    for q in range(n):
        factor_z = {f: float(np.random.normal(0, 1)) for f in FACTORS}
        bucket_returns = {
            "kr_equity":             0.02 + 0.02 * factor_z["F1_growth"] + float(np.random.normal(0, 0.05)),
            "global_equity":         0.02 + 0.03 * factor_z["F1_growth"] + float(np.random.normal(0, 0.05)),
            "precious_metals":       0.005 + float(np.random.normal(0, 0.03)),
            "cyclical_commodity_fx": 0.005 + float(np.random.normal(0, 0.04)),
            "kr_bond":               0.01 - 0.01 * factor_z["F1_growth"] + float(np.random.normal(0, 0.02)),
            "credit":                0.008 + float(np.random.normal(0, 0.015)),
            "global_duration":       0.01 - 0.008 * factor_z["F1_growth"] + float(np.random.normal(0, 0.02)),
            "cash_mmf":              0.005 + float(np.random.normal(0, 0.002)),
        }
        samples.append(
            HistoricalSample(
                date=f"2010-{(q % 12) + 1:02d}-01",
                factor_z=factor_z,
                bucket_returns_next=bucket_returns,
            )
        )
    return samples


def test_simulate_portfolio_returns_returns_array():
    samples = _synthetic_samples(10)
    rets = simulate_portfolio_returns(samples, INITIAL_BETA)
    assert isinstance(rets, np.ndarray)
    assert len(rets) == 10


def test_compute_sharpe_basic():
    rets = np.array([0.01, 0.02, -0.01, 0.015])
    sharpe = compute_sharpe(rets)
    assert isinstance(sharpe, float)
    assert sharpe != 0.0


def test_compute_sharpe_zero_std():
    rets = np.array([0.01, 0.01, 0.01])
    assert compute_sharpe(rets) == 0.0


def test_hybrid_calibration_returns_valid_beta():
    samples = _synthetic_samples(50)
    beta, sharpe = hybrid_calibration(samples, shrinkage=0.5)
    assert isinstance(beta, dict)
    assert len(beta) == len(INITIAL_BETA)
    # Each (factor, bucket) present
    for key in INITIAL_BETA:
        assert key in beta
    # Sharpe is finite
    assert np.isfinite(sharpe)


def test_walk_forward_produces_folds():
    samples = _synthetic_samples(100)
    folds = walk_forward(samples, initial_train_size=40, test_window=4)
    assert len(folds) > 0
    for f in folds:
        assert f.oos_sharpe is not None
        assert f.in_sample_sharpe is not None


def test_aggregate_median_beta():
    samples = _synthetic_samples(80)
    folds = walk_forward(samples, initial_train_size=40, test_window=4)
    median = aggregate_median_beta(folds)
    assert isinstance(median, dict)
    for key in INITIAL_BETA:
        assert key in median


def test_benchmark_60_40_returns():
    samples = _synthetic_samples(20)
    rets = benchmark_60_40_returns(samples)
    assert len(rets) == 20


# ---------------------------------------------------------------------------
# Tier 2: Tasks 6, 7, 9 — new tests
# ---------------------------------------------------------------------------


def test_hard_zero_cells_23_entries():
    from tradingagents.skills.research.factor_calibration import HARD_ZERO_CELLS
    assert len(HARD_ZERO_CELLS) == 23
    assert ("F1_growth", "precious_metals") in HARD_ZERO_CELLS
    assert ("F8_valuation", "precious_metals") in HARD_ZERO_CELLS
    assert ("F11_earnings_revision", "precious_metals") in HARD_ZERO_CELLS


def test_hard_zero_cells_consistent_with_prior():
    """Every hard-zero cell must have a ~0 prior in INITIAL_BETA (else the
    theoretical exclusion contradicts the hand-coded prior)."""
    from tradingagents.skills.research.factor_calibration import HARD_ZERO_CELLS
    from tradingagents.skills.research.factor_to_bucket import INITIAL_BETA
    bad = [(k, INITIAL_BETA[k]) for k in HARD_ZERO_CELLS
           if abs(INITIAL_BETA.get(k, 0.0)) > 0.02]
    assert not bad, f"hard-zero cells with non-trivial prior: {bad}"


def test_bucket_families_5_families():
    from tradingagents.skills.research.factor_calibration import BUCKET_FAMILIES, bucket_family
    assert set(BUCKET_FAMILIES.keys()) == {"equity", "commodity", "duration", "credit", "cash"}
    assert "kr_equity" in BUCKET_FAMILIES["equity"]
    assert "precious_metals" in BUCKET_FAMILIES["commodity"]
    assert "kr_bond" in BUCKET_FAMILIES["duration"]
    assert BUCKET_FAMILIES["credit"] == ["credit"]
    assert BUCKET_FAMILIES["cash"] == ["cash_mmf"]
    assert bucket_family("kr_equity") == "equity"
    assert bucket_family("cash_mmf") == "cash"


def test_hard_zero_cells_cover_all_8_buckets_for_factors():
    """Every hard-zero (f,b) must reference a real 8-bucket name."""
    from tradingagents.skills.research.factor_calibration import HARD_ZERO_CELLS
    from tradingagents.skills.research.factor_to_bucket import BUCKETS, FACTORS
    for (f, b) in HARD_ZERO_CELLS:
        assert f in FACTORS, f"{f} not a factor"
        assert b in BUCKETS, f"{b} not a bucket"


def test_simulate_per_factor_aware_skips_nan():
    from tradingagents.skills.research.factor_calibration import (
        simulate_portfolio_returns_per_factor_aware, HistoricalSample,
    )
    from tradingagents.skills.research.factor_to_bucket import INITIAL_BASELINE, FACTORS
    samples = [
        HistoricalSample(
            date="2020-03-31",
            factor_z={"F1_growth": float("nan"),
                      **{f: 0.0 for f in FACTORS if f != "F1_growth"}},
            bucket_returns_next={b: 0.01 for b in INITIAL_BASELINE},
        ),
    ]
    beta = {(f, b): 0.05 for f in FACTORS for b in INITIAL_BASELINE}
    returns = simulate_portfolio_returns_per_factor_aware(samples, beta)
    assert len(returns) == 1
    # all-zero (after NaN skip of F1) → baseline projected → ret = sum(baseline*0.01) = 0.01
    assert abs(returns[0] - 0.01) < 1e-9


def test_simulate_per_factor_aware_all_factors_present():
    """No NaN → all factors contribute (sanity, returns finite)."""
    from tradingagents.skills.research.factor_calibration import (
        simulate_portfolio_returns_per_factor_aware, HistoricalSample,
    )
    from tradingagents.skills.research.factor_to_bucket import INITIAL_BASELINE, FACTORS, INITIAL_BETA
    samples = [
        HistoricalSample(
            date="2020-03-31",
            factor_z={f: 0.5 for f in FACTORS},
            bucket_returns_next={b: 0.0 for b in INITIAL_BASELINE},
        ),
    ]
    returns = simulate_portfolio_returns_per_factor_aware(samples, INITIAL_BETA)
    assert len(returns) == 1
    assert np.isfinite(returns[0])


def test_compute_effective_df_monotone_in_lambda():
    from tradingagents.skills.research.factor_calibration import compute_effective_df
    np.random.seed(42)
    X = np.random.randn(100, 50)
    df_small = compute_effective_df(X, 0.01)
    df_large = compute_effective_df(X, 100.0)
    df_huge = compute_effective_df(X, 1e6)
    assert df_small > df_large   # monotone: larger λ → fewer effective df
    assert df_large < df_small   # redundant but explicit
    assert df_huge < 1.0         # extreme shrinkage → near-zero effective df


def test_compute_vif_matrix_detects_collinearity():
    from tradingagents.skills.research.factor_calibration import (
        compute_vif_matrix, HistoricalSample,
    )
    np.random.seed(1)
    # 3 factors: f3 = f1 + small noise (high VIF), f2 independent
    n = 200
    f1 = np.random.randn(n)
    f2 = np.random.randn(n)
    f3 = f1 + 0.01 * np.random.randn(n)  # nearly collinear with f1
    samples = [
        HistoricalSample(date=f"d{i}",
                         factor_z={"f1": f1[i], "f2": f2[i], "f3": f3[i]},
                         bucket_returns_next={})
        for i in range(n)
    ]
    vif = compute_vif_matrix(samples, ["f1", "f2", "f3"])
    assert vif["f1"] > 5.0   # collinear with f3
    assert vif["f3"] > 5.0
    assert vif["f2"] < 3.0   # independent
