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
from tradingagents.skills.portfolio.scenario_anchor import (
    SCENARIO_MODIFIER, apply_scenario_modifier,
)
from tradingagents.schemas.research import _VALID_SCENARIOS

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
    # confidence=0.5, conviction="medium" → half=0.7 (<1) → 밴드가 hard band 내부로 좁혀짐
    lo, hi = effective_band(0.10, 0.04, 0.20, confidence=0.5, conviction="medium")
    assert 0.04 < lo < 0.10 < hi < 0.20          # 엄격히 내부
    assert lo == pytest.approx(0.10 - (0.10 - 0.04) * 0.7)
    assert hi == pytest.approx(0.10 + (0.20 - 0.10) * 0.7)


def test_effective_band_confidence_floor():
    # confidence=0.0, conviction="low" → half=0.4*0.6=0.24 (가장 좁음)
    lo, hi = effective_band(0.10, 0.04, 0.20, confidence=0.0, conviction="low")
    assert lo == pytest.approx(0.10 - (0.10 - 0.04) * 0.24)
    assert hi == pytest.approx(0.10 + (0.20 - 0.10) * 0.24)


def test_low_confidence_low_conviction_narrows_toward_baseline():
    base, hmin, hmax = 0.10, 0.04, 0.20
    lo_lo, hi_lo = effective_band(base, hmin, hmax, confidence=0.05, conviction="low")
    lo_hi, hi_hi = effective_band(base, hmin, hmax, confidence=1.0, conviction="high")
    # 저신뢰·저확신 밴드가 baseline 에 더 가깝다
    assert (base - lo_lo) < (base - lo_hi)
    assert (hi_lo - base) < (hi_hi - base)


def test_high_confidence_high_conviction_reaches_hard_band():
    lo, hi = effective_band(0.10, 0.04, 0.20, confidence=1.0, conviction="high")
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


def test_modifier_keys_are_valid_orthogonal_scenarios():
    assert "neutral" not in SCENARIO_MODIFIER
    assert set(SCENARIO_MODIFIER) <= (_VALID_SCENARIOS - {"neutral"})
    for deltas in SCENARIO_MODIFIER.values():
        assert all(b in GAPS_BUCKET_KEYS for b in deltas)
        assert all(abs(d) <= 0.05 + 1e-9 for d in deltas.values())


def test_neutral_scenario_is_noop():
    base = dict(QUADRANT_BASELINE["growth_disinflation"])
    hmin = {b: hard_band("growth_disinflation", b, base[b])[0] for b in base}
    hmax = {b: hard_band("growth_disinflation", b, base[b])[1] for b in base}
    assert apply_scenario_modifier(base, "neutral", hmin, hmax) == pytest.approx(base)
    assert apply_scenario_modifier(base, "definitely_unknown", hmin, hmax) == pytest.approx(base)


def test_kr_stress_shifts_kr_down_global_up_within_band_sum1():
    q = "growth_disinflation"
    base = dict(QUADRANT_BASELINE[q])
    hmin = {b: hard_band(q, b, base[b])[0] for b in base}
    hmax = {b: hard_band(q, b, base[b])[1] for b in base}
    out = apply_scenario_modifier(base, "kr_stress", hmin, hmax)
    assert out["b1_kr_equity"] < base["b1_kr_equity"]
    assert out["b2_dm_core"] > base["b2_dm_core"]
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(hmin[b] - 1e-9 <= out[b] <= hmax[b] + 1e-9 for b in out)


def test_modifier_clamped_by_quadrant_hard_band():
    q = "recession_disinflation"
    base = dict(QUADRANT_BASELINE[q])
    hmin = {b: hard_band(q, b, base[b])[0] for b in base}
    hmax = {b: hard_band(q, b, base[b])[1] for b in base}
    out = apply_scenario_modifier(base, "ai_concentration", hmin, hmax)
    assert out["b3_global_tech"] <= hmax["b3_global_tech"] + 1e-9
