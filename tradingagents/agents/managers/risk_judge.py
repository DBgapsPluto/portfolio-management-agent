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


# Stage 4 audit (2026-05-26, Task 0): Stage 1 sentinel marker.
# risk_report 의 fetch 실패 snapshot 은 staleness_days=99 로 표시됨.
# Stage 1/2/3 audit 의 staleness propagation chain 의 마지막 끊김 보수.
STALENESS_SENTINEL_DAYS_S4: int = 99


def _extract_risk_signals(risk_report) -> dict:
    """Stage 1 risk_report에서 lens가 쓸 정량 신호 추출.

    Stage 4 audit Task 0: staleness 추적 보강. systemic_score / vix_term /
    funding_stress 객체의 staleness_days 도 함께 추출. 셋 다 sentinel(≥99) 이면
    risk_judge 가 lens 호출 skip + empty overlay (Stage 3 가 이미 strict MIN_VAR
    강제했으므로 Stage 4 는 추가 안 함이 보수적).

    risk_report 자체가 None 인 경우도 fully degraded 로 처리.
    """
    if risk_report is None:
        # risk_report 자체 부재 — 기존 default 동작 (안전 기본값으로 lens 호출).
        # Stage 4 audit Task 0 의 'all_degraded' 는 명시적 sentinel snapshot
        # (staleness=99) 검출용으로 한정. risk_report 부재는 다른 시나리오
        # (Stage 1 자체 skip 등) 가능성 있어 lens 호출은 유지.
        return {
            "systemic_score": 5.0,
            "vix_term_regime": "contango",
            "funding_regime": "calm",
            "systemic_staleness": None,
            "vix_term_staleness": None,
            "funding_staleness": None,
            "all_degraded": False,
        }
    systemic = getattr(risk_report, "systemic_score", None)
    vix_term = getattr(risk_report, "vix_term", None)
    funding = getattr(risk_report, "funding_stress", None)

    systemic_stale = getattr(systemic, "staleness_days", None) if systemic else None
    vix_stale = getattr(vix_term, "staleness_days", None) if vix_term else None
    funding_stale = getattr(funding, "staleness_days", None) if funding else None

    def _is_sentinel(s: int | None) -> bool:
        return isinstance(s, int) and s >= STALENESS_SENTINEL_DAYS_S4

    all_degraded = (
        _is_sentinel(systemic_stale)
        and _is_sentinel(vix_stale)
        and _is_sentinel(funding_stale)
    )

    return {
        "systemic_score": float(systemic.score) if systemic else 5.0,
        "vix_term_regime": getattr(vix_term, "regime", "contango") or "contango",
        "funding_regime": getattr(funding, "regime", "calm") or "calm",
        "systemic_staleness": systemic_stale,
        "vix_term_staleness": vix_stale,
        "funding_staleness": funding_stale,
        "all_degraded": all_degraded,
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
        logger.info(
            "risk_judge start: as_of=%s, n_positions=%s",
            as_of,
            len(weight_vector_1.weights) if weight_vector_1 else 0,
        )

        # Stage 4 audit Task 1: attribution dict — Stage 6 narrative 가시화.
        # Stage 3 의 allocation_attribution 옆에 별도 risk_judge_attribution 으로
        # 산출 (state 키 충돌 회피).
        rj_attribution: dict = {
            "as_of": as_of_str,
            "input_present": {
                "weight_vector": weight_vector_1 is not None,
                "candidate_set": candidate_set is not None,
                "bucket_target": bucket_target is not None,
                "risk_report": risk_report is not None,
                "macro_report": macro_report is not None,
                "research_decision": research_decision is not None,
                "technical_report": technical_report is not None,
            },
        }

        # Input 검증
        if weight_vector_1 is None or candidate_set is None or bucket_target is None:
            logger.warning(
                "risk_judge: Stage 3 입력 부재 (wv=%s, cs=%s, bt=%s) → skip",
                weight_vector_1 is not None,
                candidate_set is not None,
                bucket_target is not None,
            )
            overlay = RiskOverlay.no_concerns(as_of_date=as_of)
            rj_attribution["skipped"] = "stage3_inputs_missing"
            return {
                "risk_overlay": overlay,
                "risk_debate_summary": (
                    "## Risk Overlay\nStage 3 입력 부재 — skip\n"
                ),
                "risk_judge_attribution": rj_attribution,
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
            logger.warning("risk_judge: returns matrix unavailable → skip")
            overlay = RiskOverlay.no_concerns(as_of_date=as_of)
            rj_attribution["skipped"] = "returns_matrix_empty"
            return {
                "risk_overlay": overlay,
                "risk_debate_summary": (
                    "## Risk Overlay\nreturns matrix unavailable — skip\n"
                ),
                "risk_judge_attribution": rj_attribution,
            }

        # 2. Stage 3.5 numerics
        clusters = (
            getattr(technical_report, "correlation_clusters", None) or []
        )
        numerics = compute_portfolio_numerics(
            weight_vector_1, returns, clusters=clusters,
        )

        # 3. Stage 1 정량 신호 추출 (staleness 포함 — Stage 4 audit Task 0)
        risk_signals = _extract_risk_signals(risk_report)
        regime_quadrant = (
            getattr(macro_report.regime, "quadrant", None)
            if macro_report and getattr(macro_report, "regime", None) else None
        )

        # Stage 4 audit Task 0: Stage 1 risk_signals 모두 sentinel (≥99) 이면
        # placeholder 값 (systemic=5.0, vix=contango, funding=calm) 으로 lens
        # 호출 시 silent 잘못된 overlay 산출 위험. Stage 3 audit Task 0 이 이미
        # degraded_inputs 시 MIN_VARIANCE 강제했으므로, Stage 4 는 추가 overlay
        # 안 만드는 게 보수적 (empty overlay = Stage 3 결과 보존).
        if risk_signals["all_degraded"]:
            logger.warning(
                "risk_judge: risk_signals 모두 sentinel "
                "(systemic_stale=%s, vix_stale=%s, funding_stale=%s) → "
                "lens 호출 skip + empty overlay (Stage 3 결과 보존)",
                risk_signals["systemic_staleness"],
                risk_signals["vix_term_staleness"],
                risk_signals["funding_staleness"],
            )
            overlay = RiskOverlay.no_concerns(as_of_date=as_of)
            rj_attribution["skipped"] = "risk_signals_degraded"
            rj_attribution["risk_signal_staleness"] = {
                "systemic": risk_signals["systemic_staleness"],
                "vix_term": risk_signals["vix_term_staleness"],
                "funding": risk_signals["funding_staleness"],
            }
            return {
                "weight_vector": weight_vector_1,
                "risk_overlay": overlay,
                "portfolio_numerics": numerics,
                "risk_judge_attribution": rj_attribution,
                "risk_debate_summary": (
                    "## Risk Overlay\n"
                    "**risk_signals_degraded**: Stage 1 risk_report 의 systemic / "
                    "vix_term / funding_stress 모두 sentinel (staleness≥99)\n"
                    "→ lens skip, empty overlay (Stage 3 결과 보존)\n"
                    f"Strength applied: 0.00\n"
                )[:2000],
            }

        # Stage 4 audit Task 1: lens 호출 전 input snapshot.
        rj_attribution["risk_signal_staleness"] = {
            "systemic": risk_signals["systemic_staleness"],
            "vix_term": risk_signals["vix_term_staleness"],
            "funding": risk_signals["funding_staleness"],
        }

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
        for c in concerns:
            logger.info(
                "lens %s → level=%s, evidence: %s",
                c.lens, c.level, c.evidence[:120],
            )

        # 5. severity-gated 합의
        overlay = aggregate_lens_concerns(concerns, as_of_date=as_of)
        logger.info(
            "severity_aggregator: strength=%.2f, multiplier=%.2f, "
            "ceilings=%d, cluster_caps=%d, decision: %s",
            overlay.strength_applied, overlay.risk_asset_multiplier,
            len(overlay.weight_ceilings), len(overlay.cluster_caps),
            overlay.severity_decision[:120],
        )

        # Stage 4 audit Task 1: lens 결과 + aggregate 결과 attribution.
        rj_attribution["lens_concerns"] = [
            {
                "lens": c.lens,
                "level": c.level,
                "evidence": c.evidence[:200],
            }
            for c in concerns
        ]
        rj_attribution["strength_applied"] = overlay.strength_applied
        rj_attribution["severity_decision"] = overlay.severity_decision
        rj_attribution["multiplier"] = overlay.risk_asset_multiplier

        # 6. overlay 적용 (empty면 1차 그대로) + outcome 기록 (Stage 3 Task 4 의
        # overlay attribution 도 함께 채워짐).
        rj_attribution["overlay"] = {}
        weight_vector_2, outcome = apply_risk_overlay(
            weight_vector_1, overlay, candidate_set, returns, bucket_target,
            method=weight_vector_1.method, clusters=clusters,
            attribution=rj_attribution,
        )
        overlay = overlay.model_copy(update={"overlay_apply_outcome": outcome})
        logger.info(
            "risk_judge complete: outcome=%s, weight_changed=%s",
            outcome, weight_vector_2.weights != weight_vector_1.weights,
        )

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
            "risk_judge_attribution": rj_attribution,
            "risk_debate_summary": summary,
        }

    return node
