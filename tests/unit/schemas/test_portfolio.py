"""Task 10: BucketTarget schema 8-bucket support verification."""
import pytest
from pydantic import ValidationError
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.research.factor_to_bucket import BUCKETS, INITIAL_BASELINE


_8_BUCKET_WEIGHTS = {
    "kr_equity":             0.15,
    "global_equity":         0.20,
    "precious_metals":       0.08,
    "cyclical_commodity_fx": 0.14,
    "kr_bond":               0.15,
    "credit":                0.05,
    "global_duration":       0.13,
    "cash_mmf":              0.10,
}


def test_bucket_target_accepts_8_buckets():
    """Tier 1: BucketTarget supports arbitrary 8-bucket weights."""
    target = BucketTarget(weights=_8_BUCKET_WEIGHTS, rationale="8-bucket test")
    assert set(target.keys()) == set(_8_BUCKET_WEIGHTS.keys())
    assert abs(target.total - 1.0) < 1e-6


def test_bucket_target_8_bucket_values_accessible():
    """All 8 bucket values accessible via dict-like interface."""
    target = BucketTarget(weights=_8_BUCKET_WEIGHTS, rationale="test")
    assert target["kr_equity"] == pytest.approx(0.15)
    assert target["global_equity"] == pytest.approx(0.20)
    assert target["precious_metals"] == pytest.approx(0.08)
    assert target["cyclical_commodity_fx"] == pytest.approx(0.14)
    assert target["kr_bond"] == pytest.approx(0.15)
    assert target["credit"] == pytest.approx(0.05)
    assert target["global_duration"] == pytest.approx(0.13)
    assert target["cash_mmf"] == pytest.approx(0.10)


def test_bucket_target_risk_asset_weight_8buckets():
    """risk_asset_weight counts 4 risk buckets: kr_equity, global_equity,
    precious_metals, cyclical_commodity_fx."""
    target = BucketTarget(weights=_8_BUCKET_WEIGHTS, rationale="test")
    expected_risk = 0.15 + 0.20 + 0.08 + 0.14  # = 0.57
    assert abs(target.risk_asset_weight - expected_risk) < 1e-6


def test_bucket_target_rejects_non_unit_sum():
    """Sum ≠ 1.0 → ValidationError."""
    bad = dict(_8_BUCKET_WEIGHTS)
    bad["kr_equity"] = 0.50  # sum = 1.35
    with pytest.raises(ValidationError):
        BucketTarget(weights=bad, rationale="bad")


def test_bucket_target_bond_tips_share_default():
    """bond_tips_share defaults to 0.0."""
    target = BucketTarget(weights=_8_BUCKET_WEIGHTS, rationale="test")
    assert target.bond_tips_share == 0.0


def test_bucket_target_bond_tips_share_custom():
    """bond_tips_share can be set explicitly."""
    target = BucketTarget(
        weights=_8_BUCKET_WEIGHTS, rationale="test", bond_tips_share=0.40,
    )
    assert target.bond_tips_share == pytest.approx(0.40)


def test_bucket_target_dict_iteration():
    """Iteration over BucketTarget yields all 8 bucket keys."""
    target = BucketTarget(weights=_8_BUCKET_WEIGHTS, rationale="test")
    assert list(target.keys()) == list(_8_BUCKET_WEIGHTS.keys())
    assert list(target.values()) == [_8_BUCKET_WEIGHTS[k] for k in _8_BUCKET_WEIGHTS]


def test_bucket_target_items():
    """items() returns (key, weight) pairs."""
    target = BucketTarget(weights=_8_BUCKET_WEIGHTS, rationale="test")
    for b, w in target.items():
        assert b in _8_BUCKET_WEIGHTS
        assert w == pytest.approx(_8_BUCKET_WEIGHTS[b])


def test_bucket_target_get_with_default():
    """get() returns default for missing keys."""
    target = BucketTarget(weights=_8_BUCKET_WEIGHTS, rationale="test")
    assert target.get("kr_equity") == pytest.approx(0.15)
    assert target.get("nonexistent_bucket", 0.0) == 0.0


def test_bucket_target_from_initial_baseline():
    """BucketTarget constructed from factor_to_bucket.INITIAL_BASELINE passes validation."""
    target = BucketTarget(
        weights=dict(INITIAL_BASELINE), rationale="baseline test",
    )
    assert set(target.keys()) == set(BUCKETS)
    assert abs(target.total - 1.0) < 1e-6


def test_bucket_target_mandate_cap():
    """risk_asset_weight ≤ 0.70 for INITIAL_BASELINE."""
    target = BucketTarget(
        weights=dict(INITIAL_BASELINE), rationale="mandate check",
    )
    assert target.risk_asset_weight <= 0.70 + 1e-6
