"""Stage 3 trader Step A — quadrant 앵커 (baseline + hard band + 동적 밴드 + 투영).

앵커 key = macro_report.regime.quadrant (4개, 결정론). LLM 은 baseline 대비 tilt 만
하고, 코드가 confidence 로 좁힌 밴드 안으로 박스제약 투영.

baseline 수치는 v1 시드 (레짐→자산군 로직 + mandate ≤70% 지향 + 옛 BL 부호).
risk≤70% 하드 보장은 Stage 5 validator 담당 — 본 모듈은 강제하지 않는다.
"""
from __future__ import annotations

from typing import Literal

from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS, DEFENSIVE_KEYS

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


LAT_BASE: float = 1.0   # 예약된 튜닝 다이얼 (L2 변동성 검증 시 조정). 현재 1.0 → no-op.


def effective_band(
    baseline: float, hard_min: float, hard_max: float,
    confidence: float,
) -> tuple[float, float]:
    """동적 latitude — confidence 낮으면 baseline 에 수렴.

    half ∈ [0.4, 1.0]. half==1 (confidence=1) 이면 hard band 전체 사용.
    baseline ∈ [eff_min, eff_max] ⊆ [hard_min, hard_max] 항상 성립.
    """
    half = LAT_BASE * (0.4 + 0.6 * max(0.0, min(1.0, confidence)))
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


# === 매크로 신호 → bucket delta (v1 시드, 튜닝 대상). net≈0, |delta| 작게. ===
# risk_tilt 5단 → 성장버킷 합 조정폭 (regime baseline 대비 위험자산 ±).
RISK_TILT_AMOUNT: dict[str, float] = {
    "strong_offensive": 0.05, "offensive": 0.025, "neutral": 0.0,
    "defensive": -0.025, "strong_defensive": -0.05,
}

CREDIT_MODIFIER: dict[str, dict[str, float]] = {
    "tight":  {"b9_risk_credit": -0.02, "a3_us_rates": 0.02},
    "crisis": {"b9_risk_credit": -0.04, "a3_us_rates": 0.02, "a1_cash": 0.02},
    # easy / neutral → no-op
}

FX_MODIFIER: dict[str, dict[str, float]] = {
    "usd_risk_off": {"a4_safe_fx": 0.03, "b1_kr_equity": -0.03},
    # krw_weak / krw_strong / neutral → 비중 no-op (종목 환헤지로만 작동)
}


def _risk_tilt_delta(baseline: dict[str, float], risk_tilt: str) -> dict[str, float]:
    """regime baseline 대비 위험자산 ±. 성장버킷 합을 amt(baseline 비례) → 방어버킷 비례 역방향."""
    amt = RISK_TILT_AMOUNT.get(risk_tilt, 0.0)
    if amt == 0.0:
        return {}
    gsum = sum(baseline[b] for b in GROWTH_KEYS) or 1.0
    dsum = sum(baseline[b] for b in DEFENSIVE_KEYS) or 1.0
    delta: dict[str, float] = {}
    for b in GROWTH_KEYS:
        delta[b] = amt * baseline[b] / gsum
    for b in DEFENSIVE_KEYS:
        delta[b] = -amt * baseline[b] / dsum
    return delta


def apply_macro_modifiers(
    baseline: dict[str, float], risk_tilt: str, credit_regime: str, fx_regime: str,
    hard_min: dict[str, float], hard_max: dict[str, float],
) -> dict[str, float]:
    """risk_tilt(정성) + credit·fx(정량) 의 bucket delta 를 합산해 hard band 로 투영.

    전부 neutral/normal → baseline 그대로. project_to_band 재사용으로 sum=1·hard band 보장,
    불가 시 baseline fallback.
    """
    delta: dict[str, float] = {}

    def _add(src: dict[str, float] | None) -> None:
        if src:
            for b, d in src.items():
                delta[b] = delta.get(b, 0.0) + d

    _add(_risk_tilt_delta(baseline, risk_tilt))
    _add(CREDIT_MODIFIER.get(credit_regime))
    _add(FX_MODIFIER.get(fx_regime))
    if not delta:
        return dict(baseline)
    return project_to_band(baseline, delta, hard_min, hard_max)
