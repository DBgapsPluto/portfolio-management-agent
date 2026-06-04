"""bucket_sync — Stage 3 target/executed alignment."""
import pytest

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.bucket_sync import (
    BucketSyncError,
    sync_bucket_target_executed,
)
from tradingagents.skills.research.factor_to_bucket import BUCKETS, INITIAL_BASELINE


def _target(weights: dict[str, float] | None = None) -> BucketTarget:
    w = dict(weights or INITIAL_BASELINE)
    return BucketTarget(weights=w, bond_tips_share=0.2, rationale="test")


def test_spill_to_R_prior_proportional():
    prior = {b: 0.125 for b in BUCKETS}
    prior["cash_mmf"] = 0.15
    prior["kr_equity"] = 0.20
    prior["global_equity"] = 0.10
    total = sum(prior.values())
    prior = {b: prior[b] / total for b in BUCKETS}
    target = _target(prior)
    chosen = {
        b: ([] if b == "cash_mmf" else [f"T_{b}"])
        for b in BUCKETS
    }
    alpha = {
        b: ({} if b == "cash_mmf" else {f"T_{b}": 1.0})
        for b in BUCKETS
    }
    new_target, audit = sync_bucket_target_executed(
        bucket_target=target,
        bucket_chosen=chosen,
        alpha_scores_by_bucket=alpha,
        prior_weights=prior,
        eligible_by_bucket={
            b: ([] if b == "cash_mmf" else [f"T_{b}"])
            for b in BUCKETS
        },
    )
    assert any(d["bucket"] == "cash_mmf" for d in audit["donors"])
    assert new_target.weights["kr_equity"] > prior["kr_equity"]
    assert audit["lost_mass_pp"] == pytest.approx(prior["cash_mmf"] * 100, abs=0.5)
    assert "kr_equity" in audit["R_buckets"]


def test_sync_mandate_clip_when_risk_high():
    """P0-1b: QP mandate clip only when spill pushes risk sum above 70%."""
    prior = {b: 0.05 for b in BUCKETS}
    prior["cash_mmf"] = 0.25
    prior["kr_equity"] = 0.35
    prior["global_equity"] = 0.30
    total = sum(prior.values())
    prior = {b: prior[b] / total for b in BUCKETS}
    target = _target(prior)
    chosen = {
        "cash_mmf": [],
        "kr_equity": ["T_KR"],
        "global_equity": ["T_GL"],
        **{b: [] for b in BUCKETS if b not in ("cash_mmf", "kr_equity", "global_equity")},
    }
    alpha = {
        "cash_mmf": {},
        "kr_equity": {"T_KR": 1.0},
        "global_equity": {"T_GL": 1.0},
        **{b: {} for b in BUCKETS if b not in ("cash_mmf", "kr_equity", "global_equity")},
    }
    new_target, audit = sync_bucket_target_executed(
        bucket_target=target,
        bucket_chosen=chosen,
        alpha_scores_by_bucket=alpha,
        prior_weights=prior,
        eligible_by_bucket={
            "cash_mmf": ["T_CASH"],
            "kr_equity": ["T_KR"],
            "global_equity": ["T_GL"],
            **{b: [] for b in BUCKETS if b not in ("cash_mmf", "kr_equity", "global_equity")},
        },
    )
    assert audit["mandate_clip_applied"] is True
    assert audit["risk_sum_pre_clip"] > 0.70
    assert audit["risk_sum_post_clip"] <= 0.70 + 1e-6
    risk_buckets = ("kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx")
    risk_sum = sum(new_target.weights[b] for b in risk_buckets)
    assert risk_sum <= 0.70 + 1e-6


def test_empty_R_raises_bucket_sync_error():
    prior = {b: 0.125 for b in BUCKETS}
    prior["cash_mmf"] = 0.20
    total = sum(prior.values())
    prior = {b: prior[b] / total for b in BUCKETS}
    target = _target(prior)
    chosen = {b: [] for b in BUCKETS}
    alpha = {b: {} for b in BUCKETS}
    with pytest.raises(BucketSyncError):
        sync_bucket_target_executed(
            bucket_target=target,
            bucket_chosen=chosen,
            alpha_scores_by_bucket=alpha,
            prior_weights=prior,
        )
