"""Research Manager (Stage 2) — Factor model (PR 2026-05-22).

Pipeline:
  Stage 1 (4 analyst struct + 4 summary) → AgentState
    → compute_all_factors(state) → FactorScores (9 z-vector)
    → apply_prior_smoothing (EMA in factor space, λ=1 default no-op)
    → apply_factor_model_with_safety(z) → (bucket, tips, contributions, diagnostics)
    → derive_dominant_scenario + derive_conviction (deterministic legacy compat)
    → ResearchDecision

Stage 2 추가 LLM 호출 0. macro_news_analyst 의 NewsReport structured field 활용 (Option Z).
"""
import logging
from dataclasses import replace
from typing import Any, Optional

logger = logging.getLogger(__name__)

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.schemas.research import ResearchDecision
from tradingagents.skills.research.factor_estimators import (
    FactorScore,
    FactorScores,
    compute_all_factors,
)
from tradingagents.skills.research.factor_to_bucket import (
    FACTORS,
    INITIAL_BASELINE,
    apply_factor_model_with_safety,
)


# Temporal smoothing (factor space). EMA infrastructure 유지 — default no-op.
# λ=1.0 → 100% new (prior 무시). λ<1.0 → λ·new + (1-λ)·prior. 시간 안정성 vs 반응성.
_EMA_LAMBDA: float = 1.0


# Stage 2 audit (2026-05-26, Task 1): scenario / conviction mapping thresholds.
# named constants — 도출 근거 + tuning 후보 표시. hysteresis 없음 (단발 z crossing →
# scenario jump). 현재 동작이 fragile 한 영역이지만 hysteresis 도입은 별도 brainstorm.
#
# 시나리오 boundary 의미 (논리적 근거):
#   z=0.5  → ~1σ 미만의 약한 cycle 신호 (균형 추세 진입)
#   z=1.0  → ~1σ 표준 cycle 신호 (KR-specific 식별선)
#   z=1.5  → ~1.5σ 강한 vol 신호 (global_credit stress)
SCENARIO_CYCLE_THRESHOLD: float = 0.5    # F1/F2 cycle quadrant boundary
SCENARIO_KR_THRESHOLD: float = 1.0       # F6 KR-specific (kr_stress / kr_boom)
SCENARIO_KR_CORROBORATE: float = 0.5     # F5/F7 corroboration for kr_stress
SCENARIO_VOL_THRESHOLD: float = 1.5      # F7 vol — global_credit upper gate
SCENARIO_CREDIT_THRESHOLD: float = 1.0   # F5 credit — global_credit upper gate

# Conviction 형식: total_mag = Σ|z|, alignment = 3-factor (F1+, F5-, F7-) sign agreement
# 9 factor 중 risk-on/off 의 핵심 proxy 3개만 사용 — F1=cycle, F5=credit, F7=vol.
# 나머지 6 factor 는 conviction 계산에 미반영 (개선 후보, Stage 2 audit followup).
CONVICTION_HIGH_MAG: float = 4.0         # 평균 |z|≈0.44 (9 factor 모두 ~0.4σ)
CONVICTION_MED_MAG: float = 2.0          # 평균 |z|≈0.22 (절반 factor 가 ~0.4σ)

# 2026-05-26 #8 fix — regime confidence → bucket sizing mapping rule.
# Stage 1 의 LLM regime classifier confidence (0~1) 가 Stage 3 bucket sizing 에
# 명시적 영향. high confidence (≥0.8) 면 위험자산 신호 강화 (×1.05), low
# confidence (<0.5) 면 약화 (×0.92). mandate cap (0.70) 은 여전히 enforce.
# 평가의 핵심 architecture 비판 ("confidence 0.89 vs 위험자산 37.5% 불일치") 해소.
REGIME_CONFIDENCE_HIGH: float = 0.8        # 이 이상이면 risk multiplier 1.05
REGIME_CONFIDENCE_LOW: float = 0.5         # 미만이면 multiplier 0.92
RISK_MULT_HIGH_CONF: float = 1.05
RISK_MULT_LOW_CONF: float = 0.92
RISK_MULT_NEUTRAL: float = 1.0


