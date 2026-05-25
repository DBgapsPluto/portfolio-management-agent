"""Stage 4 Risk Judge — Phase 2: 3 lens + severity-gated aggregation.

흐름:
  Stage 3 1차 WeightVector  ─┐
  Stage 1 정량 (risk_report) ┤
  Stage 2 ResearchDecision   ┘
                              ↓
                  Stage 3.5 numerics 계산 (LLM 없음)
                              ↓
              ┌─→ tail_risk_lens (LLM 없음, threshold + preset overlay)
              ├─→ concentration_lens (LLM 없음)
              └─→ macro_conditional_lens (LLM 없음)
                              ↓
                  severity_aggregator (3 LensConcern → 단일 RiskOverlay)
                              ↓
                  overlay.is_empty()?
                       ├─ Yes → Stage 3 weight 그대로
                       └─ No  → apply_risk_overlay (Stage 3 2차 호출)

LLM 호출 0회 (Stage 1·2·3 정신 일관). WeightAdjustment.delta는 영구 폐기.
"""
import logging
from datetime import date, timedelta

from tradingagents.agents.allocator.overlay_apply import apply_risk_overlay
from tradingagents.agents.risk_lens.concentration_lens import (
    run_concentration_lens,
)
from tradingagents.agents.risk_lens.macro_conditional_lens import (
    run_macro_conditional_lens,
)
from tradingagents.agents.risk_lens.tail_risk_lens import run_tail_risk_lens
from tradingagents.observability.overlay_stats import record_overlay_outcome
from tradingagents.schemas.risk_overlay import RiskOverlay
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
from tradingagents.skills.risk.portfolio_metrics import compute_portfolio_numerics
from tradingagents.skills.risk.severity_aggregator import aggregate_lens_concerns

logger = logging.getLogger(__name__)


def _extract_risk_signals(risk_report) -> dict:
    """Stage 1 risk_report에서 lens가 쓸 정량 신호 추출. 없으면 안전 기본값."""
    if risk_report is None:
        return {
            "systemic_score": 5.0,
            "vix_term_regime": "contango",
            "funding_regime": "calm",
        }
    systemic = getattr(risk_report, "systemic_score", None)
    vix_term = getattr(risk_report, "vix_term", None)
    funding = getattr(risk_report, "funding_stress", None)
    return {
        "systemic_score": float(systemic.score) if systemic else 5.0,
        "vix_term_regime": getattr(vix_term, "regime", "contango") or "contango",
        "funding_regime": getattr(funding, "regime", "calm") or "calm",
    }


def create_risk_judge(
    quick_llm=None, deep_llm=None, cache_path: str | None = None,
):
    """Phase 2: deterministic 3 lens + severity gate.

    quick_llm/deep_llm은 backward-compat 시그니처 (Phase 2 미사용).
    Phase 3에서 lens evidence narrative 보강 시 quick_llm 활용 가능.
    """
    def node(state):
        as_of_str = state.get("as_of_date")
        as_of = (
            date.fromisoformat(as_of_str)
            if isinstance(as_of_str, str) else None
        )

        weight_vector_1 = state.get("weight_vector")
        candidate_set = state.get("candidate_set")
        bucket_target = state.get("bucket_target")
        risk_report = state.get("risk_report")
        macro_report = state.get("macro_report")
        research_decision = state.get("research_decision")
        technical_report = state.get("technical_report")

        # Input 검증
        if weight_vector_1 is None or candidate_set is None or bucket_target is None:
            overlay = RiskOverlay.no_concerns(as_of_date=as_of)
            return {
                "risk_overlay": overlay,
                "risk_debate_summary": (
                    "## Risk Overlay\nStage 3 입력 부재 — skip\n"
                ),
            }

        # 1. returns matrix (Stage 3 캐시 재사용 ParquetCache)
        try:
            tickers = [
                t for ts in candidate_set.bucket_to_tickers.values() for t in ts
            ]
            start = as_of - timedelta(days=365 * 3) if as_of else None
            returns = (
                fetch_returns_matrix(
                    tickers, start, as_of, cache_path=cache_path,
                ) if as_of else None
            )
        except Exception:
            returns = None

        if returns is None or returns.empty:
            overlay = RiskOverlay.no_concerns(as_of_date=as_of)
            return {
                "risk_overlay": overlay,
                "risk_debate_summary": (
                    "## Risk Overlay\nreturns matrix unavailable — skip\n"
                ),
            }

        # 2. Stage 3.5 numerics
        clusters = (
            getattr(technical_report, "correlation_clusters", None) or []
        )
        numerics = compute_portfolio_numerics(
            weight_vector_1, returns, clusters=clusters,
        )

        # 3. Stage 1 정량 신호 추출
        risk_signals = _extract_risk_signals(risk_report)
        regime_quadrant = (
            getattr(macro_report.regime, "quadrant", None)
            if macro_report and getattr(macro_report, "regime", None) else None
        )

        # 4. 3 lens 호출
        tail_concern = run_tail_risk_lens(
            numerics,
            systemic_score=risk_signals["systemic_score"],
            vix_term_regime=risk_signals["vix_term_regime"],
            funding_regime=risk_signals["funding_regime"],
        )
        conc_concern = run_concentration_lens(numerics, weight_vector_1)
        macro_concern = run_macro_conditional_lens(
            weight_vector_1, candidate_set,
            research_decision=research_decision,
            systemic_score=risk_signals["systemic_score"],
            regime_quadrant=regime_quadrant,
        )

        concerns = [tail_concern, conc_concern, macro_concern]

        # 5. severity-gated 합의
        overlay = aggregate_lens_concerns(concerns, as_of_date=as_of)

        # 6. overlay 적용 (empty면 1차 그대로) + outcome 기록 (Task 4)
        weight_vector_2, outcome = apply_risk_overlay(
            weight_vector_1, overlay, candidate_set, returns, bucket_target,
            method=weight_vector_1.method, clusters=clusters,
        )
        overlay = overlay.model_copy(update={"overlay_apply_outcome": outcome})

        # Summary
        lens_str = "\n".join(
            f"  {c.lens}: {c.level} — {c.evidence[:120]}"
            for c in concerns
        )
        weight_changed = weight_vector_2.weights != weight_vector_1.weights
        summary = (
            f"## Risk Overlay\n"
            f"Lens decisions:\n{lens_str}\n"
            f"Severity: {overlay.severity_decision}\n"
            f"Strength applied: {overlay.strength_applied:.2f}\n"
            f"multiplier={overlay.risk_asset_multiplier:.2f}, "
            f"ceilings={len(overlay.weight_ceilings)}, "
            f"floors={len(overlay.tail_hedge_floor)}\n"
            f"Weight vector "
            f"{'updated by 2nd allocator' if weight_changed else 'unchanged'}.\n"
        )[:2000]

        # 7. telemetry — 누적 stats jsonl 한 줄 append
        try:
            record_overlay_outcome(
                date=as_of_str or "unknown",
                outcome=overlay.overlay_apply_outcome,
                lens_levels={c.lens: c.level for c in concerns},
                strength=overlay.strength_applied,
                multiplier=overlay.risk_asset_multiplier,
            )
        except Exception:
            # telemetry 실패는 파이프라인 안 막음
            logger.warning(
                "overlay_outcomes.jsonl write failed", exc_info=True,
            )

        return {
            "weight_vector": weight_vector_2,
            "risk_overlay": overlay,
            "portfolio_numerics": numerics,
            "risk_debate_summary": summary,
        }

    return node
