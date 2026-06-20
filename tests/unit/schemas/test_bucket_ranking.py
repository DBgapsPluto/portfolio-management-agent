import pytest
from pydantic import ValidationError
from tradingagents.schemas.portfolio import BucketTilt, BucketRanking

def test_bucket_ranking_field():
    bt = BucketTilt(bucket_ranking={
        "b3_global_tech": BucketRanking(tier="strong_OW", conviction=0.8, rationale="AI"),
    })
    assert bt.bucket_ranking["b3_global_tech"].tier == "strong_OW"
    assert 0.0 <= bt.bucket_ranking["b3_global_tech"].conviction <= 0.95

def test_bucket_ranking_default_empty():
    bt = BucketTilt()
    assert bt.bucket_ranking == {}            # backward-compat default

def test_conviction_clamped():
    with pytest.raises(ValidationError):
        BucketRanking(tier="OW", conviction=1.5, rationale="x")

def test_tier_must_be_valid_literal():
    with pytest.raises(ValidationError):
        BucketRanking(tier="super_bullish", conviction=0.5, rationale="x")
