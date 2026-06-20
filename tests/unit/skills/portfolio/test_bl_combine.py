import numpy as np
import pandas as pd
import pytest
from tradingagents.skills.portfolio import bl_engine as be


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