def _confidence_risk_multiplier(confidence: float | None) -> float:
    """regime confidence → 위험자산 multiplier (1.05 / 1.0 / 0.92)."""
    if confidence is None:
        return RISK_MULT_NEUTRAL
    if confidence >= REGIME_CONFIDENCE_HIGH:
        return RISK_MULT_HIGH_CONF
    if confidence < REGIME_CONFIDENCE_LOW:
        return RISK_MULT_LOW_CONF
    return RISK_MULT_NEUTRAL


def _apply_confidence_to_bucket(
    bucket: dict[str, float], confidence: float | None,
    risk_buckets: tuple[str, ...] = ("kr_equity", "global_equity", "fx_commodity"),
    mandate_risk_cap: float = 0.70,
) -> tuple[dict[str, float], float]:
    """bucket 의 위험자산에 confidence multiplier 적용. mandate cap enforce.

    Returns (new_bucket, applied_multiplier).
    """
    mult = _confidence_risk_multiplier(confidence)
    if abs(mult - 1.0) < 1e-9:
        return bucket, 1.0
    risk_total = sum(bucket.get(b, 0.0) for b in risk_buckets)
    new_risk = min(risk_total * mult, mandate_risk_cap)
    if risk_total <= 0:
        return bucket, mult
    risk_factor = new_risk / risk_total
    diff = new_risk - risk_total  # 음수면 위험자산 줄어듦, 양수면 늘어남
    new_bucket = dict(bucket)
    for b in risk_buckets:
        new_bucket[b] = new_bucket.get(b, 0.0) * risk_factor
    # diff 만큼 안전자산 (bond + cash_mmf) 에 비례 redistribute.
    safe_total = new_bucket.get("bond", 0.0) + new_bucket.get("cash_mmf", 0.0)
    if safe_total > 0:
        bond_share = new_bucket.get("bond", 0.0) / safe_total
        new_bucket["bond"] = new_bucket.get("bond", 0.0) - diff * bond_share
        new_bucket["cash_mmf"] = new_bucket.get("cash_mmf", 0.0) - diff * (1 - bond_share)
    return new_bucket, mult
CONVICTION_HIGH_ALIGN: float = 0.6       # 3 중 2 동의 (3-factor sign vote)
CONVICTION_MED_ALIGN: float = 0.3        # 3 중 1 동의

# Backtest prep (2026-05-26): scenario hysteresis — z-score 가 threshold 직전·직후
# 에서 진동하면 scenario jump → portfolio 출렁임 → backtest noise. prior decision
# 의 scenario 가 relaxed entry zone (threshold - band) 안에 있으면 유지.
#
# Priority 의 의미: 낮은 숫자 = 더 urgent state. 더 urgent 로 전환은 hysteresis 무시
# (즉시 switch). 같거나 덜 urgent 로 전환만 hysteresis 적용 (premature exit 방지).
SCENARIO_HYSTERESIS_BAND: float = 0.05   # ±5% z-score deadband
SCENARIO_PRIORITY: dict[str, int] = {
    "global_credit":   1,   # 가장 urgent (극단 stress)
    "kr_stress":       2,
    "kr_boom":         3,
    "broad_recession": 4,
    "stagflation":     5,
    "overheating":     6,
    # 2026-05-26 #5 fix — late_cycle + sticky inflation cell 추가.
    # 평가의 "변형된 골디락스" hedge 해소. F1 약양 (cycle threshold 못 넘는 약한
    # 확장) + F2 인플레 잔존 (≥0.4) + F5 신용 약세 (≤-0.2) 의 특정 상태.
    # stagflation 보다 약함 (growth 안 무너짐), overheating 보다 신용 약함.
    "late_cycle":      7,
    "goldilocks":      8,   # default (가장 benign)
}


