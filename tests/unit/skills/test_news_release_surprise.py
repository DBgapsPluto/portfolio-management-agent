from datetime import date, timedelta

import pytest

from tradingagents.schemas.news import ReleaseSurprise
from tradingagents.skills.news.release_surprise import (
    compute_release_surprise_snapshot, normalize_release,
)


def _release(
    indicator: str = "US CPI YoY",
    region: str = "US",
    importance: int = 3,
    forecast: float | None = 3.0,
    actual: float | None = 3.2,
    when: date = date(2026, 5, 18),
) -> ReleaseSurprise:
    return ReleaseSurprise(
        release_date=when, region=region, indicator=indicator,
        importance=importance,
        forecast=forecast, actual=actual, previous=2.8,
        surprise=None, surprise_zscore=None, direction="unknown",
        unit="pct",
    )


def test_normalize_computes_surprise_and_direction():
    raw = _release()
    norm = normalize_release(raw, historical_std=0.15)
    assert norm.surprise == pytest.approx(0.2, abs=0.01)
    assert norm.direction == "positive"
    assert norm.surprise_zscore == pytest.approx(0.2 / 0.15, abs=0.01)


def test_normalize_inline_when_close_to_forecast():
    raw = _release(forecast=3.0, actual=3.02)
    norm = normalize_release(raw, historical_std=0.15)
    assert norm.direction == "inline"


def test_normalize_no_actual_returns_unknown():
    raw = _release(actual=None)
    norm = normalize_release(raw, historical_std=0.15)
    assert norm.surprise is None
    assert norm.direction == "unknown"


def test_snapshot_counts_today_and_5d():
    today = date(2026, 5, 18)
    releases = [
        normalize_release(_release(when=today), 0.15),
        normalize_release(_release(when=today - timedelta(days=2)), 0.15),
        normalize_release(_release(when=today - timedelta(days=10)), 0.15),
    ]
    snap = compute_release_surprise_snapshot(releases, as_of=today)
    assert len(snap.today_releases) == 1
    assert len(snap.last_5d_releases) == 2  # today + 2일 전
    assert snap.high_importance_today == 1


def test_snapshot_hawkish_bias_when_cpi_surprises_up():
    today = date(2026, 5, 18)
    # CPI 강한 +surprise 5번
    releases = [
        normalize_release(
            _release(indicator="US CPI YoY", actual=3.5, forecast=3.0, when=today - timedelta(days=i)),
            historical_std=0.1,
        )
        for i in range(5)
    ]
    snap = compute_release_surprise_snapshot(releases, as_of=today)
    assert snap.bias_30d == "hawkish_surprise"
    assert snap.surprise_index_30d > 0


def test_snapshot_dovish_bias_when_unemployment_spikes():
    today = date(2026, 5, 18)
    # 실업률 surprise + (dovish)
    releases = [
        normalize_release(
            _release(indicator="US Unemployment Rate", actual=4.5, forecast=4.0, when=today - timedelta(days=i)),
            historical_std=0.1,
        )
        for i in range(5)
    ]
    snap = compute_release_surprise_snapshot(releases, as_of=today)
    assert snap.bias_30d == "dovish_surprise"


def test_snapshot_balanced_with_no_releases():
    snap = compute_release_surprise_snapshot([], as_of=date(2026, 5, 18))
    assert snap.bias_30d == "balanced"
    assert snap.surprise_index_30d == 0.0
    assert snap.today_releases == []
