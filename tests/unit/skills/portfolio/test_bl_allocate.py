import numpy as np
import pandas as pd
import pytest
from tradingagents.skills.portfolio import bl_engine as be
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS, GROWTH_KEYS

def _sigma14(pinned=()):
    keep = [b for b in GAPS_BUCKET_KEYS if b not in pinned]
    rng = np.random.default_rng(2)
    A = rng.normal(0, 1, (len(keep), len(keep)))
    return pd.DataFrame(A @ A.T / len(keep) * 0.04, index=keep, columns=keep)

def _baseline14():
    from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE
    return pd.Series(QUADRANT_BASELINE["growth_disinflation"])

def test_pinned_bucket_fixed_others_bl():
    Sigma = _sigma14(pinned=("b4_china",))
    base = _baseline14()
    res = be.bl_allocate(Sigma, base, ranking={"b3_global_tech": ("strong_OW", 0.9)},
                         pinned=["b4_china"], delta=2.5, growth_keys=set(GROWTH_KEYS))
    w = res["weights"]
    assert abs(w.sum() - 1.0) < 1e-6
    assert w["b4_china"] == pytest.approx(base["b4_china"], abs=1e-9)   # pinned fixed
    assert res["meta"]["b4_china"]["status"] == "baseline_pinned"

def test_empty_sigma_full_fallback():
    base = _baseline14()
    res = be.bl_allocate(pd.DataFrame(), base, ranking={}, pinned=list(GAPS_BUCKET_KEYS),
                         delta=2.5, growth_keys=set(GROWTH_KEYS))
    assert np.allclose(res["weights"].reindex(base.index).values, base.values, atol=1e-9)
    assert res["meta"]["__global__"]["status"] == "full_fallback"
