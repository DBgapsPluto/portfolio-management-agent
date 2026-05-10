"""D5 — Tiered cache fallback behavior."""
from datetime import date, timedelta

import pytest

from tradingagents.dataflows.cache import CacheMiss, FetchFailure, TieredCache
from tradingagents.schemas.macro import YieldCurveSnapshot


def test_d1_hit_when_live_fails(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    c.write(today - timedelta(days=1), {"data": "yesterday"})

    def fail():
        raise FetchFailure("api down")

    val, staleness = c.fetch_with_fallback(fail, as_of=today)
    assert val == {"data": "yesterday"}
    assert staleness == 1


def test_live_succeeds_returns_zero_staleness(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)

    val, staleness = c.fetch_with_fallback(lambda: {"x": 1}, as_of=today)
    assert val == {"x": 1}
    assert staleness == 0
    assert c.read(today) == {"x": 1}


def test_d7_max_staleness(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    c.write(today - timedelta(days=8), {"data": "ancient"})

    def fail():
        raise FetchFailure("api down")

    with pytest.raises(CacheMiss):
        c.fetch_with_fallback(fail, as_of=today, max_staleness=7)


def test_walks_back_to_first_available(tmp_path):
    """When d-1 is missing but d-3 exists, return d-3 with staleness=3."""
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    c.write(today - timedelta(days=3), {"v": 3})

    val, staleness = c.fetch_with_fallback(
        lambda: (_ for _ in ()).throw(FetchFailure("down")),
        as_of=today,
    )
    assert val == {"v": 3}
    assert staleness == 3


def test_staleness_propagates_to_snapshot():
    """Verify schema staleness flags reflect TieredCache staleness."""
    snap = YieldCurveSnapshot(
        spread_10y_2y_bps=-25.0,
        spread_10y_3m_bps=-30.0,
        inverted_days_count=120,
        percentile_5y=0.05,
        staleness_days=3,
    )
    assert snap.is_stale is True
    assert snap.is_severely_stale is False

    severe = snap.model_copy(update={"staleness_days": 8})
    assert severe.is_stale is True
    assert severe.is_severely_stale is True
