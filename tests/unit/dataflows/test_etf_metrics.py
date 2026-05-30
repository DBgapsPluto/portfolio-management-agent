"""etf_metrics 단위 테스트."""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.etf_metrics import (
    ETFDailyMetrics,
    _parse_krx_record,
    compute_premium_discount_median,
    compute_tracking_error_12m,
    compute_volume_per_aum_median,
    fetch_etf_metrics_window,
)


def _fake_krx_record(ticker: str, basDd: date, nav: float = 45000.0,
                     market_price: float = 45100.0, tracking_rate: float = 99.85) -> dict:
    return {
        "ISU_SRT_CD": ticker,
        "BAS_DD": basDd.strftime("%Y%m%d"),
        "NAV": str(nav),
        "TDD_CLSPRC": str(market_price),
        "ACC_TRDVOL": "1234567",
        "ACC_TRDVAL": str(int(market_price * 1234567)),
        "MKTCAP": "16480300000000",
        "TRC_RT": str(tracking_rate),
    }


def _build_synthetic_metrics_df(
    ticker: str, start: date, n_days: int = 100,
    market_price_base: float = 45000.0, vol: float = 0.01, seed: int = 0,
) -> pd.DataFrame:
    """ticker × date multi-index DataFrame 합성 (테스트용)."""
    rng = np.random.default_rng(seed)
    dates = [start + timedelta(days=i) for i in range(n_days)]
    rows = []
    price = market_price_base
    nav = market_price_base * 1.0
    for d in dates:
        price *= 1 + rng.normal(0, vol)
        nav *= 1 + rng.normal(0, vol * 0.95)
        premium = price / nav - 1
        rows.append({
            "ticker": ticker, "trade_date": d,
            "nav": nav, "market_price": price,
            "premium_discount": premium,
            "volume": int(rng.integers(100000, 5000000)),
            "trade_value_krw": float(price * rng.integers(100000, 5000000)),
            "aum_krw": 16_000_000_000_000.0,
            "tracking_rate": 99.5 + rng.normal(0, 0.3),
        })
    return pd.DataFrame(rows).set_index(["ticker", "trade_date"])


def test_parse_krx_record_basic():
    rec = _fake_krx_record("069500", date(2026, 5, 28))
    parsed = _parse_krx_record(rec, date(2026, 5, 28))
    assert parsed is not None
    assert parsed.ticker == "069500"
    assert parsed.trade_date == date(2026, 5, 28)
    assert parsed.nav == 45000.0
    assert parsed.market_price == 45100.0
    assert parsed.tracking_rate == pytest.approx(99.85, abs=1e-3)
    # premium_discount = 45100/45000 - 1
    assert parsed.premium_discount == pytest.approx(45100/45000 - 1, abs=1e-6)


def test_parse_krx_record_missing_nav_returns_none():
    """NAV 누락 (필수 필드) → None."""
    rec = _fake_krx_record("069500", date(2026, 5, 28))
    del rec["NAV"]
    parsed = _parse_krx_record(rec, date(2026, 5, 28))
    assert parsed is None


def test_parse_krx_record_missing_tracking_rate_ok():
    """tracking_rate 누락 → tracking_rate=None 으로 정상 생성."""
    rec = _fake_krx_record("069500", date(2026, 5, 28))
    del rec["TRC_RT"]
    parsed = _parse_krx_record(rec, date(2026, 5, 28))
    assert parsed is not None
    assert parsed.tracking_rate is None


def test_fetch_etf_metrics_window_returns_multi_index_df(monkeypatch, tmp_path):
    """fetch 결과 ticker × date multi-index DataFrame."""
    def fake_fetch(basDd, ticker=None):
        return [
            _fake_krx_record("069500", basDd),
            _fake_krx_record("360750", basDd),
        ]
    monkeypatch.setattr(
        "tradingagents.dataflows.etf_metrics.fetch_etf_daily_detail",
        fake_fetch,
    )
    start = date(2026, 5, 25)  # Mon
    end = date(2026, 5, 28)    # Thu (4 business days)
    df = fetch_etf_metrics_window(
        ["069500", "360750"], start, end, cache_path=tmp_path,
    )
    assert isinstance(df.index, pd.MultiIndex)
    assert df.index.names == ["ticker", "trade_date"]
    assert {"nav", "market_price", "premium_discount", "tracking_rate"} <= set(df.columns)
    # 2 tickers × ~4 business days = ~8 rows
    assert len(df) >= 6


