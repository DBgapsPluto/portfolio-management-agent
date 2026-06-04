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


def test_empty_cache_does_not_block_live_refetch(tmp_path):
    """빈 결과가 캐시된 뒤(일시적 fetch 실패) 같은 as_of 재호출 시 live 를 다시 시도.

    회귀: 깨진 pykrx 가 빈 credit_balance 를 as_of 캐시(`{}`)에 저장 → KOFIA 연결
    후에도 그 빈 캐시가 fetch 를 영구 차단했다 (kr_margin sentinel 고착).
    빈 dict 는 캐시 히트가 아니라 miss 로 취급해야 한다.
    """
    call_count = {"n": 0}

    def fetcher() -> pd.Series:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return pd.Series(dtype=float, name="x")  # 1차: 빈 (일시 실패)
        return pd.Series(
            [42.0], index=pd.to_datetime(["2026-05-16"]), name="x",
        )

    s1 = fetch_series_with_cache(
        fetcher, namespace="test", cache_key="x",
        as_of=date(2026, 5, 16), cache_dir=tmp_path,
    )
    assert s1.empty

    s2 = fetch_series_with_cache(
        fetcher, namespace="test", cache_key="x",
        as_of=date(2026, 5, 16), cache_dir=tmp_path,
    )
    assert call_count["n"] == 2  # 빈 캐시 무시 → live 재호출
    assert not s2.empty
    assert s2.iloc[-1] == 42.0


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


def test_frame_dict_roundtrip():
    from tradingagents.dataflows.series_cache import dict_to_frame, frame_to_dict
    idx = pd.to_datetime(["2026-05-15", "2026-05-16"])
    df = pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 4.0]}, index=idx)
    out = frame_to_dict(df)
    assert set(out.keys()) == {"A", "B"}
    rebuilt = dict_to_frame(out)
    assert list(rebuilt.columns) == ["A", "B"]
    assert (rebuilt["A"].values == df["A"].values).all()


def test_frame_dict_empty():
    from tradingagents.dataflows.series_cache import dict_to_frame
    df = dict_to_frame({})
    assert df.empty


def test_fetch_frame_with_cache(tmp_path):
    from tradingagents.dataflows.series_cache import fetch_frame_with_cache

    call_count = {"n": 0}

    def fetcher() -> pd.DataFrame:
        call_count["n"] += 1
        idx = pd.to_datetime(["2026-05-15", "2026-05-16"])
        return pd.DataFrame({"X": [1.0, 2.0], "Y": [3.0, 4.0]}, index=idx)

    f1 = fetch_frame_with_cache(
        fetcher, namespace="frame_test", cache_key="t",
        as_of=date(2026, 5, 16), cache_dir=tmp_path,
    )
    f2 = fetch_frame_with_cache(
        fetcher, namespace="frame_test", cache_key="t",
        as_of=date(2026, 5, 16), cache_dir=tmp_path,
    )
    assert call_count["n"] == 1
    assert list(f1.columns) == ["X", "Y"]
    assert (f1 == f2).all().all()


def test_empty_frame_cache_does_not_block_live_refetch(tmp_path):
    """frame 버전도 빈 결과를 캐시 히트로 취급하지 않고 live 재시도 (series 와 동일)."""
    from tradingagents.dataflows.series_cache import fetch_frame_with_cache

    call_count = {"n": 0}

    def fetcher() -> pd.DataFrame:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return pd.DataFrame()  # 1차: 빈 (일시 실패)
        return pd.DataFrame({"X": [1.0]}, index=pd.to_datetime(["2026-05-16"]))

    f1 = fetch_frame_with_cache(
        fetcher, namespace="frame_test", cache_key="empty",
        as_of=date(2026, 5, 16), cache_dir=tmp_path,
    )
    assert f1.empty

    f2 = fetch_frame_with_cache(
        fetcher, namespace="frame_test", cache_key="empty",
        as_of=date(2026, 5, 16), cache_dir=tmp_path,
    )
    assert call_count["n"] == 2  # 빈 캐시 무시 → live 재호출
    assert not f2.empty


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