def _blend_factors_with_prior(
    new: FactorScores,
    prior_decision: Optional[ResearchDecision],
    lam: float,
) -> FactorScores:
    """EMA on factor z-vector. λ=1 → identity. prior None → identity."""
    if prior_decision is None or lam >= 1.0 - 1e-9:
        return new
    prior_z = prior_decision.factor_scores
    if not prior_z:
        return new

    def _blend(new_factor: FactorScore, prior_key: str) -> FactorScore:
        prior_val = prior_z.get(prior_key, new_factor.z_score)
        blended_z = lam * new_factor.z_score + (1 - lam) * prior_val
        return replace(new_factor, z_score=blended_z)

    return FactorScores(
        growth_surprise=_blend(new.growth_surprise, "F1_growth"),
        inflation_surprise=_blend(new.inflation_surprise, "F2_inflation"),
        real_rate=_blend(new.real_rate, "F3_real_rate"),
        term_premium=_blend(new.term_premium, "F4_term_premium"),
        credit_cycle=_blend(new.credit_cycle, "F5_credit_cycle"),
        krw_regime=_blend(new.krw_regime, "F6_krw_regime"),
        equity_vol_regime=_blend(new.equity_vol_regime, "F7_equity_vol_regime"),
        valuation=_blend(new.valuation, "F8_valuation"),
        market_dispersion=_blend(new.market_dispersion, "F9_market_dispersion"),
    )


def _strict_classify_scenario(
    f1: float, f2: float, f5: float, f6: float, f7: float,
    offset: float = 0.0,
) -> str:
    """Strict scenario classification — entry threshold + offset 으로 평가.

    offset=0 → 정상 (entry) 검사. offset<0 → relaxed (exit) 검사 (hysteresis 용).
    예: offset=-0.05 → threshold 가 0.5-(-0.05)*sign(threshold)=... 가 아니라
    "threshold 의 magnitude 를 0.05 줄임" — entry 시 0.5 필요했던 게 0.45 만 필요.
    """
    cycle = SCENARIO_CYCLE_THRESHOLD + offset
    kr = SCENARIO_KR_THRESHOLD + offset
    kr_corr = SCENARIO_KR_CORROBORATE + offset
    vol = SCENARIO_VOL_THRESHOLD + offset
    credit = SCENARIO_CREDIT_THRESHOLD + offset

    if f7 > vol and f5 > credit:
        return "global_credit"
    if f6 > kr:
        if f5 > kr_corr or f7 > kr_corr:
            return "kr_stress"
        return "kr_boom"
    if f6 < -kr:
        return "kr_boom"

    if f1 > cycle and f2 > cycle:
        return "overheating"
    if f1 > cycle and f2 < -cycle:
        return "goldilocks"
    if f1 < -cycle and f2 > cycle:
        return "stagflation"
    if f1 < -cycle and f2 < -cycle:
        return "broad_recession"
    # 2026-05-26 #5 fix — late_cycle + sticky inflation.
    # overheating 진입 못 했지만 (F1 ≤ cycle) 인플레+신용 약세 결합 신호.
    # F1 양수 (성장 무너지지 않음) + F2 ≥ 0.4 (인플레 잔존, cycle 보다 약간 낮은
    # threshold) + F5 ≤ -0.2 (신용 약세) → late_cycle. offset 적용.
    late_inflation = 0.4 + offset
    late_credit = -0.2 - offset
    if f1 > 0 and f2 > late_inflation and f5 < late_credit:
        return "late_cycle"
    return "goldilocks"


def _is_in_scenario_relaxed(
    f1: float, f2: float, f5: float, f6: float, f7: float,
    target_scenario: str, band: float,
) -> bool:
    """target_scenario 의 relaxed entry 조건 (threshold - band) 을 만족하는가."""
    relaxed_classification = _strict_classify_scenario(
        f1, f2, f5, f6, f7, offset=-band,
    )
    # 핵심 점검: relaxed offset 이면 같은 scenario 분류로 떨어지는가.
    # _strict_classify 의 priority 가 있으므로, relaxed 에서 같은 결과 → 여전히
    # entry zone (band 안) 에 있음.
    return relaxed_classification == target_scenario


