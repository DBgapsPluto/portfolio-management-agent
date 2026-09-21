import numpy as np
import pandas as pd
from tradingagents.skills.portfolio import bl_engine as be
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS, GROWTH_KEYS
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE

def _real_sigma(seed=3):
    keep = list(GAPS_BUCKET_KEYS)
    rng = np.random.default_rng(seed)
    vols = rng.uniform(0.05, 0.30, len(keep))
    C = rng.uniform(0.1, 0.6, (len(keep), len(keep))); C = (C + C.T) / 2; np.fill_diagonal(C, 1.0)
    S = np.outer(vols, vols) * C
    S = S @ S.T / len(keep) + np.eye(len(keep)) * 1e-4
    return pd.DataFrame(S, index=keep, columns=keep)

_MANDATE = {"a5_gold_infl"} | set(GROWTH_KEYS)

def test_full_conviction_single_view_bounded():
    Sigma = _real_sigma(); base = pd.Series(QUADRANT_BASELINE["growth_disinflation"])
    res = be.bl_allocate(Sigma, base, ranking={"b3_global_tech": ("strong_OW", 0.95)},
                         delta=2.5, growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE,
                         growth_cap=0.30, defensive_cap=0.50)
    w = res["weights"]
    assert w.max() <= 0.50 + 1e-9
    assert np.abs(w - base).sum() <= 0.40
    defensive = [b for b in base.index if b not in GROWTH_KEYS]
    assert w[defensive].sum() >= base[defensive].sum() * 0.5

def test_growth_view_respects_growth_ceiling():
    Sigma = _real_sigma(); base = pd.Series(QUADRANT_BASELINE["growth_disinflation"])
    res = be.bl_allocate(Sigma, base, ranking={"b3_global_tech": ("strong_OW", 0.95)},
                         delta=2.5, growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE,
                         growth_cap=0.30, defensive_cap=0.50)
    assert res["weights"]["b3_global_tech"] <= 0.30 + 1e-9

def test_sigma_vol_perturbation_stays_bounded():
    base = pd.Series(QUADRANT_BASELINE["growth_disinflation"])
    for scale in (0.8, 1.0, 1.2):
        Sigma = _real_sigma() * scale
        res = be.bl_allocate(Sigma, base, ranking={"b3_global_tech": ("strong_OW", 0.95)},
                             delta=2.5, growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE,
                             growth_cap=0.30, defensive_cap=0.50)
        assert res["weights"].max() <= 0.50 + 1e-9

def test_no_single_growth_bucket_exceeds_ceiling_any_seed():
    base = pd.Series(QUADRANT_BASELINE["growth_disinflation"])
    for seed in range(6):
        Sigma = _real_sigma(seed)
        res = be.bl_allocate(Sigma, base, ranking={"b3_global_tech": ("strong_OW", 0.95)},
                             delta=2.5, growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE,
                             growth_cap=0.30, defensive_cap=0.50)
        w = res["weights"]
        for g in GROWTH_KEYS:
            assert w[g] <= 0.30 + 1e-9
