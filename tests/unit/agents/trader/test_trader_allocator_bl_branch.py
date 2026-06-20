from datetime import date
import numpy as np
import pandas as pd
import pytest
from tradingagents.agents.trader import trader_allocator as ta


def test_build_bl_bucket_weights_uses_as_of(monkeypatch):
    captured = {}
    def fake_proxies(as_of, window_days=730):
        captured["as_of"] = as_of
        from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
        idx = pd.bdate_range(end=pd.Timestamp(as_of), periods=400)
        rng = np.random.default_rng(0)
        return pd.DataFrame(rng.normal(0, 0.01, (400, 14)), index=idx, columns=list(GAPS_BUCKET_KEYS))
    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", fake_proxies)
    aso = date(2026, 5, 10)
    bw, meta = ta.build_bl_bucket_weights(aso, "growth_disinflation",
                                          {"b3_global_tech": ("strong_OW", 0.9)})
    assert captured["as_of"] == aso                     # look-ahead guard wired
    assert abs(sum(bw.values()) - 1.0) < 1e-6
    from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
    assert set(bw).issubset(set(GAPS_BUCKET_KEYS))


def test_build_bl_falls_back_to_baseline_on_fetch_failure(monkeypatch):
    def boom(as_of, window_days=730):
        raise RuntimeError("no network")
    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", boom)
    from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE
    bw, meta = ta.build_bl_bucket_weights(date(2026, 5, 10), "growth_disinflation", {})
    base = QUADRANT_BASELINE["growth_disinflation"]
    assert all(abs(bw[k] - base[k]) < 1e-9 for k in base)   # baseline fallback
    assert meta["__global__"]["status"] == "baseline_no_sigma"


def test_fx_credit_extra_views_zero_sum():
    from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
    P, Q, conf = ta._fx_credit_extra_views(list(GAPS_BUCKET_KEYS), "usd_risk_off", "crisis")
    assert P.shape[0] == 2
    assert np.allclose(P.sum(axis=1), 0.0)              # each row zero-sum


def test_build_bl_persists_correlation_summary(monkeypatch):
    # PHIL-4: when Σ is non-empty, build_bl_bucket_weights must persist a COMPACT
    # nested-dict correlation summary into meta['__global__']['correlation'] so the
    # philosophy report can render the 단일리스크통제 fact at report time.
    from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
    keys = list(GAPS_BUCKET_KEYS)

    def fake_proxies(as_of, window_days=730):
        idx = pd.bdate_range(end=pd.Timestamp(as_of), periods=400)
        rng = np.random.default_rng(7)
        return pd.DataFrame(rng.normal(0, 0.01, (400, 14)), index=idx, columns=keys)
    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", fake_proxies)

    bw, meta = ta.build_bl_bucket_weights(
        date(2026, 5, 10), "growth_disinflation",
        {"b3_global_tech": ("strong_OW", 0.9)},
    )
    corr = meta["__global__"].get("correlation")
    assert corr is not None, "correlation summary must be persisted when Σ non-empty"
    # 14×14 nested dict over the 14 buckets
    assert set(corr) == set(keys)
    for k in keys:
        assert set(corr[k]) == set(keys)
        assert abs(corr[k][k] - 1.0) < 1e-6        # unit diagonal
        # symmetric and compact (rounded to 4 dp)
        for j in keys:
            assert abs(corr[k][j] - corr[j][k]) < 1e-9
            assert abs(corr[k][j] - round(corr[k][j], 4)) < 1e-12


def test_build_bl_no_correlation_on_fetch_failure(monkeypatch):
    # Σ unavailable → baseline fallback meta has NO 'correlation' key (graceful).
    def boom(as_of, window_days=730):
        raise RuntimeError("no network")
    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", boom)
    bw, meta = ta.build_bl_bucket_weights(date(2026, 5, 10), "growth_disinflation", {})
    assert "correlation" not in meta["__global__"]