def derive_dominant_scenario(
    factor_scores: FactorScores,
    prior_scenario: str | None = None,
    hysteresis_band: float = SCENARIO_HYSTERESIS_BAND,
) -> str:
    """Deterministic mapping factor z → 7 scenario name + optional hysteresis.

    Priority (가장 urgent 부터):
      1. F7 > VOL_THRESHOLD AND F5 > CREDIT_THRESHOLD → "global_credit"
      2. F6 > KR_THRESHOLD → "kr_stress" (if F5/F7 > KR_CORROBORATE) else "kr_boom"
      3. F6 < -KR_THRESHOLD → "kr_boom"
      4. cycle quadrant (F1, F2) at ±CYCLE_THRESHOLD:
         F1>+, F2>+ → "overheating"     | F1>+, F2<- → "goldilocks"
         F1<-, F2>+ → "stagflation"     | F1<-, F2<- → "broad_recession"
      5. default → "goldilocks"

    Hysteresis (2026-05-26 backtest prep): prior_scenario 가 있으면 z 가
    threshold 직전·직후 fluctuation 으로 scenario jump 방지.
    - 더 urgent (낮은 priority 숫자) 로 전환은 hysteresis 무시 → 즉시 switch
    - 같거나 덜 urgent 로 전환은 prior 가 relaxed entry zone 안에 있으면 유지
    """
    f1 = factor_scores.growth_surprise.z_score
    f2 = factor_scores.inflation_surprise.z_score
    f5 = factor_scores.credit_cycle.z_score
    f6 = factor_scores.krw_regime.z_score
    f7 = factor_scores.equity_vol_regime.z_score

    new_scenario = _strict_classify_scenario(f1, f2, f5, f6, f7)

    if prior_scenario is None or prior_scenario == new_scenario:
        return new_scenario

    # 다른 scenario 로 전환 후보. priority 비교.
    new_priority = SCENARIO_PRIORITY.get(new_scenario, 99)
    prior_priority = SCENARIO_PRIORITY.get(prior_scenario, 99)

    if new_priority < prior_priority:
        # 더 urgent state 로 전환 — 즉시 switch (hysteresis 무시).
        return new_scenario

    # 같거나 덜 urgent — hysteresis 적용.
    # prior_scenario 가 relaxed entry zone (band 감소된 threshold) 안에 있으면 유지.
    if _is_in_scenario_relaxed(f1, f2, f5, f6, f7, prior_scenario, hysteresis_band):
        return prior_scenario
    return new_scenario


def derive_conviction(factor_scores: FactorScores) -> str:
    """total magnitude + sign agreement 기반 conviction (high/medium/low).

    9 factor 의 |z| 합 (total magnitude) 으로 신호 강도 측정 + 3-factor 핵심 proxy
    (F1 cycle, F5 credit, F7 vol) 의 부호 일치도로 risk-on/off 정렬 측정.

    Stage 2 audit (Task 1): 9 factor 중 3 만 alignment 에 사용 — F1 growth는 +가 risk-on,
    F5 credit_cycle 는 +가 stress (risk-off, sign 뒤집음), F7 equity_vol_regime 도
    +가 stress (sign 뒤집음). 나머지 6 factor 미반영은 conviction 의 단순화. 개선
    여지: F2 inflation, F6 krw 도 weighted alignment 에 포함하기.
    """
    z_dict = factor_scores.to_dict()
    total_mag = sum(abs(z) for z in z_dict.values())
    # 주요 risk-on/off factor — F1 growth (+), F5 credit_cycle (-), F7 vol (-)
    signs = [
        z_dict["F1_growth"],
        -z_dict["F5_credit_cycle"],
        -z_dict["F7_equity_vol_regime"],
    ]
    avg_sign_count = sum(1 if s > 0 else -1 if s < 0 else 0 for s in signs)
    alignment = abs(avg_sign_count) / len(signs)

    if total_mag > CONVICTION_HIGH_MAG and alignment > CONVICTION_HIGH_ALIGN:
        return "high"
    if total_mag > CONVICTION_MED_MAG and alignment > CONVICTION_MED_ALIGN:
        return "medium"
    return "low"


