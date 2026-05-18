"""Stage 4 Risk Judge — Phase 1 placeholder.

Phase 1 (현재 commit): no-op judge — RiskOverlay.no_concerns() 항상 반환.
  → graph 인프라 (stub 교체 + apply_risk_overlay wiring) 검증용.

Phase 2 (다음 commit): 3 lens (tail_risk/concentration/macro_conditional) 호출 +
  severity-gated aggregation으로 교체.

WeightAdjustment.delta (LLM이 weight 직접 산출) 폐기. LLM은 *제약*만 만들고
Stage 3 optimizer가 풀이 (Stage 1·2·3 정신 일관).
"""
from datetime import date

from tradingagents.agents.allocator.overlay_apply import apply_risk_overlay
from tradingagents.schemas.risk_overlay import RiskOverlay


def create_risk_judge(quick_llm=None, deep_llm=None):
    """Phase 1: LLM 미사용 (always-empty overlay).

    Phase 2에서 quick_llm 인자가 lens debator 3개에 전달됨.
    """
    def node(state):
        as_of_str = state.get("as_of_date")
        as_of = (
            date.fromisoformat(as_of_str)
            if isinstance(as_of_str, str) else None
        )

        # Phase 1 — empty overlay
        overlay = RiskOverlay.no_concerns(as_of_date=as_of)

        weight_vector_1 = state.get("weight_vector")
        candidate_set = state.get("candidate_set")
        bucket_target = state.get("bucket_target")

        # overlay 비었으면 weight_vector 변경 없음 (인프라 검증만)
        if (
            overlay.is_empty()
            or weight_vector_1 is None
            or candidate_set is None
            or bucket_target is None
        ):
            return {
                "risk_overlay": overlay,
                "risk_debate_summary": (
                    f"## Risk Overlay\n{overlay.severity_decision}\n"
                    f"No weight adjustments applied (Phase 1 placeholder).\n"
                )[:2000],
            }

        # overlay 적용 path (Phase 2 lens가 채워질 때 동작)
        # Phase 1에서는 이 분기 실행 안 됨 (overlay 항상 empty).
        # 인프라 검증 위해 코드 유지.
        try:
            from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
            from datetime import timedelta
            tickers = [
                t for ts in candidate_set.bucket_to_tickers.values() for t in ts
            ]
            start = as_of - timedelta(days=365 * 3) if as_of else None
            returns = fetch_returns_matrix(
                tickers, start, as_of, cache_path=None,
            ) if as_of else None
        except Exception:
            returns = None

        if returns is None or returns.empty:
            return {
                "risk_overlay": overlay,
                "risk_debate_summary": (
                    "## Risk Overlay\nreturns matrix unavailable, "
                    "overlay skipped (Stage 3 result kept).\n"
                ),
            }

        weight_vector_2 = apply_risk_overlay(
            weight_vector_1, overlay, candidate_set, returns, bucket_target,
            method=weight_vector_1.method,
        )

        return {
            "weight_vector": weight_vector_2,
            "risk_overlay": overlay,
            "risk_debate_summary": (
                f"## Risk Overlay\n"
                f"Strength applied: {overlay.strength_applied:.2f}\n"
                f"Decision: {overlay.severity_decision}\n"
                f"Weight vector updated by 2nd allocator call.\n"
            )[:2000],
        }

    return node
