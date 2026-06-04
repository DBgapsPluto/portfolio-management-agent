"""Deterministic execution-alignment trace for philosophy.md (P2)."""
from __future__ import annotations

from typing import Any

from tradingagents.skills.research.factor_to_bucket import BUCKETS, RISK_BUCKETS


def _pct(w: float) -> str:
    return f"{w * 100:.1f}%"


def _render_covenant_ledger(
    *,
    pure: dict[str, float],
    covenant: dict[str, float],
    feasible: dict[str, float],
    final_realized: dict[str, float],
    tension_pp: float = 5.0,
) -> list[str]:
    """P1+P3: covenant anchor chain vs feasible/final."""
    lines = [
        "",
        "## Covenant Ledger",
        "",
        "| 버킷 | scenario_pure | covenant | feasible | final |",
        "|------|---------------|----------|----------|-------|",
    ]
    tensions: list[str] = []
    for b in BUCKETS:
        feas_b = float(feasible.get(b, 0.0))
        cov_b = float(covenant.get(b, 0.0))
        if abs(feas_b - cov_b) > tension_pp / 100.0:
            tensions.append(
                f"{b}: feasible {_pct(feas_b)} vs covenant {_pct(cov_b)} "
                f"(Δ {(feas_b - cov_b) * 100:+.1f}pp)"
            )
        lines.append(
            f"| {b} | {_pct(float(pure.get(b, 0)))} | {_pct(cov_b)} | "
            f"{_pct(feas_b)} | {_pct(float(final_realized.get(b, 0)))} |"
        )
    if tensions:
        lines.append("")
        lines.append(
            "- narrative tension: " + "; ".join(tensions[:4])
            + (" …" if len(tensions) > 4 else "")
        )
    return lines


def _aggregate_wm_5bucket(w8: dict[str, float]) -> dict[str, float]:
    """8-bucket realized/feasible → WM 5-bucket view."""
    return {
        "kr_equity": float(w8.get("kr_equity", 0.0)),
        "global_equity": float(w8.get("global_equity", 0.0)),
        "fx_commodity": float(w8.get("precious_metals", 0.0))
        + float(w8.get("cyclical_commodity_fx", 0.0)),
        "bond": float(w8.get("kr_bond", 0.0))
        + float(w8.get("credit", 0.0))
        + float(w8.get("global_duration", 0.0)),
        "cash_mmf": float(w8.get("cash_mmf", 0.0)),
    }


def render_pipeline_narrative(state: dict) -> str:
    """Deterministic Stage 1→5 path for philosophy.md (의사결정 경로)."""
    rd = state.get("research_decision")
    ac = getattr(rd, "allocation_contract", None) if rd is not None else None
    attr = state.get("allocation_attribution") or {}
    cfg = (attr.get("config") or {}) if isinstance(attr, dict) else {}
    sync = attr.get("bucket_sync_audit") or {}
    align = attr.get("implementation_alignment") or {}
    qp = attr.get("stage3_mandate_qp") or {}
    method_choice = state.get("method_choice")
    method = (
        method_choice.method.value
        if method_choice is not None and hasattr(method_choice, "method")
        else _resolve_method_label(state)
    )
    dominant = getattr(rd, "dominant_scenario", None) if rd else None
    feasible = dict(ac.feasible_weights) if ac is not None else {}
    feas_risk = sum(float(feasible.get(b, 0)) for b in RISK_BUCKETS)
    realized = align.get("realized_bucket_weights") or {}
    risk_final = sum(float(realized.get(b, 0)) for b in RISK_BUCKETS)
    unalloc = float(
        attr.get("hrp_unallocated_mass") or attr.get("nco_unallocated_mass") or 0.0
    )
    rj = state.get("risk_judge_attribution") or {}
    clip = rj.get("overlay_risk_clip") or {}

    lines = [
        "## 의사결정 경로",
        "",
        "1. **Stage 1 (매크로·리스크)** — 애널리스트 요약으로 레짐·시장 리스크를 진단합니다.",
        "2. **Stage 2 (리서치·계약)** — "
        f"시나리오 `{dominant or '?'}` → factor tilt → "
        "covenant/feasible 버킷(투자 가능 집합)을 확정합니다.",
        f"   - feasible 위험자산 합: {_pct(feas_risk)}",
        "3. **Stage 3 (후보·최적화)** — "
        f"방법 `{method}`; bucket sync "
        f"(lost {sync.get('lost_mass_pp', 0)} pp → R={sync.get('R_buckets', [])}).",
    ]
    if unalloc > 1e-9:
        lines.append(
            f"   - HRP/NCO shortfall: {unalloc * 100:.2f}pp 미배분 "
            "(위험 버킷으로 전역 스케일업 없음)."
        )
    if qp.get("triggered"):
        lines.append(
            f"   - Mandate QP(B): risk "
            f"{float(qp.get('risk_sum_pre', 0)) * 100:.1f}% → "
            f"{float(qp.get('risk_sum_post', 0)) * 100:.1f}% "
            f"(w_ref=feasible)."
        )
    else:
        lines.append(
            f"   - Allocator realized risk (pre-validator): {_pct(risk_final)}"
        )
    lines.extend([
        "4. **Stage 4 (리스크 오버레이)** — "
        + (
            f"overlay clip 적용 (post risk "
            f"{float(clip['risk_sum_post_clip']) * 100:.1f}%)."
            if clip.get("risk_sum_post_clip") is not None
            else "빈 overlay 또는 clip 미발동."
        ),
        "5. **Stage 5 (검증·폴백)** — "
        f"validation_passed={state.get('validation_passed')}, "
        f"fallback_used={state.get('fallback_used', False)}.",
    ])
    if state.get("fallback_used"):
        lines.append(
            "   - contract 모드: 1차 실패 시 allocator 재시도 없이 "
            "min-variance 등 폴백 포트폴리오로 제출."
        )
    return "\n".join(lines)


