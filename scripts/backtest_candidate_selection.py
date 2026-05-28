"""Backtest legacy momentum-only vs multi-factor + de-dup candidate selection.

Two modes:
- --mode fixture: uses tests/fixtures/pykrx_etf_prices.parquet (small but real).
- --mode synthetic: constructs controlled scenarios to verify mechanism.

Note: full historical backtest requires KRX_ID/KRX_PW env vars for pykrx access
(not available in this environment). Fixture mode gives a limited real-data
sanity check; synthetic mode verifies the new logic behaves as designed across
known scenarios.
"""
from __future__ import annotations

import argparse
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.dataflows.universe import ETFEntry, Universe, load_universe
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.schemas.technical import ETFRanking
from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates


# ────────────────────────────────────────────────────────────────────────────
# Common utilities
# ────────────────────────────────────────────────────────────────────────────

def _returns_from_prices(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    pivot = prices.pivot(index="date", columns="ticker", values="close")
    return pivot.pct_change().dropna(how="all")


def _rank_momentum(prices: pd.DataFrame, universe: Universe) -> dict[str, list[ETFRanking]]:
    """Light momentum-rank (3+6+12 month composite rank) per category."""
    cat_lookup = {e.ticker: e.category for e in universe.etfs}
    grouped: dict[str, list[ETFRanking]] = {}
    for ticker, sub in prices.groupby("ticker"):
        sub = sub.sort_values("date")
        n = len(sub)
        if n < 60:
            continue
        end = float(sub["close"].iloc[-1])
        # use available history (cap at 252)
        idx_3 = max(-n + 1, -63)
        idx_6 = max(-n + 1, -126)
        idx_12 = max(-n + 1, -252)
        m3 = (end / float(sub["close"].iloc[idx_3])) - 1
        m6 = (end / float(sub["close"].iloc[idx_6])) - 1
        m12 = (end / float(sub["close"].iloc[idx_12])) - 1
        cat = cat_lookup.get(ticker, "기타")
        grouped.setdefault(cat, []).append(ETFRanking(
            ticker=ticker, name=ticker,
            momentum_3m=m3, momentum_6m=m6, momentum_12m=m12,
            rank_in_category=1,
        ))
    for items in grouped.values():
        items.sort(key=lambda r: r.momentum_3m + r.momentum_6m + r.momentum_12m, reverse=True)
        for i, r in enumerate(items, start=1):
            r.rank_in_category = i
    return grouped


_NEWLY_LISTED_TOLERANCE_DAYS = 14
"""Skip a ticker if its first post-as_of price is >14 calendar days after as_of.

Newly-listed ETFs have no trading data at as_of, so anchoring the forward
window to "first available date" would silently extend the measurement
horizon to whenever they listed (sometimes 1+ year later). Treat them as
missing instead."""


def _forward_return(prices: pd.DataFrame, ticker: str, start: date, horizon: int) -> float | None:
    sub = prices[prices["ticker"] == ticker].sort_values("date").reset_index(drop=True)
    sub = sub[pd.to_datetime(sub["date"]) >= pd.Timestamp(start)].reset_index(drop=True)
    if len(sub) < 2:
        return None
    first_date = pd.Timestamp(sub["date"].iloc[0])
    if (first_date - pd.Timestamp(start)).days > _NEWLY_LISTED_TOLERANCE_DAYS:
        return None  # ticker not tradable at as_of; skip
    p0 = float(sub["close"].iloc[0])
    p1 = float(sub["close"].iloc[min(horizon, len(sub) - 1)])
    return p1 / p0 - 1 if p0 > 0 else None


def _basket_metrics(prices: pd.DataFrame, tickers: list[str], start: date,
                    horizon: int) -> tuple[float | None, float | None]:
    """(forward return, annualized vol) for equal-weighted basket.

    Skips tickers whose first post-as_of data is more than
    _NEWLY_LISTED_TOLERANCE_DAYS after as_of (newly-listed ETFs).
    """
    rets = [_forward_return(prices, t, start, horizon) for t in tickers]
    rets = [r for r in rets if r is not None]
    fwd = float(np.mean(rets)) if rets else None

    # Daily basket vol over the forward window
    daily = []
    for t in tickers:
        sub = prices[prices["ticker"] == t].sort_values("date")
        sub = sub[pd.to_datetime(sub["date"]) >= pd.Timestamp(start)]
        if len(sub) < horizon:
            continue
        first_date = pd.Timestamp(sub["date"].iloc[0])
        if (first_date - pd.Timestamp(start)).days > _NEWLY_LISTED_TOLERANCE_DAYS:
            continue  # newly-listed; skip
        r = sub["close"].iloc[:horizon].pct_change().dropna()
        daily.append(r.values)
    if not daily:
        return fwd, None
    min_len = min(len(r) for r in daily)
    arr = np.stack([r[:min_len] for r in daily], axis=1)
    basket = arr.mean(axis=1)
    vol = float(basket.std() * math.sqrt(252)) if basket.std() > 0 else None
    return fwd, vol


def _intra_corr(returns: pd.DataFrame, tickers: list[str]) -> float | None:
    cols = [t for t in tickers if t in returns.columns]
    if len(cols) < 2:
        return None
    cm = returns[cols].corr().abs()
    mask = np.triu(np.ones_like(cm, dtype=bool), k=1)
    return float(cm.values[mask].mean())


# ────────────────────────────────────────────────────────────────────────────
# FIXTURE mode (real data, limited)
# ────────────────────────────────────────────────────────────────────────────

def run_fixture_backtest() -> None:
    fx_path = Path("tests/fixtures/pykrx_etf_prices.parquet")
    if not fx_path.exists():
        print(f"[fixture] missing {fx_path}")
        return
    prices = pd.read_parquet(fx_path)
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    print(f"[fixture] {len(prices)} rows, {prices['ticker'].nunique()} tickers, "
          f"{prices['date'].min()} ~ {prices['date'].max()}")

    universe = load_universe(Path("data/universe.json"))
    # Restrict universe to fixture tickers + drop AUM floor for this small sample
    fx_tickers = set(prices["ticker"].unique())
    universe = Universe(
        version=universe.version,
        etfs=[e for e in universe.etfs if e.ticker in fx_tickers],
    )
    if not universe.etfs:
        print("[fixture] no overlap between fixture tickers and universe.json")
        return
    print(f"[fixture] {len(universe.etfs)} usable tickers after universe match:")
    for e in universe.etfs:
        print(f"   {e.ticker} {e.name[:24]:24s} cat={e.category}")

    # BucketTarget chosen so the available categories have weight > 0
    target = BucketTarget(
        kr_equity=0.40, global_equity=0.00, fx_commodity=0.10,
        bond=0.40, cash_mmf=0.10,
        rationale="fixture-fit allocation",
    )

    # As-of dates picked to leave ≥60d of forward data and ≥120d of history.
    # Fixture spans 2025-05-12 ~ 2026-05-08. Pick 2025-11, 2026-01.
    as_of_dates = [date(2025, 11, 3), date(2026, 1, 5)]
    horizon = 60

    rows = []
    for as_of in as_of_dates:
        hist = prices[prices["date"] <= as_of]
        fwd = prices[prices["date"] > as_of]
        if hist.empty or fwd.empty:
            continue
        returns = _returns_from_prices(hist)
        rankings = _rank_momentum(hist, universe)

        legacy = select_etf_candidates(
            universe, target, rankings,
            as_of=as_of, per_bucket_n=2,
            returns=None,
        )
        new = select_etf_candidates(
            universe, target, rankings,
            as_of=as_of, per_bucket_n=2,
            returns=returns,
            regime_quadrant="unknown", regime_confidence=0.5,
            correlation_threshold=0.85,
        )

        legacy_tickers = [t for ts in legacy.bucket_to_tickers.values() for t in ts]
        new_tickers = [t for ts in new.bucket_to_tickers.values() for t in ts]

        legacy_fwd, legacy_vol = _basket_metrics(fwd, legacy_tickers, as_of, horizon)
        new_fwd, new_vol = _basket_metrics(fwd, new_tickers, as_of, horizon)

        rows.append({
            "as_of": as_of.isoformat(),
            "legacy_pick": ",".join(legacy_tickers),
            "new_pick": ",".join(new_tickers),
            "overlap": len(set(legacy_tickers) & set(new_tickers)),
            "legacy_fwd": legacy_fwd, "new_fwd": new_fwd,
            "legacy_vol": legacy_vol, "new_vol": new_vol,
            "legacy_corr": _intra_corr(returns, legacy_tickers),
            "new_corr": _intra_corr(returns, new_tickers),
        })

    df = pd.DataFrame(rows)
    print()
    print(f"[fixture] forward {horizon}d basket metrics:")
    print(df.to_string(index=False))
    print()
    print("⚠️ Sample size: tiny (2 dates × few tickers). Not statistically meaningful;")
    print("    purely a wiring sanity check on real prices.")


# ────────────────────────────────────────────────────────────────────────────
# SYNTHETIC mode (mechanism verification)
# ────────────────────────────────────────────────────────────────────────────

def _make_synthetic_universe(tickers: list[str], category: str = "국내주식_지수") -> Universe:
    return Universe(
        version="synth",
        etfs=[ETFEntry(
            ticker=t, name=t, aum_krw=10e12,
            underlying_index="x", bucket="위험", category=category,
        ) for t in tickers],
    )


def _make_series(seed: int, days: int = 400, drift: float = 0.0,
                 vol: float = 0.012, spike_last: int = 0,
                 spike_size: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, days)
    if spike_last > 0:
        r[-spike_last:] += spike_size
    return np.cumprod(1 + r) * 100


def _to_prices(series_by_ticker: dict[str, np.ndarray]) -> pd.DataFrame:
    rows = []
    days = next(iter(series_by_ticker.values())).shape[0]
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    for t, arr in series_by_ticker.items():
        for d, p in zip(dates, arr):
            rows.append({"ticker": t, "date": d.date(), "close": float(p)})
    return pd.DataFrame(rows)


def _scenario(name: str, series_by_ticker: dict[str, np.ndarray],
              regime_quadrant: str, regime_confidence: float,
              per_bucket_n: int = 4) -> dict:
    tickers = list(series_by_ticker.keys())
    universe = _make_synthetic_universe(tickers)
    prices = _to_prices(series_by_ticker)
    returns = _returns_from_prices(prices)
    rankings = _rank_momentum(prices, universe)

    target = BucketTarget(
        kr_equity=1.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.0,
        rationale="synth",
    )
    as_of = date(2024, 1, 1) + timedelta(days=int(prices["date"].max().toordinal()
                                                    - date(2024, 1, 1).toordinal()))
    legacy = select_etf_candidates(
        universe, target, rankings,
        as_of=as_of, per_bucket_n=per_bucket_n,
        returns=None,
    )
    new = select_etf_candidates(
        universe, target, rankings,
        as_of=as_of, per_bucket_n=per_bucket_n,
        returns=returns,
        regime_quadrant=regime_quadrant, regime_confidence=regime_confidence,
        correlation_threshold=0.85,
    )
    return {
        "scenario": name,
        "regime": f"{regime_quadrant}/{regime_confidence:.2f}",
        "legacy": legacy.bucket_to_tickers["kr_equity"],
        "new": new.bucket_to_tickers["kr_equity"],
    }


def run_synthetic_backtest() -> None:
    print("[synthetic] mechanism verification on controlled scenarios")
    print()

    # ─── Scenario 1: skip-1m matters ─────────────────────────────────────
    # Two tickers A and B. Both flat over 12m EXCEPT:
    #   A has a +30% spike in the LAST 21 days.
    #   B has a steady +20% drift over 12m without recent spike.
    # Legacy momentum sees A as #1 (recent spike dominates the raw windows).
    # New skip-1m filter excludes the last 21d → A's edge disappears.
    s1 = {
        "A_recent_spike":  _make_series(1, drift=0.0,  spike_last=21, spike_size=0.013),
        "B_steady_trend":  _make_series(2, drift=0.0009),
        "C_dud":           _make_series(3, drift=-0.0005),
        "D_dud":           _make_series(4, drift=-0.0010),
    }
    r1 = _scenario("Skip-1m discounts recent spike", s1,
                   regime_quadrant="growth_disinflation", regime_confidence=1.0,
                   per_bucket_n=2)

    # ─── Scenario 2: de-dup rejects correlated near-duplicates ───────────
    # A1 and A2 are nearly identical (corr 0.99). B and C are uncorrelated.
    # Legacy picks A1+A2+B by raw momentum if A is the top trend.
    # New should pick A1+B+C (drop A2 as too correlated with A1).
    np.random.seed(101)
    base = np.random.normal(0.0008, 0.012, 400)
    noise = np.random.normal(0.0, 0.012, 400)
    a1 = np.cumprod(1 + base) * 100
    a2 = np.cumprod(1 + base + 0.0003 * noise) * 100  # near-identical
    b = _make_series(7, drift=0.0006)
    c = _make_series(8, drift=0.0007)
    s2 = {"A1_clone": a1, "A2_clone": a2, "B_independent": b, "C_independent": c}
    r2 = _scenario("Correlation de-dup", s2,
                   regime_quadrant="growth_disinflation", regime_confidence=1.0,
                   per_bucket_n=3)

    # ─── Scenario 3: recession regime prefers low-vol ────────────────────
    # H = high momentum + high vol; L = lower momentum but very low vol.
    # In growth_disinflation: H should win (mom weight 0.50, lowvol 0.10).
    # In recession_disinflation: L should win (lowvol 0.45, mom 0.15).
    # Use deterministic drift + small controlled noise so signal dominates.
    days = 400
    rng = np.random.default_rng(303)
    h_drift_path = np.linspace(100, 160, days)              # +60% total, smooth
    h_noise = rng.normal(0, 2.5, days)                       # high daily noise
    h_prices = h_drift_path + np.cumsum(h_noise) * 0.5       # high vol + high mom
    l_prices = np.linspace(100, 110, days)                   # +10% total, ~no noise
    m_prices = np.linspace(100, 120, days) + rng.normal(0, 0.3, days)
    n_prices = np.linspace(100, 95, days) + rng.normal(0, 0.3, days)
    s3 = {
        "H_high_mom_high_vol": h_prices,
        "L_low_mom_low_vol":   l_prices,
        "M_medium":            m_prices,
        "N_dud":               n_prices,
    }
    r3a = _scenario("Regime growth → prefer high-mom (H)", s3,
                    regime_quadrant="growth_disinflation", regime_confidence=1.0,
                    per_bucket_n=1)
    r3b = _scenario("Regime recession → prefer low-vol (L)", s3,
                    regime_quadrant="recession_disinflation", regime_confidence=1.0,
                    per_bucket_n=1)

    # ─── Report ──────────────────────────────────────────────────────────
    results = [r1, r2, r3a, r3b]
    print("scenario                                  | regime                       | legacy                            | new")
    print("-" * 145)
    for r in results:
        print(f"{r['scenario']:42s}| {r['regime']:30s}| {', '.join(r['legacy']):35s}| {', '.join(r['new'])}")
    print()

    # Expectations
    print("Expectations:")
    print("  1) skip-1m: 'A_recent_spike' SHOULD appear in legacy but NOT in new top-2")
    print(f"     legacy first2 = {r1['legacy']}")
    print(f"     new first2    = {r1['new']}")
    print(f"     PASS = {('A_recent_spike' in r1['legacy']) and ('A_recent_spike' not in r1['new'])}")
    print()
    print("  2) de-dup: A2_clone should be dropped in 'new' (kept in legacy)")
    print(f"     legacy 3-pick = {r2['legacy']}")
    print(f"     new 3-pick    = {r2['new']}")
    print(f"     PASS = {('A2_clone' in r2['legacy']) and ('A2_clone' not in r2['new'])}")
    print()
    print("  3a) growth regime: H_high_mom_high_vol top-1 in new")
    print(f"      new = {r3a['new']}")
    print(f"      PASS = {r3a['new'] == ['H_high_mom_high_vol']}")
    print()
    print("  3b) recession regime: L_low_mom_low_vol top-1 in new (different from 3a)")
    print(f"      legacy = {r3b['legacy']}  new = {r3b['new']}")
    print(f"      PASS = {r3b['new'] == ['L_low_mom_low_vol']}")


# ────────────────────────────────────────────────────────────────────────────
# KRX mode (real multi-year historical backtest)
# ────────────────────────────────────────────────────────────────────────────

def run_krx_backtest(
    cache_path: Path,
    as_of_dates: list[date],
    horizon_days: int = 90,
    regime_overrides: dict[date, tuple[str, float]] | None = None,
) -> pd.DataFrame:
    """Real backtest using pykrx ParquetCache (prefetched).

    For each as_of date, runs both candidate selection modes and compares
    forward returns / vol / intra-correlation. Returns a summary DataFrame.
    """
    from tradingagents.dataflows.pykrx_data import (
        ParquetCache, fetch_etf_ohlcv_batch,
    )
    from tradingagents.skills.portfolio.candidate_selector import (
        list_eligible_tickers,
    )

    universe = load_universe(Path("data/universe.json"))

    # Standard moderate BucketTarget — isolates candidate-selection signal
    target = BucketTarget(
        kr_equity=0.25, global_equity=0.20, fx_commodity=0.05,
        bond=0.40, cash_mmf=0.10,
        rationale="standard 50/50 for backtest comparison",
    )

    cache = ParquetCache(cache_path)
    # Pull cached prices (no re-fetch); cap fetch span if cache miss.
    fetch_start = min(as_of_dates) - timedelta(days=365 * 3 + 30)
    fetch_end = max(as_of_dates) + timedelta(days=horizon_days + 30)
    eligible_by_bucket = list_eligible_tickers(
        universe, target, as_of=min(as_of_dates),
    )
    all_eligible = sorted({t for ts in eligible_by_bucket.values() for t in ts})
    print(f"[krx] {len(all_eligible)} eligible tickers — pulling from cache "
          f"({cache_path})…")
    prices = fetch_etf_ohlcv_batch(all_eligible, fetch_start, fetch_end, cache=cache)
    if prices.empty:
        raise RuntimeError("No price data — populate cache first.")
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    print(f"[krx] {len(prices)} rows, "
          f"{prices['ticker'].nunique()} distinct tickers, "
          f"{prices['date'].min()} → {prices['date'].max()}")

    rows = []
    for as_of in as_of_dates:
        hist = prices[prices["date"] <= as_of]
        fwd  = prices[prices["date"] >  as_of]
        if hist.empty or fwd.empty:
            print(f"[{as_of}] skipping — no hist/forward data")
            continue
        returns = _returns_from_prices(hist)
        rankings = _rank_momentum(hist, universe)

        if regime_overrides and as_of in regime_overrides:
            quad, conf = regime_overrides[as_of]
        else:
            quad, conf = "unknown", 0.5

        legacy = select_etf_candidates(
            universe, target, rankings,
            as_of=as_of, per_bucket_n=4,
            returns=None,
        )
        new = select_etf_candidates(
            universe, target, rankings,
            as_of=as_of, per_bucket_n=4,
            returns=returns,
            regime_quadrant=quad, regime_confidence=conf,
            correlation_threshold=0.85,
        )

        legacy_t = [t for ts in legacy.bucket_to_tickers.values() for t in ts]
        new_t    = [t for ts in new.bucket_to_tickers.values() for t in ts]

        legacy_fwd, legacy_vol = _basket_metrics(fwd, legacy_t, as_of, horizon_days)
        new_fwd, new_vol       = _basket_metrics(fwd, new_t, as_of, horizon_days)

        rows.append({
            "as_of": as_of.isoformat(),
            "regime": f"{quad}/{conf:.2f}",
            "legacy_n": len(legacy_t),
            "new_n": len(new_t),
            "overlap": len(set(legacy_t) & set(new_t)),
            "legacy_fwd": legacy_fwd, "new_fwd": new_fwd,
            "delta_ret": (new_fwd - legacy_fwd)
                         if legacy_fwd is not None and new_fwd is not None else None,
            "legacy_vol": legacy_vol, "new_vol": new_vol,
            "legacy_corr": _intra_corr(returns, legacy_t),
            "new_corr": _intra_corr(returns, new_t),
        })

    df = pd.DataFrame(rows)
    return df


def _print_krx_summary(df: pd.DataFrame, horizon: int) -> None:
    if df.empty:
        print("[krx] no results.")
        return
    cols = ["legacy_fwd", "new_fwd", "delta_ret",
            "legacy_vol", "new_vol", "legacy_corr", "new_corr"]
    print()
    print(f"[krx] forward {horizon}d returns/vol — legacy vs new")
    print(df.to_string(index=False, formatters={c: _fmt for c in cols}))
    print()
    valid = df.dropna(subset=["delta_ret"])
    if not valid.empty:
        mean_d = valid["delta_ret"].mean()
        win = (valid["delta_ret"] >= 0).mean()
        print(f"  Mean Δreturn (new − legacy): {mean_d:+.2%}")
        print(f"  Win rate (new ≥ legacy):     {win:.0%}  ({len(valid)} dates)")
    vc = df.dropna(subset=["legacy_corr", "new_corr"])
    if not vc.empty:
        d_corr = (vc["new_corr"] - vc["legacy_corr"]).mean()
        print(f"  Mean Δintra-correlation:     {d_corr:+.3f}  "
              f"(negative = new is more diverse)")
    vv = df.dropna(subset=["legacy_vol", "new_vol"])
    if not vv.empty:
        d_vol = (vv["new_vol"] - vv["legacy_vol"]).mean()
        print(f"  Mean Δvol:                   {d_vol:+.2%}  "
              f"(negative = new is less volatile)")


def _fmt(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if isinstance(v, float):
        return f"{v:+.2%}" if abs(v) < 5 else f"{v:.2f}"
    return str(v)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["fixture", "synthetic", "krx", "both"],
                   default="both")
    p.add_argument("--cache", default="data/.cache/pykrx_universe.parquet")
    p.add_argument("--horizon", type=int, default=90)
    p.add_argument("--dates", nargs="*", default=None,
                   help="ISO dates as_of for KRX mode; default = quarterly grid")
    args = p.parse_args()

    if args.mode in ("synthetic", "both"):
        run_synthetic_backtest()
        print()
    if args.mode in ("fixture", "both"):
        run_fixture_backtest()
    if args.mode == "krx":
        if args.dates:
            dates = [date.fromisoformat(d) for d in args.dates]
        else:
            # Quarterly grid 2023-Q2 → 2025-Q3 (≥90d forward needed at the end)
            dates = [
                date(2023, 4, 3), date(2023, 7, 3), date(2023, 10, 2),
                date(2024, 1, 2), date(2024, 4, 1), date(2024, 7, 1),
                date(2024, 10, 1), date(2025, 1, 2), date(2025, 4, 1),
                date(2025, 7, 1),
            ]
        df = run_krx_backtest(Path(args.cache), dates, horizon_days=args.horizon)
        _print_krx_summary(df, args.horizon)


if __name__ == "__main__":
    main()
