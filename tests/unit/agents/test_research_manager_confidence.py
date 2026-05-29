"""Tests for _apply_confidence_to_bucket — 8-bucket confidence redistribution.

Verifies:
  - All 4 risk buckets are scaled (not just 2).
  - diff is redistributed proportionally across ALL safe buckets (kr_bond, credit,
    global_duration, cash_mmf), not only cash_mmf.
  - No ghost keys ('bond', 'fx_commodity') written.
  - Sum preserved (=1.0) after redistribution.
  - Neutral confidence leaves bucket unchanged.

confidence → multiplier mapping (from research_manager constants):
  confidence >= 0.8  → RISK_MULT_HIGH_CONF = 1.05  (risk-on)
  confidence < 0.5   → RISK_MULT_LOW_CONF  = 0.92  (risk-off)
  otherwise          → RISK_MULT_NEUTRAL   = 1.0   (unchanged)
"""
import pytest
from tradingagents.agents.managers.research_manager import _apply_confidence_to_bucket


def _baseline_8bucket():
    return {
        "kr_equity": 0.15, "global_equity": 0.20, "precious_metals": 0.08,
        "cyclical_commodity_fx": 0.14, "kr_bond": 0.15, "credit": 0.05,
        "global_duration": 0.13, "cash_mmf": 0.10,
    }


def test_confidence_scales_all_4_risk_buckets():
    """Low-confidence multiplier (<1) shrinks ALL 4 risk buckets, not just 2."""
    bucket = _baseline_8bucket()
    # confidence=0.1 < 0.5 → mult=0.92 (<1), all risk buckets shrink
    new_bucket, mult = _apply_confidence_to_bucket(bucket, confidence=0.1)
    assert abs(mult - 0.92) < 1e-9, f"expected mult=0.92, got {mult}"
    for b in ("kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx"):
        assert new_bucket[b] < bucket[b], f"{b} not shrunk by low-confidence multiplier"
    # No ghost keys from old 5-bucket schema
    assert "bond" not in new_bucket, "ghost key 'bond' must not be written"
    assert "fx_commodity" not in new_bucket, "ghost key 'fx_commodity' must not be written"
    # Sum preserved
    assert abs(sum(new_bucket.values()) - 1.0) < 1e-9, f"sum={sum(new_bucket.values())} != 1.0"


def test_confidence_redistributes_to_all_safe_buckets():
    """diff redistributed across all 4 safe buckets proportionally, not just cash_mmf."""
    bucket = _baseline_8bucket()
    # Low confidence → risk shrinks → diff < 0 → safe buckets grow
    new_bucket, mult = _apply_confidence_to_bucket(bucket, confidence=0.1)
    assert abs(mult - 0.92) < 1e-9
    # At least one of the non-cash_mmf safe buckets must have changed
    safe_changed = [
        b for b in ("kr_bond", "credit", "global_duration")
        if abs(new_bucket[b] - bucket[b]) > 1e-12
    ]
    assert len(safe_changed) > 0, (
        "kr_bond/credit/global_duration must absorb diff — "
        "not allowed to dump it all into cash_mmf"
    )


def test_confidence_high_scales_risk_buckets_up():
    """High-confidence multiplier (>1) grows all 4 risk buckets."""
    bucket = _baseline_8bucket()
    # confidence=0.9 >= 0.8 → mult=1.05 (>1), risk buckets grow
    new_bucket, mult = _apply_confidence_to_bucket(bucket, confidence=0.9)
    assert abs(mult - 1.05) < 1e-9, f"expected mult=1.05, got {mult}"
    for b in ("kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx"):
        assert new_bucket[b] > bucket[b], f"{b} not grown by high-confidence multiplier"
    # Sum preserved
    assert abs(sum(new_bucket.values()) - 1.0) < 1e-9


def test_confidence_neutral_returns_unchanged():
    """Neutral confidence (0.5 ≤ conf < 0.8) returns original bucket unchanged."""
    bucket = _baseline_8bucket()
    # confidence=0.6 → neutral zone → mult=1.0 → early return, bucket unchanged
    new_bucket, mult = _apply_confidence_to_bucket(bucket, confidence=0.6)
    assert abs(mult - 1.0) < 1e-9
    assert new_bucket == bucket


def test_confidence_none_returns_unchanged():
    """None confidence → neutral multiplier → bucket unchanged."""
    bucket = _baseline_8bucket()
    new_bucket, mult = _apply_confidence_to_bucket(bucket, confidence=None)
    assert abs(mult - 1.0) < 1e-9
    assert new_bucket == bucket


def test_sum_preserved_after_low_confidence():
    """Verify the full redistribution keeps sum=1.0 exactly."""
    bucket = _baseline_8bucket()
    new_bucket, _ = _apply_confidence_to_bucket(bucket, confidence=0.1)
    total = sum(new_bucket.values())
    assert abs(total - 1.0) < 1e-9, f"sum={total}"


def test_sum_preserved_after_high_confidence():
    """Verify sum=1.0 holds after risk-on scaling too."""
    bucket = _baseline_8bucket()
    new_bucket, _ = _apply_confidence_to_bucket(bucket, confidence=0.9)
    total = sum(new_bucket.values())
    assert abs(total - 1.0) < 1e-9, f"sum={total}"
