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
_EMA_LAMBDA: float = 1.0


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
    """Legacy compat — deterministic mapping factor z → scenario name.

    Priority:
      1. F7 > 1.5 AND F5 > 1.0 → "global_credit"
      2. F6 > 1.0 → "kr_stress" (if F5/F7 > 0.5 corroborate) else "kr_boom"
      3. F6 < -1.0 → "kr_boom"
      4. cycle quadrant (F1, F2):
         F1>0.5 + F2>0.5 → "overheating"
         F1>0.5 + F2<-0.5 → "goldilocks"
         F1<-0.5 + F2>0.5 → "stagflation"
         F1<-0.5 + F2<-0.5 → "broad_recession"
      5. default → "goldilocks"
    """
    f1 = factor_scores.growth_surprise.z_score
    f2 = factor_scores.inflation_surprise.z_score
    f5 = factor_scores.credit_cycle.z_score
    f6 = factor_scores.krw_regime.z_score
    f7 = factor_scores.equity_vol_regime.z_score

    if f7 > 1.5 and f5 > 1.0:
        return "global_credit"
    if f6 > 1.0:
        if f5 > 0.5 or f7 > 0.5:
            return "kr_stress"
        return "kr_boom"
    if f6 < -1.0:
        return "kr_boom"

    if f1 > 0.5 and f2 > 0.5:
        return "overheating"
    if f1 > 0.5 and f2 < -0.5:
        return "goldilocks"
    if f1 < -0.5 and f2 > 0.5:
        return "stagflation"
    if f1 < -0.5 and f2 < -0.5:
        return "broad_recession"
    return "goldilocks"


def derive_conviction(factor_scores: FactorScores) -> str:
    """total magnitude + sign agreement 기반."""
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

    if total_mag > 4.0 and alignment > 0.6:
        return "high"
    if total_mag > 2.0 and alignment > 0.3:
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
