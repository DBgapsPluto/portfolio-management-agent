"""Cache layer for pandas Series fetched from external APIs (FRED, ECOS, etc.).

Wraps `TieredCache` with Series ⇆ JSON-dict conversion. as_of_date 기준 1일
캐시 키 — 같은 날 재실행은 0 API 호출.

Live fetch 실패 시 staleness window 안에서 과거 캐시로 fallback.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.cache import CacheMiss, TieredCache
from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


def series_to_dict(s: pd.Series) -> dict[str, float]:
    """Series → JSON-safe dict (index ISO string → float). NaN 제외."""
    out: dict[str, float] = {}
    for idx, value in s.items():
        if pd.isna(value):
            continue
        key = pd.Timestamp(idx).isoformat()
        out[key] = float(value)
    return out


def dict_to_series(payload: dict[str, float], name: str) -> pd.Series:
    """Reverse of series_to_dict."""
    if not payload:
        return pd.Series(dtype=float, name=name)
    items = sorted(payload.items())
    times = [pd.Timestamp(k) for k, _ in items]
    values = [float(v) for _, v in items]
    return pd.Series(values, index=times, name=name)


def resolve_cache_dir(subdir: str | None = None) -> Path:
    """Top-level cache dir from config, with optional sub-namespace."""
    base = Path(DEFAULT_CONFIG["data_cache_dir"])
    return base / subdir if subdir else base


def frame_to_dict(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """DataFrame → {col: {iso_date: value}} JSON-safe nested dict."""
    return {str(col): series_to_dict(df[col]) for col in df.columns}


def dict_to_frame(payload: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Reverse of frame_to_dict."""
    if not payload:
        return pd.DataFrame()
    cols = {col: dict_to_series(d, name=col) for col, d in payload.items()}
    return pd.DataFrame(cols).sort_index()


def fetch_series_with_cache(
    fetcher: Callable[[], pd.Series],
    *,
    namespace: str,
    cache_key: str,
    as_of: date,
    max_staleness: int = 7,
    cache_dir: Path | None = None,
) -> pd.Series:
    """Cache-first Series fetcher.

    namespace: "fred", "ecos", etc. (cache_dir 하위 폴더 분리)
    cache_key: 시리즈 식별자 (e.g. series_id). 한 시리즈당 하나의 cache 디렉토리.
    as_of: 캐시 키 날짜 — 같은 as_of는 1회만 fetch.
    max_staleness: live 실패 시 N일 뒤로 walk back.

    On total cache miss + live failure, re-raises the underlying error.
    """
    base = cache_dir or resolve_cache_dir()
    cache = TieredCache(base / namespace, name=cache_key)

    # 1) Cache-first: 같은 as_of payload가 이미 있으면 live 호출 없이 반환.
    #    빈 dict({})는 캐시 히트가 아니라 miss 로 취급 — 일시적 fetch 실패가 빈
    #    결과로 캐시되면 데이터 소스 복구 후에도 영구 차단되기 때문 (kr_margin
    #    sentinel 고착 회귀).
    cached = cache.read(as_of)
    if cached:
        return dict_to_series(cached, name=cache_key)

    # 2) Cache miss → live + fallback chain (TieredCache가 walk-back 처리).
    def _live_to_dict() -> dict[str, float]:
        return series_to_dict(fetcher())

    payload, staleness = cache.fetch_with_fallback(
        _live_to_dict, as_of=as_of, max_staleness=max_staleness,
    )

    if staleness > 0:
        logger.info(
            "series_cache %s/%s: stale fallback (staleness=%dd)",
            namespace, cache_key, staleness,
        )

    return dict_to_series(payload, name=cache_key)


def fetch_frame_with_cache(
    fetcher: Callable[[], pd.DataFrame],
    *,
    namespace: str,
    cache_key: str,
    as_of: date,
    max_staleness: int = 7,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Cache-first DataFrame fetcher. Series 버전과 동일 패턴."""
    base = cache_dir or resolve_cache_dir()
    cache = TieredCache(base / namespace, name=cache_key)

    cached = cache.read(as_of)
    if cached:  # 빈 dict({})는 캐시 miss 로 취급 (series 버전과 동일 — 일시 실패 영구화 방지)
        return dict_to_frame(cached)

    def _live_to_dict() -> dict[str, dict[str, float]]:
        return frame_to_dict(fetcher())

    payload, staleness = cache.fetch_with_fallback(
        _live_to_dict, as_of=as_of, max_staleness=max_staleness,
    )

    if staleness > 0:
        logger.info(
            "frame_cache %s/%s: stale fallback (staleness=%dd)",
            namespace, cache_key, staleness,
        )

    return dict_to_frame(payload)
