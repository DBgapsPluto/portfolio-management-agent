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
from typing import Optional

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
CONVICTION_HIGH_ALIGN: float = 0.6       # 3 중 2 동의 (3-factor sign vote)
CONVICTION_MED_ALIGN: float = 0.3        # 3 중 1 동의


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
        liquidity_regime=_blend(new.liquidity_regime, "F9_liquidity_regime"),
    )


def derive_dominant_scenario(factor_scores: FactorScores) -> str:
    """Legacy compat — deterministic mapping factor z → 7 scenario name.

    Priority:
      1. F7 > VOL_THRESHOLD AND F5 > CREDIT_THRESHOLD → "global_credit"
      2. F6 > KR_THRESHOLD → "kr_stress" (if F5/F7 > KR_CORROBORATE) else "kr_boom"
      3. F6 < -KR_THRESHOLD → "kr_boom"
      4. cycle quadrant (F1, F2) at ±CYCLE_THRESHOLD:
         F1>+, F2>+ → "overheating"     | F1>+, F2<- → "goldilocks"
         F1<-, F2>+ → "stagflation"     | F1<-, F2<- → "broad_recession"
      5. default → "goldilocks"

    Stage 2 audit (Task 1): hysteresis 없음. z 가 threshold 의 미세한 어느 한 쪽에
    있으면 scenario 가 바로 jump. 운영 시 매 run 의 미세 변화로 시나리오 불안정
    가능 — 영향 통합 테스트로 확인. hysteresis 도입은 별도 PR.
    """
    f1 = factor_scores.growth_surprise.z_score
    f2 = factor_scores.inflation_surprise.z_score
    f5 = factor_scores.credit_cycle.z_score
    f6 = factor_scores.krw_regime.z_score
    f7 = factor_scores.equity_vol_regime.z_score

    if f7 > SCENARIO_VOL_THRESHOLD and f5 > SCENARIO_CREDIT_THRESHOLD:
        return "global_credit"
    if f6 > SCENARIO_KR_THRESHOLD:
        if f5 > SCENARIO_KR_CORROBORATE or f7 > SCENARIO_KR_CORROBORATE:
            return "kr_stress"
        return "kr_boom"
    if f6 < -SCENARIO_KR_THRESHOLD:
        return "kr_boom"

    if f1 > SCENARIO_CYCLE_THRESHOLD and f2 > SCENARIO_CYCLE_THRESHOLD:
        return "overheating"
    if f1 > SCENARIO_CYCLE_THRESHOLD and f2 < -SCENARIO_CYCLE_THRESHOLD:
        return "goldilocks"
    if f1 < -SCENARIO_CYCLE_THRESHOLD and f2 > SCENARIO_CYCLE_THRESHOLD:
        return "stagflation"
    if f1 < -SCENARIO_CYCLE_THRESHOLD and f2 < -SCENARIO_CYCLE_THRESHOLD:
        return "broad_recession"
    return "goldilocks"


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
                factor_scores.liquidity_regime,
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

        # 4. Legacy compat fields
        dominant_scenario = derive_dominant_scenario(factor_scores)
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
