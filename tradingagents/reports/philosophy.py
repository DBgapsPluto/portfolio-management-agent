"""Investment philosophy document generator (대회 §4.1: ≥4 워드 페이지).

Stage 6 정리: prompt에 Stage 2 시나리오 + Stage 4 lens / numerics + Stage 5
mandate 정보를 *섹션별 명시 매핑*으로 주입. LLM 호출 수는 유지 (1-2회).
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


PHILOSOPHY_PROMPT = """\
You are writing the investment philosophy document for a Korean investment competition.

Mandatory sections (each ≥600 chars in Korean):
1. 매크로 환경 진단 — Stage 1 macro_quant 요약 인용 (regime, yield curve, inflation, employment)
2. 시장 리스크 평가 — Stage 1 market_risk + Stage 4 portfolio_numerics 인용 (VIX, credit spread, CVaR, HHI)
3. 자산군 비중 결정 논리 — Stage 2 시나리오 확률 분포 + 5-bucket target 인용
4. 단일 리스크 통제 전략 — Stage 4 concentration lens + Stage 5 cluster cap (0.25) 인용
5. 시장 충격 시나리오 — Stage 2 7개 시나리오 중 보수형 (broad_recession/global_credit/kr_stress) + Stage 4 tail_risk lens 인용
6. 매매 원칙 — Stage 5 rebalance_mode + turnover floor 인용

Inputs:
{state_summary}

CRITICAL RULES (대회 §4.2):
- Korean only
- DO NOT copy ETF prospectus text or news headlines verbatim
- All numbers MUST come from the inputs above
- Total ≥4000 chars
- 섹션별로 위에 명시된 Stage 출력을 *구체 수치로* 인용

Output the full markdown document."""


def _format_scenario_probs(rd) -> str:
    """ResearchDecision.scenario_probabilities → 정렬된 한 줄 요약."""
    if rd is None or not hasattr(rd, "scenario_probabilities"):
        return "(none)"
    try:
        probs = rd.scenario_probabilities.as_dict()
    except AttributeError:
        return "(unavailable)"
    sorted_p = sorted(probs.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{name} {p*100:.0f}%" for name, p in sorted_p)


def _format_overlay(overlay) -> str:
    """RiskOverlay → 짧은 요약."""
    if overlay is None:
        return "(none — Stage 4 not run or empty)"
    if overlay.is_empty():
        return f"(empty — {overlay.severity_decision})"
    lens_summary = "; ".join(
        f"{lc.lens}={lc.level}" for lc in overlay.lens_concerns
    ) if overlay.lens_concerns else "(no lens concerns)"
    return (
        f"strength={overlay.strength_applied:.2f}, "
        f"multiplier={overlay.risk_asset_multiplier:.2f}, "
        f"ceilings={len(overlay.weight_ceilings)}, "
        f"floors={len(overlay.tail_hedge_floor)} | {lens_summary}"
    )


def _format_numerics(n) -> str:
    if n is None:
        return "(not computed)"
    return (
        f"HHI={n.hhi:.3f}, top1={n.top1_weight*100:.1f}%, "
        f"top3_sum={n.top3_weight_sum*100:.1f}%, "
        f"max_cluster={n.max_cluster_exposure*100:.1f}%, "
        f"CVaR_95={n.cvar_95_1d*100:.2f}%, vol_60d={n.realized_vol_60d*100:.2f}%"
    )


def _format_validation(report) -> str:
    if report is None:
        return "(not validated)"
    n_hard = sum(1 for v in report.violations if v.severity == "hard")
    n_soft = sum(1 for v in report.violations if v.severity == "soft")
    return (
        f"passed={report.passed}, hard_violations={n_hard}, soft={n_soft}"
    )


def _build_state_summary(state: dict) -> str:
    """philosophy prompt에 들어가는 풍부한 state 요약 (Stage 6 정리 ②).

    이전엔 Stage 1 summary 4 + bucket_target만. 신규: Stage 2 ResearchDecision,
    Stage 3 MethodChoice, Stage 4 RiskOverlay + PortfolioNumerics, Stage 5
    ValidationReport, rebalance_mode 모두 명시.
    """
    wv = state["weight_vector"]
    rd = state.get("research_decision")
    overlay = state.get("risk_overlay")
    numerics = state.get("portfolio_numerics")
    validation = state.get("validation_report")
    rebalance_mode = state.get("rebalance_mode", "unknown")
    method_choice = state.get("method_choice")

    method_reasoning = ""
    if method_choice is not None:
        # MethodChoice는 dict 또는 Pydantic 둘 다 지원
        if isinstance(method_choice, dict):
            method_reasoning = method_choice.get("reasoning", "")
        else:
            method_reasoning = getattr(method_choice, "reasoning", "")

    return (
        "### Stage 1 — Analyst Summaries\n"
        f"#### Macro\n{state.get('macro_summary', '')}\n\n"
        f"#### Risk\n{state.get('risk_summary', '')}\n\n"
        f"#### Technical\n{state.get('technical_summary', '')}\n\n"
        f"#### News\n{state.get('news_summary', '')}\n\n"
        "### Stage 2 — Research Decision\n"
        f"{state.get('research_debate_summary', '')}\n"
        f"Scenario probabilities: {_format_scenario_probs(rd)}\n\n"
        "### Stage 3 — Method choice\n"
        f"Selected: {wv.method.value}\n"
        f"Reasoning: {method_reasoning}\n\n"
        "### Stage 4 — Risk Overlay\n"
        f"Overlay: {_format_overlay(overlay)}\n"
        f"Portfolio numerics: {_format_numerics(numerics)}\n\n"
        "### Stage 5 — Mandate Validation\n"
        f"{_format_validation(validation)}\n"
        f"Rebalance mode: {rebalance_mode}\n\n"
        "### Final Portfolio\n"
        f"Method: {wv.method.value}\n"
        f"Top 5 weights: "
        f"{sorted(wv.weights.items(), key=lambda x: -x[1])[:5]}\n"
        f"Rationale: {wv.rationale}\n"
    )


def generate_philosophy(state: dict, deep_llm) -> str:
    state_summary = _build_state_summary(state)
    response = deep_llm.invoke(
        PHILOSOPHY_PROMPT.format(state_summary=state_summary)
    )
    text = response.content
    if len(text) < 4000:
        retry = deep_llm.invoke(
            f"The document below is only {len(text)} chars. Expand each of 6 "
            f"sections to ≥600 chars (total ≥4000):\n\n{text}"
        )
        text = retry.content
    if len(text) < 4000:
        logger.warning(
            "philosophy.md only %d chars after retry — manual review required",
            len(text),
        )
    return text


def write_philosophy(state: dict, deep_llm, out_path: Path) -> Path:
    text = generate_philosophy(state, deep_llm)
    out_path.write_text(text, encoding="utf-8")
    return out_path
