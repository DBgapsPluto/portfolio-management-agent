from datetime import date
import pandas as pd
from tradingagents.backtest import bucket_proxies as bp

def test_proxy_map_covers_14_buckets():
    from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
    assert set(bp.BUCKET_PROXY) == set(GAPS_BUCKET_KEYS)
    for k, specs in bp.BUCKET_PROXY.items():
        assert len(specs) >= 1
        for src, key in specs:
            assert src in ("yf", "fred", "pykrx", "cash")

def test_fetch_returns_respects_as_of_no_lookahead(monkeypatch):
    idx = pd.bdate_range("2024-01-01", "2024-12-31")
    full = pd.Series(0.001, index=idx)
    def fake_yf(symbols, start, end):
        sub = full[(full.index.date >= start) & (full.index.date <= end)]
        return pd.DataFrame({s: sub for s in symbols})
    monkeypatch.setattr(bp, "_raw_yf_batch_close", fake_yf)
    monkeypatch.setattr(bp, "_fred_returns", lambda key, start, end: full[(full.index.date >= start) & (full.index.date <= end)])
    monkeypatch.setattr(bp, "_pykrx_returns", lambda key, start, end: full[(full.index.date >= start) & (full.index.date <= end)])
    monkeypatch.setattr(bp, "_cash_returns", lambda key, start, end: full[(full.index.date >= start) & (full.index.date <= end)])
    as_of = date(2024, 6, 30)
    df = bp.fetch_bucket_proxy_returns(as_of, window_days=120)
    assert not df.empty
    assert df.index.max().date() <= as_of

def test_per_bucket_failover_to_alternate(monkeypatch):
    idx = pd.bdate_range("2024-01-01", "2024-12-31")
    good = pd.Series(0.001, index=idx)
    def fake_yf(symbols, start, end):
        out = {}
        for s in symbols:
            out[s] = pd.Series(dtype=float) if s == "MCHI" else good[(good.index.date >= start) & (good.index.date <= end)]
        return pd.DataFrame(out)
    monkeypatch.setattr(bp, "_raw_yf_batch_close", fake_yf)
    monkeypatch.setattr(bp, "_fred_returns", lambda key, start, end: good)
    monkeypatch.setattr(bp, "_pykrx_returns", lambda key, start, end: good)
    monkeypatch.setattr(bp, "_cash_returns", lambda key, start, end: good)
    df = bp.fetch_bucket_proxy_returns(date(2024, 6, 30), window_days=120)
    assert "b4_china" in df.columns
    assert df["b4_china"].notna().sum() > 0

def test_tz_aware_yf_index_does_not_crash(monkeypatch):
    # yfinance can return a tz-AWARE DatetimeIndex; must not crash the as_of cutoff.
    idx_aware = pd.bdate_range("2024-01-01", "2024-12-31", tz="UTC")
    full_aware = pd.Series(0.001, index=idx_aware)
    idx_naive = pd.bdate_range("2024-01-01", "2024-12-31")
    full_naive = pd.Series(0.001, index=idx_naive)
    def fake_yf(symbols, start, end):
        sub = full_aware[(full_aware.index.date >= start) & (full_aware.index.date <= end)]
        return pd.DataFrame({s: sub for s in symbols})
    monkeypatch.setattr(bp, "_raw_yf_batch_close", fake_yf)
    monkeypatch.setattr(bp, "_fred_returns", lambda key, start, end: full_naive[(full_naive.index.date >= start) & (full_naive.index.date <= end)])
    monkeypatch.setattr(bp, "_pykrx_returns", lambda key, start, end: full_naive[(full_naive.index.date >= start) & (full_naive.index.date <= end)])
    monkeypatch.setattr(bp, "_cash_returns", lambda key, start, end: full_naive[(full_naive.index.date >= start) & (full_naive.index.date <= end)])
    as_of = date(2024, 6, 30)
    df = bp.fetch_bucket_proxy_returns(as_of, window_days=120)
    assert not df.empty
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is None
    assert df.index.max().date() <= as_of

def test_assembled_index_is_datetime_even_with_empty_bucket(monkeypatch):
    # One bucket fully fails -> empty series; assembled index must stay datetime64, not object.
    idx = pd.bdate_range("2024-01-01", "2024-12-31")
    good = pd.Series(0.001, index=idx)
    def fake_yf(symbols, start, end):
        out = {}
        for s in symbols:
            # b3_global_tech -> QQQ is the only proxy; make it empty.
            out[s] = pd.Series(dtype=float) if s == "QQQ" else good[(good.index.date >= start) & (good.index.date <= end)]
        return pd.DataFrame(out)
    monkeypatch.setattr(bp, "_raw_yf_batch_close", fake_yf)
    monkeypatch.setattr(bp, "_fred_returns", lambda key, start, end: good[(good.index.date >= start) & (good.index.date <= end)])
    monkeypatch.setattr(bp, "_pykrx_returns", lambda key, start, end: good[(good.index.date >= start) & (good.index.date <= end)])
    monkeypatch.setattr(bp, "_cash_returns", lambda key, start, end: good[(good.index.date >= start) & (good.index.date <= end)])
    df = bp.fetch_bucket_proxy_returns(date(2024, 6, 30), window_days=120)
    assert pd.api.types.is_datetime64_any_dtype(df.index)
    assert "b3_global_tech" in df.columns
    assert df["b3_global_tech"].isna().all()
