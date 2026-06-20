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
