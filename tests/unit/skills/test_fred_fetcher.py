"""FRED skill cache key 회귀.

cache_key 가 logical name('china_cli')이면 series 매핑을 바꿔도 옛 series 캐시를
hit 한다 (china_cli: NOSTSAM→AASTSAM 교체 시 실제로 발생). resolved series_id 를
cache_key 로 써서 series 교체 시 캐시가 자동 분리되게 한다.
"""
from datetime import date

import pandas as pd

from tradingagents.skills.macro import fred_fetcher as ff


def test_fred_cache_key_is_resolved_series_id(monkeypatch):
    """fred 캐시 key 가 logical name 이 아니라 resolved series_id 여야 한다."""
    captured = {}

    def fake_cache(_live, *, namespace, cache_key, as_of, max_staleness):
        captured["namespace"] = namespace
        captured["cache_key"] = cache_key
        return _live()

    monkeypatch.setattr(ff, "fetch_series_with_cache", fake_cache)
    monkeypatch.setattr(ff, "fetch_fred_series", lambda *a, **k: pd.Series(dtype=float))

    ff.fetch_fred_series_skill(
        "china_cli", date(2026, 1, 1), date(2026, 1, 2), as_of_date=date(2026, 1, 2),
    )

    assert captured["cache_key"] == "CHNLOLITOAASTSAM"  # logical 'china_cli' 아님


def test_fred_cache_key_passthrough_for_raw_series_id(monkeypatch):
    """logical 매핑에 없는 raw series_id 는 그대로 cache_key 로 쓴다."""
    captured = {}

    def fake_cache(_live, *, namespace, cache_key, as_of, max_staleness):
        captured["cache_key"] = cache_key
        return _live()

    monkeypatch.setattr(ff, "fetch_series_with_cache", fake_cache)
    monkeypatch.setattr(ff, "fetch_fred_series", lambda *a, **k: pd.Series(dtype=float))

    ff.fetch_fred_series_skill(
        "DGS10", date(2026, 1, 1), date(2026, 1, 2), as_of_date=date(2026, 1, 2),
    )

    assert captured["cache_key"] == "DGS10"
