"""Research Manager (Stage 2) — 24-cell Cartesian product framework.

흐름:
  Stage 1 summaries (macro/risk/technical/news) + Stage 0 신호 cleaning
  (conditional stress surprise + KR residual signals)
    → estimator (deep_llm 1회, ScenarioProbabilities24 산출 — 24 cell 분포)
    → map_probs_to_bucket (결정적 가중평균, BucketTarget + dominant_cell/cycle)
    → ResearchDecision

axis 정의:
  D1 cycle (4): A/B/C/D
  D2 tail (2):  N/T  (conditional surprise z 기준)
  D3 kr (3):    F/boom/stress  (residual signal 기준)

mandate (위험자산 ≤ 0.70)은 모든 cell playbook이 ≤ 0.70 → 선형결합 자동 보장.
"""
from tradingagents.schemas.research import (
    ALL_CELLS, ResearchDecision, ScenarioProbabilities24,
)
from tradingagents.skills._helpers import invoke_with_structured_retry
from tradingagents.skills.research.scenario_definitions import (
    CYCLE_DEFINITIONS, KR_DEFINITIONS, TAIL_DEFINITIONS,
    all_cells_definition_block,
)
from tradingagents.skills.research.scenario_mapper import map_probs_to_bucket
from tradingagents.skills.risk.conditional_stress import compute_conditional_stress
from tradingagents.skills.risk.kr_residual_signals import compute_kr_residual_signals


# Temporal smoothing (Issue #11 / spec §2 C3 / decisions.md D2, D3).
# C2 variance n=20: flip rate 0%, bond σ 0.3pp ≪ 3pp → 둘 다 no-op default.
# infrastructure 만 구축 — 미래 cycle transition 시점 재측정 후 활성화 권장.
_EMA_LAMBDA: float = 1.0      # D2: λ=1.0 (new only, prior 무시 — no smoothing)
_HYSTERESIS_DELTA: float = 0.0  # D3: Δ=0.0 (off — flip threshold 0)


def _blend_with_prior(
    new: ScenarioProbabilities24,
    prior_decision: ResearchDecision | None,
    lam: float,
) -> ScenarioProbabilities24:
    """EMA blend: final_probs = λ·new + (1-λ)·prior. λ=1.0 또는 prior None 시 identity.

    24-cell 분포 합 = 1.0 보장 (renormalize). reasoning 은 new 의 것 유지.
    """
    if prior_decision is None or lam >= 1.0 - 1e-9:
        return new
    prior_probs = prior_decision.scenario_probabilities
    blended = {
        key: lam * getattr(new, key) + (1.0 - lam) * getattr(prior_probs, key)
        for key in ALL_CELLS
    }
    total = sum(blended.values())
    if total <= 0:
        return new
    blended = {k: v / total for k, v in blended.items()}
    return ScenarioProbabilities24(**blended, reasoning=new.reasoning)


def _apply_hysteresis(
    decision: ResearchDecision,
    prior_decision: ResearchDecision | None,
    delta: float,
) -> ResearchDecision:
    """Dominant cycle 변경 시 새 marginal 이 기존 cycle marginal 보다 +Δ 이상 앞서야 변경.

    Δ=0.0 또는 prior None 또는 cycle 변경 없음 → identity.
    변경 거부 시 dominant_cycle/probability 만 prior 의 값으로 override (marginal 값 보존).
    """
    if prior_decision is None or delta <= 0:
        return decision
    if decision.dominant_cycle == prior_decision.dominant_cycle:
        return decision
    new_dominant = decision.dominant_cycle
    prior_dominant = prior_decision.dominant_cycle
    new_marg = decision.cycle_marginals.get(new_dominant, 0.0)
    prior_in_new = decision.cycle_marginals.get(prior_dominant, 0.0)
    if (new_marg - prior_in_new) >= delta:
        return decision  # large enough — allow change
    # Override: keep prior dominant label (marginal 값은 raw 유지)
    overridden = decision.model_copy(update={
        "dominant_cycle": prior_dominant,  # type: ignore[arg-type]
        "dominant_cycle_probability": prior_in_new,
    })
    return overridden


