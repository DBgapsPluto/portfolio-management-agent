import pytest
from tradingagents.skills.portfolio.gaps_buckets import (
    GAPS_BUCKET_KEYS, GROWTH_KEYS, DEFENSIVE_KEYS,
)
from tradingagents.skills.portfolio.scenario_anchor import (
    QUADRANT_BASELINE, hard_band,
)

QUADRANTS = ("growth_inflation", "growth_disinflation",
             "recession_inflation", "recession_disinflation")
RISK_PROXY = ("a5_gold_infl",) + GROWTH_KEYS   # a5 + 모든 성장버킷


@pytest.mark.parametrize("q", QUADRANTS)
def test_baseline_covers_all_14_buckets(q):
    assert set(QUADRANT_BASELINE[q]) == set(GAPS_BUCKET_KEYS)


@pytest.mark.parametrize("q", QUADRANTS)
def test_baseline_sums_to_one(q):
    assert sum(QUADRANT_BASELINE[q].values()) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("q", QUADRANTS)
def test_baseline_risk_proxy_at_most_70pct(q):
    risk = sum(QUADRANT_BASELINE[q][b] for b in RISK_PROXY)
    assert risk <= 0.70 + 1e-9


@pytest.mark.parametrize("q", QUADRANTS)
def test_hard_band_brackets_baseline_and_feasible(q):
    base = QUADRANT_BASELINE[q]
    lo = hi = 0.0
    for b, w in base.items():
        hmin, hmax = hard_band(q, b, w)
        assert 0.0 <= hmin <= w <= hmax
        lo += hmin
        hi += hmax
    assert lo <= 1.0 <= hi   # 투영 가능성


def test_l1_growth_tilts_to_growth_camp():
    for q in ("growth_inflation", "growth_disinflation"):
        base = QUADRANT_BASELINE[q]
        assert sum(base[b] for b in GROWTH_KEYS) > sum(base[b] for b in DEFENSIVE_KEYS)


def test_l1_recession_tilts_to_defensive_camp():
    for q in ("recession_inflation", "recession_disinflation"):
        base = QUADRANT_BASELINE[q]
        assert sum(base[b] for b in DEFENSIVE_KEYS) > sum(base[b] for b in GROWTH_KEYS)


def test_l1_inflation_lifts_gold_and_commodity():
    assert (QUADRANT_BASELINE["recession_inflation"]["a5_gold_infl"]
            > QUADRANT_BASELINE["growth_disinflation"]["a5_gold_infl"])
    assert (QUADRANT_BASELINE["growth_inflation"]["b8_cyclical_commodity"]
            > QUADRANT_BASELINE["growth_disinflation"]["b8_cyclical_commodity"])


def test_l1_broad_recession_has_max_duration():
    a3 = {q: QUADRANT_BASELINE[q]["a3_us_rates"] for q in QUADRANTS}
    assert a3["recession_disinflation"] == max(a3.values())
