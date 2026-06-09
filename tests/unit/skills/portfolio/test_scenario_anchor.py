import pytest
from tradingagents.skills.portfolio.gaps_buckets import (
    GAPS_BUCKET_KEYS, GROWTH_KEYS, DEFENSIVE_KEYS,
)
from tradingagents.skills.portfolio.scenario_anchor import (
    QUADRANT_BASELINE, hard_band,
)
from tradingagents.skills.portfolio.scenario_anchor import effective_band
from tradingagents.skills.portfolio.scenario_anchor import project_to_band
from tradingagents.schemas.portfolio import BucketTilt

QUADRANTS = ("growth_inflation", "growth_disinflation",
             "recession_inflation", "recession_disinflation")
# a5_gold_infl은 camp상 방어지만 금 ETF는 per-ETF 위험 플래그라 risk proxy에 포함.
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


def test_effective_band_brackets_baseline():
    # confidence=0.5 → half=0.7 (<1) → 밴드가 hard band 내부로 좁혀짐
    lo, hi = effective_band(0.10, 0.04, 0.20, confidence=0.5)
    assert 0.04 < lo < 0.10 < hi < 0.20          # 엄격히 내부
    assert lo == pytest.approx(0.10 - (0.10 - 0.04) * 0.7)
    assert hi == pytest.approx(0.10 + (0.20 - 0.10) * 0.7)


def test_effective_band_confidence_floor():
    # confidence=0.0 → half=0.4 (가장 좁음, confidence floor)
    lo, hi = effective_band(0.10, 0.04, 0.20, confidence=0.0)
    assert lo == pytest.approx(0.10 - (0.10 - 0.04) * 0.4)
    assert hi == pytest.approx(0.10 + (0.20 - 0.10) * 0.4)


def test_low_confidence_narrows_toward_baseline():
    base, hmin, hmax = 0.10, 0.04, 0.20
    lo_lo, hi_lo = effective_band(base, hmin, hmax, confidence=0.05)
    lo_hi, hi_hi = effective_band(base, hmin, hmax, confidence=1.0)
    # 저신뢰 밴드가 baseline 에 더 가깝다
    assert (base - lo_lo) < (base - lo_hi)
    assert (hi_lo - base) < (hi_hi - base)


def test_high_confidence_reaches_hard_band():
    lo, hi = effective_band(0.10, 0.04, 0.20, confidence=1.0)
    assert lo == pytest.approx(0.04)
    assert hi == pytest.approx(0.20)


_B = {"x": 0.30, "y": 0.30, "z": 0.40}            # baseline (합 1.0)
_LO = {"x": 0.10, "y": 0.10, "z": 0.20}
_HI = {"x": 0.50, "y": 0.50, "z": 0.60}


def test_zero_tilt_returns_baseline():
    out = project_to_band(_B, {}, _LO, _HI)
    assert out == pytest.approx(_B)


def test_result_always_sums_to_one():
    out = project_to_band(_B, {"x": 0.15, "y": -0.05, "z": -0.05}, _LO, _HI)
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(_LO[k] - 1e-9 <= out[k] <= _HI[k] + 1e-9 for k in _B)


def test_out_of_band_tilt_is_clamped():
    # x 를 밴드(0.50) 초과로 밀어도 ≤ hard_max, 잔차는 재분배
    out = project_to_band(_B, {"x": 0.40}, _LO, _HI)
    assert out["x"] <= 0.50 + 1e-9
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)


def test_net_positive_tilt_redistributed_down():
    # 모든 tilt 가 +라 합>1 → 여유 있는 버킷에서 끌어내려 sum=1 유지
    out = project_to_band(_B, {"x": 0.10, "y": 0.10, "z": 0.10}, _LO, _HI)
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)


def test_infeasible_numeric_falls_back_to_baseline():
    # eff_min 합이 1 초과(모순) → baseline 반환
    bad_lo = {"x": 0.40, "y": 0.40, "z": 0.40}
    out = project_to_band(_B, {"x": 0.05}, bad_lo, _HI)
    assert out == pytest.approx(_B)


def test_redistribution_is_proportional_to_headroom():
    # x 를 +0.40 밀면 초과분이 y,z 로 재분배. y,z 는 동일 headroom 이므로 동일하게 줄어듦.
    # _B: y=0.30, z=0.40 / _LO: y=0.10, z=0.20 → headroom-down y:0.20, z:0.20 (동일)
    # 동일 headroom → 절대 감소량 동일 (최종값은 다름: y≠z)
    out = project_to_band(_B, {"x": 0.40}, _LO, _HI)
    assert (_B["y"] - out["y"]) == pytest.approx(_B["z"] - out["z"])  # 동일 headroom → 동일 절대 감소
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)


def test_bucket_tilt_defaults_empty():
    bt = BucketTilt()
    assert bt.tilts == {}
    assert bt.rationale == ""


def test_bucket_tilt_accepts_sparse_deltas():
    bt = BucketTilt(tilts={"b3_global_tech": 0.04, "b5_other_intl": -0.04})
    assert bt.tilts["b3_global_tech"] == pytest.approx(0.04)


from tradingagents.skills.portfolio.scenario_anchor import apply_macro_modifiers
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS, DEFENSIVE_KEYS

def _hb(baseline):
    from tradingagents.skills.portfolio.scenario_anchor import hard_band
    lo = {b: hard_band("growth_disinflation", b, baseline[b])[0] for b in baseline}
    hi = {b: hard_band("growth_disinflation", b, baseline[b])[1] for b in baseline}
    return lo, hi

def test_macro_modifiers_neutral_is_baseline():
    base = QUADRANT_BASELINE["growth_disinflation"]
    lo, hi = _hb(base)
    out = apply_macro_modifiers(base, "neutral", "neutral", "neutral", lo, hi)
    assert out == pytest.approx(base)

def test_macro_modifiers_defensive_cuts_growth():
    base = QUADRANT_BASELINE["growth_disinflation"]
    lo, hi = _hb(base)
    out = apply_macro_modifiers(base, "defensive", "neutral", "neutral", lo, hi)
    g0 = sum(base[b] for b in GROWTH_KEYS)
    g1 = sum(out[b] for b in GROWTH_KEYS)
    assert g1 < g0
    assert abs(sum(out.values()) - 1.0) < 1e-9

def test_macro_modifiers_credit_crisis_cuts_hy():
    base = QUADRANT_BASELINE["growth_disinflation"]
    lo, hi = _hb(base)
    out = apply_macro_modifiers(base, "neutral", "crisis", "neutral", lo, hi)
    assert out["b9_risk_credit"] < base["b9_risk_credit"]
    assert out["a3_us_rates"] > base["a3_us_rates"]

def test_macro_modifiers_fx_usd_riskoff_lifts_safe_fx():
    base = QUADRANT_BASELINE["growth_disinflation"]
    lo, hi = _hb(base)
    out = apply_macro_modifiers(base, "neutral", "neutral", "usd_risk_off", lo, hi)
    assert out["a4_safe_fx"] > base["a4_safe_fx"]
    assert out["b1_kr_equity"] < base["b1_kr_equity"]

def test_macro_modifiers_strong_defensive_cuts_more():
    base = QUADRANT_BASELINE["growth_disinflation"]
    lo, hi = _hb(base)
    mild = apply_macro_modifiers(base, "defensive", "neutral", "neutral", lo, hi)
    strong = apply_macro_modifiers(base, "strong_defensive", "neutral", "neutral", lo, hi)
    assert sum(strong[b] for b in GROWTH_KEYS) < sum(mild[b] for b in GROWTH_KEYS)
