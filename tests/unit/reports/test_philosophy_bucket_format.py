from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.reports.philosophy import format_bucket_target_14


def test_format_lists_nonzero_14_buckets_with_kr_names():
    bt = BucketTarget(weights={"a1_cash": 0.3, "b1_kr_equity": 0.5,
                               "b3_global_tech": 0.2}, rationale="t")
    out = format_bucket_target_14(bt)
    assert "현금성" in out
    assert "한국주식" in out
    assert "30.0%" in out or "30%" in out
    # 0 비중 버킷은 생략
    assert "중국주식" not in out