def create_research_manager(deep_llm):
    """Note: deep_llm 인자 유지 (interface compat), 사용 안 함."""

    def node(state):
        logger.info("research_manager start: computing 9-factor z-vector")

        # 1. Compute 9 factors (deterministic)
        factor_scores = compute_all_factors(state)
        z_dict_pre = factor_scores.to_dict()
        n_active = sum(
            1 for f in [
                factor_scores.growth_surprise, factor_scores.inflation_surprise,
                factor_scores.real_rate, factor_scores.term_premium,
                factor_scores.credit_cycle, factor_scores.krw_regime,
                factor_scores.equity_vol_regime, factor_scores.valuation,
                factor_scores.market_dispersion,
            ] if f.confidence > 0.0
        )
        logger.info(
            "research_manager: 9 factors computed (%d/9 with active components), "
            "|z| sum=%.2f",
            n_active, sum(abs(v) for v in z_dict_pre.values()),
        )

        # 2. EMA blend (λ=1.0 default no-op)
        prior_decision: Optional[ResearchDecision] = state.get("prior_research_decision")
        if prior_decision is not None and _EMA_LAMBDA < 1.0 - 1e-9:
            logger.info(
                "research_manager: EMA blend active (λ=%.2f, prior present)", _EMA_LAMBDA,
            )
        factor_scores = _blend_factors_with_prior(
            factor_scores, prior_decision, _EMA_LAMBDA,
        )

        # 3. Factor → bucket + QP mandate projection + safety diagnostics
        bucket, tips_share, contributions, safety_diag = apply_factor_model_with_safety(
            factor_scores.to_dict()
        )

        # 2026-05-26 #8 fix — regime confidence × bucket sizing mapping.
        # Stage 1 의 LLM regime classifier confidence 를 bucket sizing 에 반영.
        # macro_report.regime.confidence (있으면) → 위험자산 multiplier (1.05/1.0/0.92).
        macro_report = state.get("macro_report")
        regime = getattr(macro_report, "regime", None) if macro_report else None
        regime_confidence = (
            float(getattr(regime, "confidence", 0.0)) if regime else None
        )
        bucket, confidence_mult = _apply_confidence_to_bucket(
            bucket, regime_confidence,
        )
        if abs(confidence_mult - 1.0) > 1e-9:
            logger.info(
                "research_manager: confidence (%.2f) → risk_multiplier %.2f applied to bucket",
                regime_confidence or 0.0, confidence_mult,
            )
        safety_diag["regime_confidence"] = regime_confidence
        safety_diag["confidence_risk_multiplier"] = confidence_mult

        # 2026-05-26 #3 fix — component-level outlier signal extraction.
        # factor aggregate z 는 (예: F6=+0.137) 가 묻히지만 그 안의 단일 component
        # (예: foreign_flow_z 가 외국인 -43.8조 → z=-3+) 는 distribution-top 신호.
        # 모든 9 factor 의 components 검사 → |z| ≥ 3 인 outlier 추출 → 운영자
        # 가시화 (philosophy.md narrative + risk_judge 가 사용 가능).
        extreme_components: list[dict[str, Any]] = []
        for factor_name in (
            "growth_surprise", "inflation_surprise", "real_rate",
            "term_premium", "credit_cycle", "krw_regime",
            "equity_vol_regime", "valuation", "market_dispersion",
        ):
            fs = getattr(factor_scores, factor_name, None)
            if fs is None:
                continue
            for comp_name, comp_z in (fs.components or {}).items():
                if abs(float(comp_z)) >= 3.0:
                    extreme_components.append({
                        "factor": fs.name,
                        "component": comp_name,
                        "z": round(float(comp_z), 3),
                        "factor_aggregate_z": round(float(fs.z_score), 3),
                    })
        if extreme_components:
            logger.warning(
                "research_manager: %d extreme component(s) detected — %s",
                len(extreme_components),
                [(c["factor"], c["component"], c["z"]) for c in extreme_components],
            )
        safety_diag["extreme_components"] = extreme_components

        # 4. Legacy compat fields — scenario hysteresis 적용 (backtest prep).
        prior_scenario = (
            getattr(prior_decision, "dominant_scenario", None)
            if prior_decision is not None else None
        )
        dominant_scenario = derive_dominant_scenario(
            factor_scores, prior_scenario=prior_scenario,
        )
        if prior_scenario and prior_scenario != dominant_scenario:
            logger.info(
                "research_manager: scenario transition %s → %s (priority %d → %d)",
                prior_scenario, dominant_scenario,
                SCENARIO_PRIORITY.get(prior_scenario, 99),
                SCENARIO_PRIORITY.get(dominant_scenario, 99),
            )
        elif prior_scenario and prior_scenario == dominant_scenario:
            # Hysteresis 가 발동했을 수 있음 (strict 와 결과 비교).
            strict_new = _strict_classify_scenario(
                factor_scores.growth_surprise.z_score,
                factor_scores.inflation_surprise.z_score,
                factor_scores.credit_cycle.z_score,
                factor_scores.krw_regime.z_score,
                factor_scores.equity_vol_regime.z_score,
            )
            if strict_new != dominant_scenario:
                logger.info(
                    "research_manager: hysteresis held — strict=%s vs maintained=%s",
                    strict_new, dominant_scenario,
                )
        conviction = derive_conviction(factor_scores)
        logger.info(
            "research_manager: scenario=%s, conviction=%s, "
            "extreme_factor=%s, projection_intervened=%s",
            dominant_scenario, conviction,
            safety_diag.get("extreme_factor_active"),
            safety_diag.get("projection_intervened"),
        )

        # 5. BucketTarget
        z_dict = factor_scores.to_dict()
        z_str_top = ", ".join(
            f"{f}={z_dict[f]:+.2f}"
            for f in sorted(z_dict, key=lambda k: -abs(z_dict[k]))[:3]
        )
        rationale = (
            f"Factor model: dominant_scenario={dominant_scenario}, conviction={conviction}. "
            f"Top contributors: {z_str_top}"
        )[:500]

        target = BucketTarget(
            kr_equity=bucket["kr_equity"],
            global_equity=bucket["global_equity"],
            fx_commodity=bucket["fx_commodity"],
            bond=bucket["bond"],
            cash_mmf=bucket["cash_mmf"],
            bond_tips_share=tips_share,
            rationale=rationale,
        )

        # 6. ResearchDecision — factor model 만 (C5: 24-cell field 제거됨)
        decision = ResearchDecision(
            bucket_target=target,
            conviction=conviction,
            dominant_scenario=dominant_scenario,
            # Factor model
            factor_scores=z_dict,
            factor_contributions=contributions,
            baseline_bucket=dict(INITIAL_BASELINE),
            safety_diagnostics=safety_diag,
        )

        # Stage 2 audit (Task 0): top-3 contributors (|β·z| 큰 순) — "왜 이 bucket?" trace.
        # contributions 형태: dict[bucket, dict[factor, β·z 기여도]]
        flat_contribs: list[tuple[str, str, float]] = []
        for bucket_name, fmap in (contributions or {}).items():
            for factor_name, contrib in (fmap or {}).items():
                flat_contribs.append((bucket_name, factor_name, contrib))
        flat_contribs.sort(key=lambda x: -abs(x[2]))
        top_contribs_str = ", ".join(
            f"{f}→{b} {c*100:+.1f}pp"
            for b, f, c in flat_contribs[:3]
        ) or "(none)"

        # Safety diagnostics 의 핵심 3 키 — projection 발동, mandate 위반, extreme factor.
        diag_line = (
            f"Safety: mandate_violated_pre={safety_diag.get('mandate_violated_pre_projection')}, "
            f"projection_intervened={safety_diag.get('projection_intervened')}, "
            f"l2_distance={safety_diag.get('projection_l2_distance', 0.0):.3f}, "
            f"extreme_factor={safety_diag.get('extreme_factor_active')}\n"
        )

        # 7. Summary text
        summary = (
            f"## Research Decision (Factor Model)\n"
            f"Dominant scenario: {dominant_scenario} ({conviction})\n"
            f"Top contributors: {top_contribs_str}\n"
            f"{diag_line}\n"
            f"Factor z-scores:\n"
            + "\n".join(f"  {f}: {z:+.2f}" for f, z in z_dict.items())
            + f"\n\n## Bucket Target\n"
            f"국내주식: {target.kr_equity*100:.1f}%, "
            f"해외주식: {target.global_equity*100:.1f}%, "
            f"FX/원자재: {target.fx_commodity*100:.1f}%, "
            f"채권: {target.bond*100:.1f}% (TIPS {tips_share*100:.0f}%), "
            f"MMF: {target.cash_mmf*100:.1f}%\n"
            f"위험자산 합: {(target.kr_equity + target.global_equity + target.fx_commodity)*100:.1f}%"
        )

        return {
            "bucket_target": target,
            "research_decision": decision,
            "research_debate_summary": summary,
        }

    return node
