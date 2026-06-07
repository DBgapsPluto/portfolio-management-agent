"""Stage 3 trader Step A — quadrant 앵커 (baseline + hard band + 동적 밴드 + 투영).

앵커 key = macro_report.regime.quadrant (4개, 결정론). LLM 은 baseline 대비 tilt 만
하고, 코드가 confidence·conviction 로 좁힌 밴드 안으로 박스제약 투영.

baseline 수치는 v1 시드 (레짐→자산군 로직 + mandate ≤70% 지향 + 옛 BL 부호).
risk≤70% 하드 보장은 Stage 5 validator 담당 — 본 모듈은 강제하지 않는다.
"""
from __future__ import annotations

from typing import Literal

from tradingagents.schemas.research import ConvictionLevel
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS

RegimeQuadrant = Literal[
    "growth_inflation", "growth_disinflation",
    "recession_inflation", "recession_disinflation",
]

# quadrant → {bucket_key: baseline}. 각 quadrant 합 == 1.0 (단위테스트 강제).
QUADRANT_BASELINE: dict[RegimeQuadrant, dict[str, float]] = {
    "growth_disinflation": {
        "a1_cash": 0.08, "a2_kr_rates": 0.08, "a3_us_rates": 0.12,
        "a4_safe_fx": 0.04, "a5_gold_infl": 0.05,
        "b1_kr_equity": 0.11, "b2_dm_core": 0.16, "b3_global_tech": 0.14,
        "b4_china": 0.03, "b5_other_intl": 0.05, "b6_defensive_equity": 0.05,
        "b7_reits": 0.04, "b8_cyclical_commodity": 0.03, "b9_risk_credit": 0.02,
    },
    # v2 수정(리플레이션): 장기 듀레이션 테크는 인플레 국면서 코어 대비 부진 → b3 0.11→0.08, b2 0.09→0.12.
    "growth_inflation": {
        "a1_cash": 0.09, "a2_kr_rates": 0.07, "a3_us_rates": 0.08,
        "a4_safe_fx": 0.07, "a5_gold_infl": 0.12,
        "b1_kr_equity": 0.10, "b2_dm_core": 0.12, "b3_global_tech": 0.08,
        "b4_china": 0.03, "b5_other_intl": 0.04, "b6_defensive_equity": 0.05,
        "b7_reits": 0.03, "b8_cyclical_commodity": 0.09, "b9_risk_credit": 0.03,
    },
    "recession_disinflation": {
        "a1_cash": 0.16, "a2_kr_rates": 0.10, "a3_us_rates": 0.24,
        "a4_safe_fx": 0.10, "a5_gold_infl": 0.10,
        "b1_kr_equity": 0.04, "b2_dm_core": 0.06, "b3_global_tech": 0.04,
        "b4_china": 0.01, "b5_other_intl": 0.02, "b6_defensive_equity": 0.07,
        "b7_reits": 0.02, "b8_cyclical_commodity": 0.02, "b9_risk_credit": 0.02,
    },
    # v2 수정(스태그플레이션): 현금은 인플레로 잠식 → a1 0.15→0.11, 금/원자재로 이전(a5 0.15→0.17, b8 0.11→0.13).
    "recession_inflation": {
        "a1_cash": 0.11, "a2_kr_rates": 0.07, "a3_us_rates": 0.10,
        "a4_safe_fx": 0.08, "a5_gold_infl": 0.17,
        "b1_kr_equity": 0.05, "b2_dm_core": 0.06, "b3_global_tech": 0.04,
        "b4_china": 0.02, "b5_other_intl": 0.03, "b6_defensive_equity": 0.08,
        "b7_reits": 0.03, "b8_cyclical_commodity": 0.13, "b9_risk_credit": 0.03,
    },
}

# hard band: baseline 에서의 절대 가감. 침체 quadrant 의 성장버킷은 상단 제한(risk-on 금지).
_BAND_DOWN: float = 0.06
_BAND_UP: float = 0.10
_BAND_UP_RECESSION_GROWTH: float = 0.05


def hard_band(quadrant: RegimeQuadrant, bucket: str, baseline: float) -> tuple[float, float]:
    """버킷의 절대 외곽 한계 [hard_min, hard_max]. hard_min ≤ baseline ≤ hard_max."""
    up = _BAND_UP
    if quadrant.startswith("recession") and bucket in GROWTH_KEYS:
        up = _BAND_UP_RECESSION_GROWTH
    hmin = round(max(0.0, baseline - _BAND_DOWN), 4)
    hmax = round(baseline + up, 4)
    return hmin, hmax


