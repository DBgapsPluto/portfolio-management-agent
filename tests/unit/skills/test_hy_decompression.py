from datetime import date
from tradingagents.skills.risk.hy_decompression import compute_hy_decompression


def test_hy_decompression_basic():
    snap = compute_hy_decompression(hy_oas_bps=450.0, ig_oas_bps=120.0, as_of=date(2026, 5, 10))
    assert abs(snap.hy_minus_ig_bps - 330.0) < 1e-6
    assert snap.regime in ("calm", "widening", "stress")
    assert snap.collapsed is False


def test_hy_decompression_300_boundary():
    snap = compute_hy_decompression(hy_oas_bps=420.0, ig_oas_bps=120.0, as_of=date(2026, 5, 10))
    assert snap.hy_minus_ig_bps == 300.0
    assert snap.regime == "widening"  # 경계 300 포함 (schema 일관)


def test_hy_decompression_collapsed_sentinel():
    snap = compute_hy_decompression(hy_oas_bps=200.0, ig_oas_bps=200.0, as_of=date(2026, 5, 10))
    assert snap.hy_minus_ig_bps == 0.0
    assert snap.collapsed is True
