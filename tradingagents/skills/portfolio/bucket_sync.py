"""Stage 2/3 bucket target sync — spill unplaced macro mass to executable buckets."""
from __future__ import annotations

import logging
from typing import Any

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS,
    MANDATE_RISK_CAP,
    RISK_BUCKETS,
    project_to_mandate_qp,
)

logger = logging.getLogger(__name__)

NUMERICAL_TOLERANCE: float = 1e-9


class ContractInfeasibleError(RuntimeError):
    """Stage 2 — no bucket can absorb investability overflow."""


class BucketSyncError(RuntimeError):
    """Stage 3 — no recipient bucket R after donor spill."""


def compute_bucket_selectability(
    *,
    eligible_by_bucket: dict[str, list[str]],
    alpha_scores_by_bucket: dict[str, dict[str, float]],
) -> dict[str, int]:
    """Count tickers with alpha > 0 per bucket (matches Stage 3 n_positive_alpha)."""
    out: dict[str, int] = {}
    for bucket in BUCKETS:
        tickers = eligible_by_bucket.get(bucket, [])
        scores = alpha_scores_by_bucket.get(bucket) or {}
        out[bucket] = sum(
            1 for t in tickers if float(scores.get(t, 0.0)) > 0.0
        )
    return out


def _risk_sum(weights: dict[str, float]) -> float:
    return sum(float(weights.get(b, 0.0)) for b in RISK_BUCKETS)


def build_infeasibility_report(
    *,
    error_kind: str,
    as_of_date: str | None,
    prior_weights: dict[str, float],
    feasible_weights: dict[str, float] | None,
    binding_stage2: dict[str, str] | None,
    eligible_by_bucket: dict[str, list[str]] | None,
    n_selectable_by_bucket: dict[str, int] | None,
    bucket_chosen: dict[str, list[str]] | None,
    alpha_scores_by_bucket: dict[str, dict[str, float]] | None,
    donors: list[dict[str, Any]] | None = None,
    lost_mass_pp: float | None = None,
    r_buckets: list[str] | None = None,
    suggested_actions: list[str] | None = None,
) -> dict[str, Any]:
    """Shared structured report for ContractInfeasibleError / BucketSyncError."""
    eligible_by_bucket = eligible_by_bucket or {}
    n_selectable_by_bucket = n_selectable_by_bucket or {}
    bucket_chosen = bucket_chosen or {}
    alpha_scores_by_bucket = alpha_scores_by_bucket or {}
    binding_stage2 = binding_stage2 or {}

    rows: list[dict[str, Any]] = []
    if donors:
        rows = list(donors)
    else:
        for bucket in BUCKETS:
            chosen = bucket_chosen.get(bucket, [])
            n_elig = len(eligible_by_bucket.get(bucket, []))
            n_sel = n_selectable_by_bucket.get(
                bucket,
                sum(
                    1 for t in chosen
                    if float((alpha_scores_by_bucket.get(bucket) or {}).get(t, 0.0)) > 0
                ),
            )
            target_pp = float((feasible_weights or prior_weights).get(bucket, 0.0)) * 100
            rows.append({
                "bucket": bucket,
                "target_pp": round(target_pp, 2),
                "n_chosen": len(chosen),
                "n_eligible": n_elig,
                "n_selectable": n_sel,
                "binding_stage2": binding_stage2.get(bucket, ""),
                "in_R": (
                    len(chosen) > 0 and n_sel > 0
                    if r_buckets is not None
                    else None
                ),
            })

    return {
        "error_kind": error_kind,
        "as_of_date": as_of_date,
        "summary": _format_user_message(
            error_kind=error_kind,
            lost_mass_pp=lost_mass_pp,
            r_buckets=r_buckets,
        ),
        "donors": rows,
        "lost_mass_pp": lost_mass_pp,
        "R_buckets": r_buckets or [],
        "criteria_note": (
            "Stage 2 investability uses n_selectable (alpha>0). "
            "Stage 3 selection uses the same rule for n_max and chosen ETFs."
        ),
        "suggested_actions": suggested_actions or [
            "Check technical_report.factor_panel and as_of date.",
            "Review factor_scores / dominant_scenario for the run.",
            "Inspect binding_stage2 and allocation_attribution.json.",
        ],
    }


def _format_user_message(
    *,
    error_kind: str,
    lost_mass_pp: float | None,
    r_buckets: list[str] | None,
) -> str:
    if error_kind == "contract_infeasible":
        return (
            "Allocation contract could not place investability overflow: "
            "no bucket has selectable ETFs (alpha > 0)."
        )
    if error_kind == "bucket_sync_empty_R":
        return (
            "Portfolio allocation stopped: macro target weight remains in buckets "
            "with zero chosen ETFs, and no other bucket can absorb the mass "
            f"({lost_mass_pp or 0:.1f} pp unplaced)."
        )
    return f"Allocation infeasible ({error_kind})."


