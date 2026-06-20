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


from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE


def _real_sigma_14(seed=5):
    keys = list(QUADRANT_BASELINE["growth_disinflation"].keys())
    rng = np.random.default_rng(seed)
    vols = rng.uniform(0.05, 0.30, len(keys)); C = rng.uniform(0.1, 0.6, (len(keys), len(keys)))
    C = (C + C.T) / 2; np.fill_diagonal(C, 1.0); S = np.outer(vols, vols) * C
    S = S @ S.T / len(keys) + np.eye(len(keys)) * 1e-4
    return pd.DataFrame(S, index=keys, columns=keys)


_MANDATE = {"a5_gold_infl"} | set(GROWTH_KEYS)


@pytest.mark.parametrize("quadrant", list(QUADRANT_BASELINE.keys()))
@pytest.mark.parametrize("pin", ["a3_us_rates", "a1_cash", "a2_kr_rates"])
def test_no_view_recovery_with_defensive_pin(quadrant, pin):
    base = pd.Series(QUADRANT_BASELINE[quadrant])
    Sigma = _real_sigma_14().drop(index=[pin], columns=[pin])   # pinned bucket absent from Σ
    res = be.bl_allocate(Sigma, base, ranking={}, pinned=[pin], delta=2.5,
                         growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE)
    w = res["weights"]
    assert abs(w.sum() - 1.0) < 1e-6
    assert w[pin] == pytest.approx(base[pin], abs=1e-9)           # pin exact
    # no-view ⇒ non-pinned buckets recover their baseline (renormalized to budget, then back)
    assert np.abs(w - base).sum() < 1e-6, f"{quadrant} pin={pin} L1={np.abs(w-base).sum()}"
