"""Phase 4 — pykrx series cache + CNN F&G cache."""
from datetime import date

import pandas as pd

from tradingagents.dataflows.pykrx_data import (
    fetch_credit_balance, fetch_market_index,
)
from tradingagents.dataflows.volatility import fetch_vkospi


def _series(values, name):
    idx = pd.to_datetime(["2026-05-15", "2026-05-16"])
    return pd.Series(values, index=idx, name=name)


def _patch_cache_dir(monkeypatch, tmp_path):
    import tradingagents.default_config as cfg
    # setitem so the shared dict reference (imported elsewhere) sees the update
    monkeypatch.setitem(cfg.DEFAULT_CONFIG, "data_cache_dir", str(tmp_path))


def test_vkospi_cache_hit_skips_live(tmp_path, monkeypatch):
    _patch_cache_dir(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_live(start, end):
        calls["n"] += 1
        return _series([18.0, 19.0], "VKOSPI")

    monkeypatch.setattr(
        "tradingagents.dataflows.volatility._live_vkospi", fake_live,
    )
    s1 = fetch_vkospi(date(2026, 5, 10), date(2026, 5, 16))
    s2 = fetch_vkospi(date(2026, 5, 10), date(2026, 5, 16))
    assert calls["n"] == 1
    assert (s1 == s2).all()


def test_vkospi_live_failure_returns_empty(tmp_path, monkeypatch):
    _patch_cache_dir(monkeypatch, tmp_path)

    def fake_live(start, end):
        raise RuntimeError("pykrx fail")

    monkeypatch.setattr(
        "tradingagents.dataflows.volatility._live_vkospi", fake_live,
    )
    s = fetch_vkospi(date(2026, 5, 10), date(2026, 5, 16))
    assert s.empty


def test_market_index_cache_hit(tmp_path, monkeypatch):
    _patch_cache_dir(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_live(code, start, end):
        calls["n"] += 1
        return _series([2500.0, 2510.0], f"idx_{code}")

    monkeypatch.setattr(
        "tradingagents.dataflows.pykrx_data._live_market_index", fake_live,
    )
    fetch_market_index("1001", date(2026, 5, 10), date(2026, 5, 16))
    fetch_market_index("1001", date(2026, 5, 10), date(2026, 5, 16))
    assert calls["n"] == 1


def test_credit_balance_cache_hit(tmp_path, monkeypatch):
    _patch_cache_dir(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_live(start, end):
        calls["n"] += 1
        return _series([1e12, 1.05e12], "credit_balance")

    monkeypatch.setattr(
        "tradingagents.dataflows.pykrx_data._live_credit_balance", fake_live,
    )
    fetch_credit_balance(date(2026, 5, 10), date(2026, 5, 16))
    fetch_credit_balance(date(2026, 5, 10), date(2026, 5, 16))
    assert calls["n"] == 1


def test_market_index_different_codes_separate_cache(tmp_path, monkeypatch):
    _patch_cache_dir(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_live(code, start, end):
        calls["n"] += 1
        return _series([100.0, 101.0], f"idx_{code}")

    monkeypatch.setattr(
        "tradingagents.dataflows.pykrx_data._live_market_index", fake_live,
    )
    fetch_market_index("1001", date(2026, 5, 10), date(2026, 5, 16))
    fetch_market_index("2001", date(2026, 5, 10), date(2026, 5, 16))
    assert calls["n"] == 2  # 다른 code는 별도 cache key