def format_infeasibility_message(report: dict[str, Any]) -> str:
    """Plain-text message for logs / CLI."""
    lines = [
        report.get("summary", "Allocation infeasible."),
        f"as_of: {report.get('as_of_date', '?')}",
        "",
        "Bucket | target% | chosen | n_eligible | n_selectable | binding",
    ]
    for row in report.get("donors") or []:
        lines.append(
            f"{row.get('bucket')} | {row.get('target_pp')} | "
            f"{row.get('n_chosen', '-')} | {row.get('n_eligible')} | "
            f"{row.get('n_selectable')} | {row.get('binding_stage2', '')}"
        )
    if report.get("R_buckets") is not None:
        lines.append("")
        lines.append(f"Recipient buckets R: {report.get('R_buckets')}")
    lines.append("")
    lines.append("Suggested actions:")
    for action in report.get("suggested_actions") or []:
        lines.append(f"  - {action}")
    return "\n".join(lines)


def sync_bucket_target_executed(
    *,
    bucket_target: BucketTarget,
    bucket_chosen: dict[str, list[str]],
    alpha_scores_by_bucket: dict[str, dict[str, float]],
    prior_weights: dict[str, float],
    binding_stage2: dict[str, str] | None = None,
    eligible_by_bucket: dict[str, list[str]] | None = None,
    as_of_date: str | None = None,
) -> tuple[BucketTarget, dict[str, Any]]:
    """P0-1: spill donor bucket mass to R (chosen ∧ n_selectable>0), prior-proportional."""
    executed = {b: float(bucket_target.weights.get(b, 0.0)) for b in BUCKETS}
    n_selectable = compute_bucket_selectability(
        eligible_by_bucket=eligible_by_bucket or {},
        alpha_scores_by_bucket=alpha_scores_by_bucket,
    )

    donors: list[dict[str, Any]] = []
    lost = 0.0
    for bucket in BUCKETS:
        target_b = executed.get(bucket, 0.0)
        chosen = bucket_chosen.get(bucket, [])
        n_sel = n_selectable.get(bucket, 0)
        if target_b > NUMERICAL_TOLERANCE and len(chosen) == 0:
            donors.append({
                "bucket": bucket,
                "target_pp": round(target_b * 100, 2),
                "n_chosen": 0,
                "n_eligible": len((eligible_by_bucket or {}).get(bucket, [])),
                "n_selectable": n_sel,
                "binding_stage2": (binding_stage2 or {}).get(bucket, ""),
            })
            lost += target_b
            executed[bucket] = 0.0

    r_buckets = [
        b for b in BUCKETS
        if len(bucket_chosen.get(b, [])) > 0 and n_selectable.get(b, 0) > 0
    ]

    audit: dict[str, Any] = {
        "donors": donors,
        "lost_mass_pp": round(lost * 100, 4),
        "R_buckets": list(r_buckets),
        "mandate_clip_applied": False,
    }

    if lost > NUMERICAL_TOLERANCE and not r_buckets:
        report = build_infeasibility_report(
            error_kind="bucket_sync_empty_R",
            as_of_date=as_of_date,
            prior_weights=prior_weights,
            feasible_weights=executed,
            binding_stage2=binding_stage2,
            eligible_by_bucket=eligible_by_bucket,
            n_selectable_by_bucket=n_selectable,
            bucket_chosen=bucket_chosen,
            alpha_scores_by_bucket=alpha_scores_by_bucket,
            donors=donors,
            lost_mass_pp=audit["lost_mass_pp"],
            r_buckets=[],
        )
        msg = format_infeasibility_message(report)
        logger.error(msg)
        raise BucketSyncError(msg) from None

    if lost > NUMERICAL_TOLERANCE and r_buckets:
        denom = sum(float(prior_weights.get(b, 0.0)) for b in r_buckets)
        recipients_audit = []
        for b in r_buckets:
            share = (
                float(prior_weights.get(b, 0.0)) / denom
                if denom > NUMERICAL_TOLERANCE
                else 1.0 / len(r_buckets)
            )
            delta = lost * share
            executed[b] += delta
            recipients_audit.append({
                "bucket": b,
                "received_pp": round(delta * 100, 2),
                "prior_share": round(share, 4),
            })
        audit["recipients"] = recipients_audit

    risk_pre = _risk_sum(executed)
    audit["risk_sum_pre_clip"] = round(risk_pre, 4)
    if risk_pre > MANDATE_RISK_CAP + NUMERICAL_TOLERANCE:
        keys_present = {b: executed[b] for b in BUCKETS}
        executed = project_to_mandate_qp(keys_present)
        audit["mandate_clip_applied"] = True
        audit["risk_sum_post_clip"] = round(_risk_sum(executed), 4)
    else:
        audit["risk_sum_post_clip"] = audit["risk_sum_pre_clip"]

    total = sum(executed.values())
    if abs(total - 1.0) > 1e-5:
        executed = {b: executed[b] / total for b in BUCKETS}

    new_target = BucketTarget(
        weights=executed,
        bond_tips_share=bucket_target.bond_tips_share,
        rationale=bucket_target.rationale,
    )
    return new_target, audit