_CYCLE_BLOCK = "\n".join(f"- {c}: {defn}" for c, defn in CYCLE_DEFINITIONS.items())
_TAIL_BLOCK = "\n".join(f"- {t}: {defn}" for t, defn in TAIL_DEFINITIONS.items())
_KR_BLOCK = "\n".join(f"- {k}: {defn}" for k, defn in KR_DEFINITIONS.items())
_ALL_CELLS_BLOCK = all_cells_definition_block()


ESTIMATOR_PROMPT = f"""\
당신은 자산배분 시나리오 분석가입니다. Stage 1의 4명 분석가 (macro_quant,
market_risk, technical, macro_news)가 만든 요약 4개를 받습니다.

[Framework — 3축 직교 cell 분류]
세계 경제 상태를 3축의 Cartesian product로 표현합니다. 각 cell은 서로 disjoint하고,
24 cell의 union이 전체 상태공간을 덮습니다 (mutually exclusive + exhaustive).

D1 cycle (4 cells):
{_CYCLE_BLOCK}

D2 tail (2 cells):
{_TAIL_BLOCK}

D3 kr (3 cells):
{_KR_BLOCK}

[24 Cell 전체 list — cycle_tail_kr 형식]
{_ALL_CELLS_BLOCK}

[Stage 1 요약]
=== Macro Quant ===
{{macro_summary}}

=== Market Risk ===
{{risk_summary}}

=== Technical ===
{{technical_summary}}

=== Macro News ===
{{news_summary}}

[축 직교성 가이드 — D2, D3 신호 cycle-decontamination (Stage 0)]
{{conditional_stress_block}}
{{kr_residual_block}}

[추정 절차 — axis-aware reasoning]
1. 머릿속에서 먼저 axis별 marginal 추정:
   - D1: A/B/C/D 어느 cycle? (확률 합 = 1.0)
   - D2: N vs T? (P(T) = conditional surprise aggregate_z 기반)
   - D3: F vs boom vs stress? (KR residual score 기반)
2. axis가 독립이면 P(cell) = P(cycle) × P(tail) × P(kr).
   상관 있으면 그 상관 반영 (예: D-T가 A-T보다 자연 결합).
3. 24 cell 분포 출력 — 합 = 1.0 엄격.
4. TRANSIENT cell (B_T_*)은 P ≤ 0.03 권장 (historically rare).
5. reasoning ≤1500자: axis별 marginal 근거 + top 3 cell 근거.

[금지]
- 절대값 thresholds 단독으로 D2=T 판정 (예: "HY OAS > 600bp" 단독으로 tail X).
  반드시 Conditional Stress Surprise block의 aggregate_z 참조.
- kr_yield_curve 같은 cycle proxy로 D3 판정.
  KR Residual Signals block의 kr_stress_score / kr_boom_score만 사용.

ScenarioProbabilities24 JSON 출력. 합 검증 자동 적용.
"""


def _build_signal_blocks(state) -> tuple[str, str]:
    """state의 macro_report + risk_report에서 D2 surprise + D3 residual 산출."""
    macro_report = state.get("macro_report")
    risk_report = state.get("risk_report")
    if macro_report is None or risk_report is None:
        return ("", "")

    try:
        regime = macro_report.regime if hasattr(macro_report, "regime") else macro_report.get("regime")
        if regime is None:
            return ("", "")
        quadrant = regime.quadrant if hasattr(regime, "quadrant") else regime.get("quadrant")
        if quadrant is None:
            return ("", "")

        def _g(obj, *path, default=0.0):
            for p in path:
                if obj is None:
                    return default
                obj = getattr(obj, p, None) if hasattr(obj, p) else (obj.get(p) if isinstance(obj, dict) else None)
            return obj if obj is not None else default

        stress = compute_conditional_stress(
            quadrant,
            hy_oas_bps=_g(risk_report, "credit_spread_us_hy", "current_bps"),
            vix=_g(risk_report, "vix", "current_value"),
            funding_spread_bps=_g(risk_report, "funding_stress", "spread_bps"),
            credit_quality_bps=_g(risk_report, "credit_quality", "quality_spread_bps"),
            equity_bond_corr=_g(risk_report, "equity_bond_corr", "correlation_60d", default=-0.3),
        )
        kr = compute_kr_residual_signals(
            kr_corp_spread_bps=_g(risk_report, "kr_corp_spread", "spread_bps"),
            hy_oas_bps=_g(risk_report, "credit_spread_us_hy", "current_bps"),
            kr_margin_change_20d_pct=_g(risk_report, "kr_margin_debt", "change_20d_pct"),
            kr_tier_relative_pct=_g(risk_report, "kr_market_tier", "relative_perf_pct"),
            foreign_flow_z=_g(macro_report, "foreign_flow", "net_flow_z", default=0.0),
        )
        return (stress.to_prompt_block(), kr.to_prompt_block())
    except Exception:
        return ("", "")


