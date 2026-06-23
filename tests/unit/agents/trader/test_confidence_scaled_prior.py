import pandas as pd
import pytest
from tradingagents.agents.trader import trader_allocator as ta
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS

_RISK = {"a5_gold_infl"} | set(GROWTH_KEYS)


def test_w_neutral_risk_sum_half_and_sums_to_one():
    risk = sum(ta.W_NEUTRAL[b] for b in ta.W_NEUTRAL if b in _RISK)
    assert risk == pytest.approx(0.50, abs=1e-9)         # 위험 0.50 재정규화
    assert sum(ta.W_NEUTRAL.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(w >= 0 for w in ta.W_NEUTRAL.values())


def test_interpolate_prior_endpoints():
    base = QUADRANT_BASELINE["growth_disinflation"]
    p0 = ta._interpolate_prior("growth_disinflation", 0.0)
    p1 = ta._interpolate_prior("growth_disinflation", 1.0)
    assert all(p0[b] == pytest.approx(ta.W_NEUTRAL[b]) for b in p0)   # c=0 → 중립
    assert all(p1[b] == pytest.approx(base[b]) for b in p1)           # c=1 → baseline
    assert sum(p0.values()) == pytest.approx(1.0) and sum(p1.values()) == pytest.approx(1.0)


def test_risk_monotonic_recession_does_not_overshoot():
    def risk_of(p): return sum(p[b] for b in p if b in _RISK)
    base_risk = risk_of(QUADRANT_BASELINE["recession_disinflation"])
    r_c0 = risk_of(ta._interpolate_prior("recession_disinflation", 0.0))
    r_c1 = risk_of(ta._interpolate_prior("recession_disinflation", 1.0))
    assert r_c1 == pytest.approx(base_risk, abs=1e-9)
    assert r_c0 == pytest.approx(0.50, abs=1e-9)          # 중립으로, 0.60 아님
    assert base_risk <= r_c0 <= 0.50 + 1e-9               # 0.40→0.50 (의도적), 과상승 없음