def test_fetch_etf_metrics_window_uses_cache(monkeypatch, tmp_path):
    """캐시된 날짜는 재호출 안 함."""
    call_count = {"n": 0}
    def fake_fetch(basDd, ticker=None):
        call_count["n"] += 1
        return [_fake_krx_record("069500", basDd)]
    monkeypatch.setattr(
        "tradingagents.dataflows.etf_metrics.fetch_etf_daily_detail",
        fake_fetch,
    )
    start, end = date(2026, 5, 25), date(2026, 5, 26)
    fetch_etf_metrics_window(["069500"], start, end, cache_path=tmp_path)
    first_call_count = call_count["n"]
    # 두 번째 호출은 캐시 활용
    fetch_etf_metrics_window(["069500"], start, end, cache_path=tmp_path)
    assert call_count["n"] == first_call_count, "cache hit 시 추가 fetch 없어야"


def test_fetch_etf_metrics_window_handles_holiday_empty(monkeypatch, tmp_path):
    """공휴일 빈 응답도 정상 처리."""
    def fake_fetch(basDd, ticker=None):
        # 일요일은 빈 응답 (그러나 _business_days 가 어차피 skip)
        return [_fake_krx_record("069500", basDd)]
    monkeypatch.setattr(
        "tradingagents.dataflows.etf_metrics.fetch_etf_daily_detail",
        fake_fetch,
    )
    start = date(2026, 5, 22)  # Fri
    end = date(2026, 5, 26)    # Tue (포함 일요일)
    df = fetch_etf_metrics_window(["069500"], start, end, cache_path=tmp_path)
    # 일요일 row 없어야 (business days only)
    assert (df.index.get_level_values("trade_date") != date(2026, 5, 24)).all()


def test_compute_tracking_error_12m_uses_krx_rate_when_available():
    """tracking_rate 가 60일 이상 있으면 그 std 반환."""
    metrics = _build_synthetic_metrics_df("069500", date(2025, 5, 1), n_days=300, seed=1)
    te = compute_tracking_error_12m(metrics, "069500")
    assert te is not None
    # tracking_rate 의 std (pp). 약 0.3 부근 (seed=1 base vol 0.3).
    assert 0.05 < te < 1.5


def test_compute_tracking_error_12m_returns_none_when_insufficient():
    """< 60일 데이터 → None."""
    metrics = _build_synthetic_metrics_df("069500", date(2026, 5, 1), n_days=30, seed=2)
    # 또한 tracking_rate 컬럼 모두 NaN
    metrics["tracking_rate"] = np.nan
    te = compute_tracking_error_12m(metrics, "069500", index_returns=None)
    assert te is None


def test_compute_premium_discount_median_30day():
    """30일 median |premium_discount|."""
    metrics = _build_synthetic_metrics_df("069500", date(2026, 4, 1), n_days=60, seed=3)
    pd_median = compute_premium_discount_median(metrics, "069500", n_days=30)
    assert pd_median is not None
    assert pd_median >= 0  # |premium_discount| 절댓값이므로 ≥ 0


def test_compute_premium_discount_median_returns_none_when_no_data():
    """ticker 없으면 None."""
    metrics = _build_synthetic_metrics_df("069500", date(2026, 4, 1), n_days=30, seed=4)
    pd_median = compute_premium_discount_median(metrics, "999999", n_days=30)
    assert pd_median is None


def test_compute_volume_per_aum_median_30day():
    """30일 median trade_value/AUM. 유동성 proxy."""
    metrics = _build_synthetic_metrics_df("069500", date(2026, 4, 1), n_days=60, seed=5)
    v_aum = compute_volume_per_aum_median(metrics, "069500", n_days=30)
    assert v_aum is not None
    assert v_aum > 0
