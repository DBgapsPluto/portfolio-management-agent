from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows.cache import CacheMiss
from tradingagents.dataflows.series_cache import (
    dict_to_series, fetch_series_with_cache, series_to_dict,
)


def test_series_dict_roundtrip():
    idx = pd.to_datetime(["2026-05-15", "2026-05-16", "2026-05-17"])
    s = pd.Series([1.5, 2.5, 3.5], index=idx, name="x")
    out = series_to_dict(s)
    assert len(out) == 3
    rebuilt = dict_to_series(out, name="x")
    assert (rebuilt == s).all()
    assert rebuilt.name == "x"


def test_series_to_dict_skips_nan():
    idx = pd.to_datetime(["2026-05-15", "2026-05-16"])
    s = pd.Series([1.0, float("nan")], index=idx)
    out = series_to_dict(s)
    assert len(out) == 1


def test_dict_to_series_handles_empty():
    s = dict_to_series({}, name="empty")
    assert s.empty
    assert s.name == "empty"


def test_cache_writes_on_live_success(tmp_path):
    call_count = {"n": 0}

    def fetcher() -> pd.Series:
        call_count["n"] += 1
        idx = pd.to_datetime(["2026-05-15", "2026-05-16"])
        return pd.Series([10.0, 20.0], index=idx, name="test")

    s1 = fetch_series_with_cache(
        fetcher, namespace="test", cache_key="series_a",
        as_of=date(2026, 5, 16), cache_dir=tmp_path,
    )
    s2 = fetch_series_with_cache(
        fetcher, namespace="test", cache_key="series_a",
        as_of=date(2026, 5, 16), cache_dir=tmp_path,
    )
    # 같은 as_of → 1회만 fetch
    assert call_count["n"] == 1
    assert (s1 == s2).all()


def test_cache_falls_back_on_live_failure(tmp_path):
    """첫 호출 성공 → 캐시 적재. 두 번째 호출 (다른 as_of) live 실패 시 stale fallback."""
    success_series = pd.Series(
        [100.0], index=pd.to_datetime(["2026-05-15"]), name="x",
    )

    def fetcher_success() -> pd.Series:
        return success_series

    def fetcher_fail() -> pd.Series:
        raise ConnectionError("API down")

    # day 1: live OK, cache 적재
    fetch_series_with_cache(
        fetcher_success, namespace="test", cache_key="x",
        as_of=date(2026, 5, 15), cache_dir=tmp_path,
    )

    # day 2: live 실패 → stale fallback (1일 전)
    s = fetch_series_with_cache(
        fetcher_fail, namespace="test", cache_key="x",
        as_of=date(2026, 5, 16), cache_dir=tmp_path,
        max_staleness=7,
    )
    assert (s == success_series).all()


def test_cache_raises_when_live_fails_and_no_cache(tmp_path):
    def fetcher_fail() -> pd.Series:
        raise ConnectionError("API down")

    with pytest.raises(CacheMiss):
        fetch_series_with_cache(
            fetcher_fail, namespace="test", cache_key="empty",
            as_of=date(2026, 5, 15), cache_dir=tmp_path,
        )


def test_cache_directory_layout(tmp_path):
    def fetcher() -> pd.Series:
        return pd.Series(
            [1.0], index=pd.to_datetime(["2026-05-15"]), name="x",
        )

    fetch_series_with_cache(
        fetcher, namespace="fred", cache_key="DGS10",
        as_of=date(2026, 5, 15), cache_dir=tmp_path,
    )

    expected = tmp_path / "fred" / "DGS10" / "2026-05-15.json"
    assert expected.exists()