def create_research_manager(deep_llm):
    def node(state):
        conditional_stress_block, kr_residual_block = _build_signal_blocks(state)
        prompt = ESTIMATOR_PROMPT.format(
            macro_summary=state.get("macro_summary", ""),
            risk_summary=state.get("risk_summary", ""),
            technical_summary=state.get("technical_summary", ""),
            news_summary=state.get("news_summary", ""),
            conditional_stress_block=conditional_stress_block,
            kr_residual_block=kr_residual_block,
        )
        probs: ScenarioProbabilities24 = invoke_with_structured_retry(
            deep_llm, ScenarioProbabilities24,
            [{"role": "user", "content": prompt}],
            max_retries=1,
        )

        # EMA temporal smoothing (Issue #11 / D2). λ=1.0 default → identity.
        prior_decision: ResearchDecision | None = state.get("prior_research_decision")
        smoothed_probs = _blend_with_prior(probs, prior_decision, _EMA_LAMBDA)

        decision: ResearchDecision = map_probs_to_bucket(
            smoothed_probs, rationale_seed=smoothed_probs.reasoning[:200],
        )

        # Hysteresis (Issue #11 / D3). Δ=0.0 default → identity.
        decision = _apply_hysteresis(decision, prior_decision, _HYSTERESIS_DELTA)

        target = decision.bucket_target
        # Top cells 표기 (5개만)
        top_cells = sorted(
            decision.scenario_probabilities.as_dict().items(),
            key=lambda kv: -kv[1],
        )[:5]
        cell_lines = "\n".join(
            f"  {key:<14} {p*100:>5.1f}%" for key, p in top_cells
        )
        cycle_lines = "\n".join(
            f"  {c}  {decision.cycle_marginals[c]*100:>5.1f}%"
            for c in sorted(decision.cycle_marginals,
                            key=lambda k: -decision.cycle_marginals[k])
        )

        eff_dom = decision.effective_cycle_marginals.get(decision.dominant_cycle, 0)
        summary = (
            f"## Research Decision (24-cell framework)\n"
            f"**Dominant cycle**: {decision.dominant_cycle} "
            f"({decision.dominant_cycle_probability*100:.1f}% raw, "
            f"{eff_dom*100:.1f}% eff, β={decision.conviction_beta:.2f}, "
            f"{decision.conviction} conviction)\n"
            f"**Dominant cell**:  {decision.dominant_cell.key} "
            f"({decision.dominant_cell_probability*100:.1f}%)\n\n"
            f"Cycle marginal (raw):\n{cycle_lines}\n\n"
            f"Tail marginal: T={decision.tail_marginals.get('T',0)*100:.1f}% / "
            f"N={decision.tail_marginals.get('N',0)*100:.1f}%\n"
            f"KR marginal: F={decision.kr_marginals.get('F',0)*100:.1f}% / "
            f"boom={decision.kr_marginals.get('boom',0)*100:.1f}% / "
            f"stress={decision.kr_marginals.get('stress',0)*100:.1f}%\n\n"
            f"Top cells:\n{cell_lines}\n\n"
            f"## Bucket Target\n"
            f"국내주식: {target.kr_equity*100:.1f}%, "
            f"해외주식: {target.global_equity*100:.1f}%, "
            f"FX/원자재: {target.fx_commodity*100:.1f}%, "
            f"채권: {target.bond*100:.1f}% (TIPS share {target.bond_tips_share*100:.0f}%), "
            f"MMF: {target.cash_mmf*100:.1f}%\n"
            f"위험자산 합: {target.risk_asset_weight*100:.1f}%\n"
            f"근거: {target.rationale[:300]}"
        )

        return {
            "bucket_target": target,
            "research_decision": decision,
            "research_debate_summary": summary,
        }

    return node