def _resolve_method_label(state: dict) -> str:
    wv = state.get("weight_vector")
    if wv is not None:
        return wv.method.value
    return str(state.get("method") or "unknown")


def render_execution_trace(state: dict) -> str:
    """Mandatory ## 실행 정합성 section — numbers from pipeline state only."""
    rd = state.get("research_decision")
    ac = getattr(rd, "allocation_contract", None) if rd is not None else None
    bucket = state.get("bucket_target")
    attr = state.get("allocation_attribution") or {}
    cfg = (attr.get("config") or {}) if isinstance(attr, dict) else {}
    sync = attr.get("bucket_sync_audit") or {}
    align = attr.get("implementation_alignment") or {}
    binding = cfg.get("binding_stage2") or (
        dict(ac.binding_stage2) if ac is not None else {}
    )

    prior = dict(ac.prior_weights) if ac is not None else {}
    feasible = dict(ac.feasible_weights) if ac is not None else {}
    stage2 = cfg.get("bucket_target_stage2") or (
        dict(feasible) if feasible else {}
    )
    executed = cfg.get("bucket_target_executed") or dict(
        getattr(bucket, "weights", {}) if bucket is not None else {}
    )
    final_realized = align.get("realized_bucket_weights") or {}
    safety_diag = (
        getattr(rd, "safety_diagnostics", None) or {}
        if rd is not None
        else {}
    )
    pure_anchor = dict(safety_diag.get("anchor_scenario_pure") or {})
    covenant_anchor = dict(
        safety_diag.get("anchor_covenant")
        or safety_diag.get("stage2_anchor_blend")
        or {}
    )

    lines = [
        "## 실행 정합성",
        "",
        "| 버킷 | prior | feasible | executed | final | binding |",
        "|------|-------|----------|----------|-------|---------|",
    ]
    for b in BUCKETS:
        lines.append(
            f"| {b} | {_pct(float(prior.get(b, 0)))} | "
            f"{_pct(float(feasible.get(b, 0)))} | "
            f"{_pct(float(executed.get(b, 0)))} | "
            f"{_pct(float(final_realized.get(b, 0)))} | "
            f"{binding.get(b, '')} |"
        )

    risk_pre = sync.get("risk_sum_pre_clip")
    risk_post = sync.get("risk_sum_post_clip")
    if risk_pre is not None:
        lines.extend([
            "",
            f"- Stage 3 bucket sync: lost {sync.get('lost_mass_pp', 0)} pp → "
            f"R={sync.get('R_buckets', [])}",
            f"- Risk buckets pre/post mandate clip: {risk_pre} / {risk_post}",
            f"- Mandate clip applied: {sync.get('mandate_clip_applied', False)}",
        ])

    lines.extend([
        "",
        f"- validation_passed: {state.get('validation_passed')}",
        f"- fallback_used: {state.get('fallback_used', False)}",
        f"- allocator_retry_skipped: {state.get('allocator_retry_skipped', False)}",
    ])
    if state.get("pipeline_failure"):
        lines.append(f"- pipeline_failure: {state.get('pipeline_failure')}")

    if pure_anchor or covenant_anchor:
        lines.extend(
            _render_covenant_ledger(
                pure=pure_anchor,
                covenant=covenant_anchor,
                feasible=feasible,
                final_realized=final_realized,
            )
        )

    risk_sum = sum(float(final_realized.get(b, 0)) for b in RISK_BUCKETS)
    if final_realized:
        lines.append(
            f"- Allocator realized risk (pre-validator): {risk_sum * 100:.1f}%"
        )
    rj_attr = state.get("risk_judge_attribution") or {}
    clip = rj_attr.get("overlay_risk_clip") or {}
    if clip.get("risk_sum_post_clip") is not None:
        lines.append(
            f"- Post-risk-judge overlay clip risk sum: "
            f"{float(clip['risk_sum_post_clip']) * 100:.1f}%"
        )
    pre_proj = safety_diag.get("pre_projection_risk_asset")
    if pre_proj is not None and not final_realized:
        lines.append(
            f"- Stage 2 pre-projection risk: {float(pre_proj) * 100:.1f}%"
        )

    return "\n".join(lines)


def render_failure_philosophy_stub(state: dict, error_message: str) -> str:
    """Short philosophy when contract/sync fails before weights exist."""
    trace = render_execution_trace(state)
    return (
        f"# DB GAPS 자산배분 — 실행 불가 ({state.get('as_of_date', '?')})\n\n"
        f"파이프라인이 Stage 3 이전에 중단되었습니다.\n\n"
        f"**사유:** {error_message}\n\n"
        f"{trace}\n"
    )