CONV_FACTOR: dict[str, float] = {"high": 1.4, "medium": 1.0, "low": 0.6}
LAT_BASE: float = 1.0   # 예약된 튜닝 다이얼 (L2 변동성 검증 시 조정). 현재 1.0 → no-op.


def effective_band(
    baseline: float, hard_min: float, hard_max: float,
    confidence: float, conviction: ConvictionLevel,
) -> tuple[float, float]:
    """동적 latitude — confidence·conviction 낮으면 baseline 에 수렴.

    half ∈ [~0.24, 1.4]. half≥1 이면 hard band 전체 사용.
    baseline ∈ [eff_min, eff_max] ⊆ [hard_min, hard_max] 항상 성립.
    """
    half = (
        LAT_BASE
        * (0.4 + 0.6 * max(0.0, min(1.0, confidence)))
        * CONV_FACTOR.get(conviction, 1.0)
    )
    eff_min = max(hard_min, baseline - (baseline - hard_min) * half)
    eff_max = min(hard_max, baseline + (hard_max - baseline) * half)
    return eff_min, eff_max


_EPS: float = 1e-9
_FEASIBILITY_TOL: float = 1e-6  # _EPS 보다 의도적으로 느슨 — float 누적 오차를 허용.
_MAX_ITERS: int = 50   # 넉넉한 안전망. feasible 밴드는 ~1-2 iter 수렴; 미수렴은 아래 guard가 baseline fallback.


def project_to_band(
    baseline: dict[str, float],
    tilts: dict[str, float],
    eff_min: dict[str, float],
    eff_max: dict[str, float],
) -> dict[str, float]:
    """baseline + tilt 를 {sum=1, eff_min≤w≤eff_max} 로 투영. 불가 시 baseline."""
    keys = list(baseline)
    w = {b: min(max(baseline[b] + tilts.get(b, 0.0), eff_min[b]), eff_max[b])
         for b in keys}
    for _ in range(_MAX_ITERS):
        residual = 1.0 - sum(w.values())
        if abs(residual) < _EPS:
            break
        if residual > 0:
            head = {b: eff_max[b] - w[b] for b in keys}
        else:
            head = {b: w[b] - eff_min[b] for b in keys}
        cap = sum(v for v in head.values() if v > 0)
        if cap < _EPS:
            break
        for b in keys:
            if head[b] > 0:
                nw = w[b] + residual * head[b] / cap
                w[b] = min(max(nw, eff_min[b]), eff_max[b])
    if abs(1.0 - sum(w.values())) > _FEASIBILITY_TOL:  # 수렴 실패 → baseline fallback
        return dict(baseline)
    return w


# 직교 시나리오 → {bucket: delta}. 작고 net≈0, |delta| ≤ 0.05 (v1 시드, 튜닝 대상).
# keys ⊆ ScenarioLabel \ {neutral} (test_scenario_anchor 가 cross-check).
SCENARIO_MODIFIER: dict[str, dict[str, float]] = {
    "kr_boom":          {"b1_kr_equity": 0.05, "b5_other_intl": -0.03, "b2_dm_core": -0.02},
    "kr_stress":        {"b1_kr_equity": -0.05, "b2_dm_core": 0.03, "a1_cash": 0.02},
    "global_credit":    {"b9_risk_credit": -0.04, "a3_us_rates": 0.04},
    "ai_concentration": {"b3_global_tech": 0.05, "b6_defensive_equity": -0.03, "b5_other_intl": -0.02},
    # "neutral" 없음 → no-op
}


def apply_scenario_modifier(
    baseline: dict[str, float], scenario: str,
    hard_min: dict[str, float], hard_max: dict[str, float],
) -> dict[str, float]:
    """quadrant baseline 에 scenario modifier 를 더해 center 이동, quadrant hard band 로 투영.

    neutral / 미정의 scenario → baseline 그대로. project_to_band 재사용 → sum=1·hard band 내
    보장, 불가 시 baseline fallback. modifier 가 hard band 를 못 벗어나는 게 구조적 모순 guard.
    """
    delta = SCENARIO_MODIFIER.get(scenario)
    if not delta:
        return dict(baseline)
    return project_to_band(baseline, delta, hard_min, hard_max)
