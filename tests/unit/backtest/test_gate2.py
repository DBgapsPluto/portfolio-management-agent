import numpy as np, pandas as pd
from scripts.backtest_bl_gate2 import gate2_checks, gate2_defensive_false_trip, gate2_realized_risk
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS, GROWTH_KEYS
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE

def _sigma():
    keep = list(GAPS_BUCKET_KEYS); rng = np.random.default_rng(7)
    vols = rng.uniform(0.05,0.30,14); C = rng.uniform(0.1,0.6,(14,14)); C=(C+C.T)/2; np.fill_diagonal(C,1.0)
    S=np.outer(vols,vols)*C; S=S@S.T/14+np.eye(14)*1e-4
    return pd.DataFrame(S, index=keep, columns=keep)
_MANDATE = {"a5_gold_infl"} | set(GROWTH_KEYS)

def test_gate2_passes_on_sane_engine():
    Sigma = _sigma(); base = pd.Series(QUADRANT_BASELINE["growth_disinflation"])
    rep = gate2_checks(Sigma, base, growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE)
    assert rep["d_no_view_recovers"] and rep["a_direction"] and rep["b_not_inert"] and rep["c_no_blowup"]

def test_gate2_defensive_no_false_trip():
    Sigma = _sigma(); base = pd.Series(QUADRANT_BASELINE["recession_disinflation"])
    rep = gate2_defensive_false_trip(Sigma, base, growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE)
    assert rep["e_no_false_trip"]

def test_gate2_realized_risk_within_cap():
    Sigma = _sigma(); base = pd.Series(QUADRANT_BASELINE["growth_disinflation"])
    rep = gate2_realized_risk(Sigma, base, growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE)
    assert rep["f_risk_within_cap"]
