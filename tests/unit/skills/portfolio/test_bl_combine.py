import numpy as np
import pandas as pd
import pytest
from tradingagents.skills.portfolio import bl_engine as be
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS


def _toy(n=5, seed=1):
    rng = np.random.default_rng(seed)
    A = rng.normal(0, 1, (n, n))
    Sigma = pd.DataFrame(A @ A.T / n * 0.04, index=[f"b{i}" for i in range(n)], columns=[f"b{i}" for i in range(n)])
    w = pd.Series(1.0 / n, index=Sigma.index)
    return Sigma, w


@pytest.mark.parametrize("delta", [1.0, 2.5, 4.0, 8.0])
def test_no_view_recovers_baseline_exact(delta):
    Sigma, w_base = _toy()
    w = be.bl_bucket_weights(Sigma, w_base, ranking={}, delta=delta, base_spread=0.04,
                             growth_keys=set(), mandate_risk_keys=set())
    assert np.allclose(w.values, w_base.values, atol=1e-6)   # arbitrary δ exact recovery


def test_split_delta_breaks_recovery():
    Sigma, w_base = _toy()
    w = be._bl_weights_split_delta(Sigma, w_base, delta_inv=2.5, delta_opt=8.0)
    assert not np.allclose(w.values, w_base.values, atol=1e-3)


def test_known_view_directionally_correct():
    Sigma, w_base = _toy()
    ranking = {"b0": ("strong_OW", 0.9), "b4": ("strong_UW", 0.9)}
    w = be.bl_bucket_weights(Sigma, w_base, ranking=ranking, delta=2.5, base_spread=0.04,
                             growth_keys=set(), mandate_risk_keys=set())
    assert w["b0"] > w_base["b0"]
    assert w["b4"] < w_base["b4"]
    assert abs(w.sum() - 1.0) < 1e-6


# --- Production-path constraint tests (MATH-1) ---------------------------------
# The toy tests above pass EMPTY constraint sets, so they never exercise the real
# mandate group-caps. These exercise the production path: 14-bucket baselines with
# the real growth + mandate-risk constraint groups bound to HARD_RISK_ASSET_CAP.

# Production risk proxy = a5_gold_infl ∪ GROWTH_KEYS (a5 + b1..b9), matching
# tests/unit/skills/portfolio/test_scenario_anchor.py RISK_PROXY.
_MANDATE_RISK = {"a5_gold_infl"} | set(GROWTH_KEYS)


def _real_sigma_14(seed=5):
    keys = list(QUADRANT_BASELINE["growth_disinflation"].keys())
    rng = np.random.default_rng(seed)
    vols = rng.uniform(0.05, 0.30, len(keys))
    C = rng.uniform(0.1, 0.6, (len(keys), len(keys))); C = (C + C.T) / 2; np.fill_diagonal(C, 1.0)
    S = np.outer(vols, vols) * C
    S = S @ S.T / len(keys) + np.eye(len(keys)) * 1e-4
    return pd.DataFrame(S, index=keys, columns=keys)


@pytest.mark.parametrize("quadrant", list(QUADRANT_BASELINE.keys()))
@pytest.mark.parametrize("delta", [1.0, 2.5, 5.0, 8.0])
def test_no_view_recovery_with_real_constraints(quadrant, delta):
    Sigma = _real_sigma_14()
    w_base = pd.Series(QUADRANT_BASELINE[quadrant]).reindex(Sigma.index)
    w = be.bl_bucket_weights(Sigma, w_base, ranking={}, delta=delta,
                             growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE_RISK)
    assert np.abs(w - w_base).sum() < 1e-6, f"{quadrant} δ={delta} L1={np.abs(w-w_base).sum()}"


def test_growth_inflation_recovers_at_cap_070():
    # regression for the 0.68→0.70 fix specifically (growth_inflation risk-proxy = 0.69)
    Sigma = _real_sigma_14()
    w_base = pd.Series(QUADRANT_BASELINE["growth_inflation"]).reindex(Sigma.index)
    w = be.bl_bucket_weights(Sigma, w_base, ranking={}, delta=2.5,
                             growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE_RISK)
    assert np.abs(w - w_base).sum() < 1e-6


def test_growth_ow_view_still_clamps_to_070():
    # An aggressive all-growth-OW view must still respect the hard mandate caps:
    # Σ(growth) ≤ 0.70 and Σ(risk proxy) ≤ 0.70 (constraints must remain binding).
    Sigma = _real_sigma_14()
    w_base = pd.Series(QUADRANT_BASELINE["growth_disinflation"]).reindex(Sigma.index)
    ranking = {k: ("strong_OW", 0.95) for k in GROWTH_KEYS}
    w = be.bl_bucket_weights(Sigma, w_base, ranking=ranking, delta=2.5,
                             growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE_RISK)
    growth_sum = float(w.reindex(list(GROWTH_KEYS)).sum())
    risk_sum = float(w.reindex(list(_MANDATE_RISK)).sum())
    assert growth_sum <= 0.70 + 1e-6, f"growth {growth_sum}"
    assert risk_sum <= 0.70 + 1e-6, f"risk {risk_sum}"
    # the view should actually push growth UP toward the cap (constraint binds)
    assert growth_sum > float(w_base.reindex(list(GROWTH_KEYS)).sum())
