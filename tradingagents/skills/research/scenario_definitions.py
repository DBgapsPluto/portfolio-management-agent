"""7개 직교 시나리오 정의 + mandate-safe SCENARIO_BUCKETS.

직교 차원:
  1. 글로벌 매크로 사이클 (growth/inflation vs recession/disinflation)
  2. 시장 breadth (broad vs narrow)
  3. 신용/금융 안정성 (stable vs crisis)
  4. KR ↔ Global decoupling (follow vs KR-specific)

각 시나리오가 최소 1개 직교 차원에서 다른 시나리오와 갈림.

SCENARIO_BUCKETS Invariant:
  모든 시나리오의 위험자산(kr_eq+gl_eq+fx_comm) ≤ 0.70
  → 임의 확률 가중 평균도 ≤ 0.70 보장 (선형 invariant, mandate §2.2 안전).
"""
from tradingagents.schemas.research import ScenarioName


# 시나리오 텍스트 — estimator prompt에 그대로 주입
SCENARIO_DEFINITIONS: dict[ScenarioName, str] = {
    "goldilocks": (
        "Goldilocks (broad growth + disinflation). "
        "Stage 1 신호: macro_quant regime=growth_disinflation, "
        "market_risk score<5, technical universe_breadth=broad_risk_on. "
        "참고 사례: 1995, 2017, 2024 초"
    ),
    "ai_concentration": (
        "AI/Tech Concentration Rally — growth+disinflation이지만 mega-cap 편중. "
        "Stage 1 신호: technical sector_rotation momentum_spread>+15%, "
        "universe_breadth=narrow, breadth_us<0.5, market_risk pca concentrated. "
        "참고: 2023-2024 mega-cap rally"
    ),
    "stagflation": (
        "Stagflation — 인플레 끈끈 + 성장 둔화. "
        "Stage 1 신호: macro_quant regime=growth_inflation or recession_inflation, "
        "TIPS 10y>2%, real_yields=very_tight, news release_surprise bias=hawkish. "
        "참고: 1973-80, 2022 peak inflation"
    ),
    "broad_recession": (
        "Broad Recession (recession + disinflation, credit-stable). "
        "Stage 1 신호: regime=recession_disinflation, Sahm rule trigger, "
        "yield_curve inverted long duration, breadth broad-down. "
        "Credit 위기는 아직 (HY OAS<600bp). 참고: 1990-91, 2001"
    ),
    "global_credit": (
        "Global Credit Event — systemic credit 위기. "
        "Stage 1 신호: market_risk systemic_score≥8, funding_stress=stress, "
        "credit_quality=stress, HY OAS>1000bp, VIX backwardation, "
        "equity_bond_corr extreme_positive. "
        "참고: 2008 Q4 Lehman, 2020 Q1 COVID, 1998 LTCM"
    ),
    "kr_boom": (
        "KR Decoupling Boom — 글로벌과 무관 KR 자체 cycle 호황. "
        "Stage 1 신호: macro_quant kr_export accelerating=True (3mo>6mo>yoy), "
        "kr_leading expanding, technical kr_market_tier=small_cap_risk_on, "
        "foreign_flow KR 순매수. 참고: 2017 반도체 super-cycle, 2020 Q4"
    ),
    "kr_stress": (
        "KR Decoupling Stress — 글로벌 OK + KR-specific 위기. "
        "Stage 1 신호: market_risk kr_yield_curve inverted, "
        "kr_corp_spread=stress (레고랜드형), kr_margin_debt deleveraging, "
        "kr_market_tier=large_cap_risk_off, kr_export 둔화. "
        "참고: 2022 레고랜드, 2023 부동산 PF 위기"
    ),
}


# Mandate-safe SCENARIO_BUCKETS. 모든 시나리오 위험자산 ≤ 0.70.
# Weights는 §대회 §2.2 (위험자산 ≤ 0.70) + 실무적 5-bucket 분산 고려해서 설계.
SCENARIO_BUCKETS: dict[ScenarioName, dict[str, float]] = {
    "goldilocks":        {"kr_equity": 0.25, "global_equity": 0.30, "fx_commodity": 0.10, "bond": 0.25, "cash_mmf": 0.10},
    "ai_concentration":  {"kr_equity": 0.15, "global_equity": 0.45, "fx_commodity": 0.10, "bond": 0.25, "cash_mmf": 0.05},
    "stagflation":       {"kr_equity": 0.10, "global_equity": 0.15, "fx_commodity": 0.25, "bond": 0.40, "cash_mmf": 0.10},
    "broad_recession":   {"kr_equity": 0.10, "global_equity": 0.10, "fx_commodity": 0.10, "bond": 0.55, "cash_mmf": 0.15},
    "global_credit":     {"kr_equity": 0.05, "global_equity": 0.05, "fx_commodity": 0.10, "bond": 0.45, "cash_mmf": 0.35},
    "kr_boom":           {"kr_equity": 0.40, "global_equity": 0.20, "fx_commodity": 0.05, "bond": 0.30, "cash_mmf": 0.05},
    "kr_stress":         {"kr_equity": 0.05, "global_equity": 0.30, "fx_commodity": 0.10, "bond": 0.45, "cash_mmf": 0.10},
}


# Self-validation (모듈 import 시 보장)
_BUCKET_KEYS = ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf")


def _validate() -> None:
    for name, w in SCENARIO_BUCKETS.items():
        if set(w.keys()) != set(_BUCKET_KEYS):
            raise ValueError(f"{name}: bucket keys mismatch")
        total = sum(w.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"{name}: weights sum {total} != 1.0")
        risk = w["kr_equity"] + w["global_equity"] + w["fx_commodity"]
        if risk > 0.70 + 1e-6:
            raise ValueError(
                f"{name}: 위험자산 {risk:.3f} > 0.70 (mandate §2.2 위반)"
            )


_validate()
