from datetime import date, timedelta
from pathlib import Path

import pytest

from tradingagents.dataflows.cache import (
    TieredCache, CacheMiss, FetchFailure,
)


def _ok_fetch(value):
    def f():
        return value
    return f


def _fail_fetch():
    def f():
        raise FetchFailure("upstream down")
    return f


def test_live_success(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    val, staleness = c.fetch_with_fallback(_ok_fetch({"x": 1}), as_of=today)
    assert val == {"x": 1}
    assert staleness == 0


def test_live_fail_d1_hit(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    yesterday = date(2026, 5, 9)
    today = date(2026, 5, 10)
    c.write(yesterday, {"x": "old"})
    val, staleness = c.fetch_with_fallback(_fail_fetch(), as_of=today)
    assert val == {"x": "old"}
    assert staleness == 1


def test_live_fail_no_cache_raises(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    with pytest.raises(CacheMiss):
        c.fetch_with_fallback(_fail_fetch(), as_of=today, max_staleness=7)


def test_live_fail_d8_too_stale(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    eight_days_ago = today - timedelta(days=8)
    c.write(eight_days_ago, {"x": "ancient"})
    with pytest.raises(CacheMiss):
        c.fetch_with_fallback(_fail_fetch(), as_of=today, max_staleness=7)
