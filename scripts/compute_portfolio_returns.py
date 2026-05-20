"""Compute realized returns for backtest portfolios.

For each as_of date with a portfolio.json, fetches subsequent ETF prices and
computes:
- Per-ETF cumulative return (entry → end_date)
- Portfolio-level cumulative return (weighted average)
- Benchmarks: 50/50 KOSPI200+SPY-equivalent, KOSPI200-only, 60/40 stocks/bonds
- Annualized return, max drawdown, Sharpe

Usage:
    python scripts/compute_portfolio_returns.py
"""
from __future__ import annotations

import json
import logging
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(message)s")
logger = logging.getLogger("returns")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Today is 2026-05-20; full-cycle backtests look forward from as_of.
TODAY = date(2026, 5, 20)


def load_universe() -> dict:
    """Return ticker → entry dict from universe.json."""
    u = json.loads((PROJECT_ROOT / "data" / "universe.json").read_text(encoding="utf-8"))
    return {e["ticker"]: e for e in u["etfs"]}


def fetch_etf_close(ticker: str, start: date, end: date) -> pd.Series:
    """Daily close for one ETF via pykrx. Strips leading 'A'."""
    from pykrx import stock
    bare = ticker.lstrip("A") if ticker.startswith("A") else ticker
    df = stock.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), bare)
    if df is None or df.empty or "종가" not in df.columns:
        return pd.Series(dtype=float, name=ticker)
    s = df["종가"].copy()
    s.name = ticker
    s.index = pd.DatetimeIndex(s.index)
    return s


def fetch_benchmark(symbol: str, start: date, end: date) -> pd.Series:
    """yfinance close. SPY/KOSPI200 ETF (069500.KS) etc."""
    import yfinance as yf
    df = yf.Ticker(symbol).history(
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=False,
    )
    if df is None or df.empty or "Close" not in df.columns:
        return pd.Series(dtype=float, name=symbol)
    s = df["Close"].copy().rename(symbol)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s


def compute_metrics(returns: pd.Series, periods_per_year: int = 252) -> dict:
    """Compute annualized return, vol, Sharpe, max DD from daily returns."""
    if len(returns) < 2:
        return {"cum_return": 0.0, "ann_return": 0.0, "ann_vol": 0.0, "sharpe": 0.0, "max_dd": 0.0}
    cum = float((1.0 + returns).prod() - 1.0)
    n_days = len(returns)
    ann_ret = float((1.0 + cum) ** (periods_per_year / n_days) - 1.0)
    ann_vol = float(returns.std() * np.sqrt(periods_per_year))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    cumul_path = (1.0 + returns).cumprod()
    rolling_max = cumul_path.cummax()
    drawdown = (cumul_path - rolling_max) / rolling_max
    max_dd = float(drawdown.min())
    return {
        "cum_return": round(cum, 4),
        "ann_return": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 3),
        "max_dd": round(max_dd, 4),
        "n_days": n_days,
    }


def evaluate_portfolio(as_of: date, end: date) -> dict | None:
    portfolio_path = PROJECT_ROOT / "artifacts" / as_of.isoformat() / "portfolio.json"
    if not portfolio_path.exists():
        logger.warning("No portfolio.json for %s", as_of)
        return None

    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    weights = portfolio.get("weights") or {}
    if not weights:
        logger.warning("Empty weights for %s", as_of)
        return None

    universe = load_universe()
    bt = portfolio.get("bucket_target", {}) or {}

    # Fetch ETF closes
    closes = {}
    failed = []
    for ticker in weights:
        s = fetch_etf_close(ticker, as_of, end)
        if s.empty:
            failed.append(ticker)
            continue
        closes[ticker] = s

    if not closes:
        logger.error("All ETF fetches failed for %s", as_of)
        return None

    # Align on common dates (forward-fill within universe)
    prices = pd.DataFrame(closes).sort_index().dropna(how="all")
    prices = prices.ffill()
    # restrict to dates from as_of onward
    prices = prices[prices.index.date >= as_of]
    if prices.empty or len(prices) < 2:
        logger.error("Insufficient price history for %s", as_of)
        return None

    # Daily returns
    daily_ret = prices.pct_change().dropna()

    # Renormalize weights to fetched tickers only
    fetched_weights = {t: w for t, w in weights.items() if t in closes}
    wsum = sum(fetched_weights.values())
    if wsum == 0:
        return None
    norm_weights = {t: w / wsum for t, w in fetched_weights.items()}

    # Portfolio daily return = weighted sum of daily ETF returns
    weight_series = pd.Series(norm_weights)
    portfolio_daily = (daily_ret[weight_series.index] * weight_series).sum(axis=1)

    portfolio_metrics = compute_metrics(portfolio_daily)
    portfolio_metrics["failed_fetches"] = failed
    portfolio_metrics["n_assets_used"] = len(closes)

    # Benchmarks
    # 1. KOSPI200 — try pykrx (069500 = KODEX 200) first, fallback yfinance
    kospi = fetch_etf_close("A069500", as_of, end)
    if kospi.empty:
        kospi = fetch_benchmark("069500.KS", as_of, end)
    if not kospi.empty:
        kospi_daily = kospi.pct_change().dropna()
        kospi_metrics = compute_metrics(kospi_daily)
    else:
        kospi_metrics = None

    # 2. SPY-only
    spy = fetch_benchmark("SPY", as_of, end)
    if not spy.empty:
        spy_daily = spy.pct_change().dropna()
        spy_metrics = compute_metrics(spy_daily)
    else:
        spy_metrics = None

    # 3. 60/40 — 60% KOSPI200 + 40% KR Treasury 10y ETF (A114820)
    tlt = fetch_etf_close("A114820", as_of, end)  # KODEX 국고채10년
    if tlt.empty:
        tlt = fetch_benchmark("TLT", as_of, end)
    if not kospi.empty and not tlt.empty:
        bench_df = pd.concat([kospi.rename("kospi"), tlt.rename("tlt")], axis=1).dropna()
        bench_df = bench_df[bench_df.index.date >= as_of]
        bench_daily = bench_df.pct_change().dropna()
        sixty_forty = 0.6 * bench_daily["kospi"] + 0.4 * bench_daily["tlt"]
        sixty_forty_metrics = compute_metrics(sixty_forty)
    else:
        sixty_forty_metrics = None

    return {
        "as_of": as_of.isoformat(),
        "end": end.isoformat(),
        "horizon_days": (end - as_of).days,
        "regime_label": portfolio.get("regime_label") or "",
        "bucket_target": {
            k: round(v, 3) for k, v in bt.items() if isinstance(v, (int, float))
        },
        "stock_share": round(
            (bt.get("kr_equity") or 0) + (bt.get("global_equity") or 0), 3
        ),
        "method": (portfolio.get("method_choice") or {}).get("method")
                  or portfolio.get("method"),
        "portfolio": portfolio_metrics,
        "kospi200": kospi_metrics,
        "spy": spy_metrics,
        "60_40_kospi_tlt": sixty_forty_metrics,
    }


def main() -> int:
    # Only as_of dates that have at least 30 days of post-as_of data + portfolio.json
    candidates = [
        (date(2025, 4, 15), TODAY),  # ~13 months — most informative
        (date(2026, 5, 15), TODAY),  # only 5 days — too short, mark as N/A
    ]
    # If historical backtest runs finish later, those will be added.
    for d in ("2022-12-15", "2023-04-14", "2024-08-14"):
        as_of = date.fromisoformat(d)
        if (PROJECT_ROOT / "artifacts" / d / "portfolio.json").exists():
            # Use 1 year horizon (or up to TODAY if shorter)
            end = min(TODAY, as_of + timedelta(days=365))
            candidates.insert(0, (as_of, end))

    results = []
    for as_of, end in candidates:
        if (end - as_of).days < 10:
            logger.info("Skipping %s — horizon < 10 days", as_of)
            continue
        logger.info("Evaluating %s → %s", as_of, end)
        result = evaluate_portfolio(as_of, end)
        if result is not None:
            results.append(result)

    out_path = PROJECT_ROOT / "artifacts" / "portfolio_returns.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_path)

    # Print table
    print()
    print("=" * 100)
    print(" REALIZED RETURNS — Portfolio vs Benchmarks")
    print("=" * 100)
    for r in results:
        print(f"\n## {r['as_of']} → {r['end']}  ({r['horizon_days']}d)  {r['regime_label']}")
        bt = r["bucket_target"]
        print(
            f"  Bucket:   kr_eq={bt.get('kr_equity', 0):.0%} "
            f"global_eq={bt.get('global_equity', 0):.0%} "
            f"fx_com={bt.get('fx_commodity', 0):.0%} "
            f"bond={bt.get('bond', 0):.0%} cash={bt.get('cash_mmf', 0):.0%} "
            f"→ total stock={r['stock_share']:.0%}"
        )
        print(f"  Method:   {r['method']}")
        p = r["portfolio"]
        print(
            f"  Portfolio: cum={p['cum_return']:+.2%}  ann={p['ann_return']:+.2%}  "
            f"vol={p['ann_vol']:.2%}  Sharpe={p['sharpe']:.2f}  "
            f"max_DD={p['max_dd']:.2%}  n_days={p['n_days']}  "
            f"n_assets={p['n_assets_used']}"
        )
        if r["kospi200"]:
            k = r["kospi200"]
            print(
                f"  KOSPI200: cum={k['cum_return']:+.2%}  ann={k['ann_return']:+.2%}  "
                f"vol={k['ann_vol']:.2%}  Sharpe={k['sharpe']:.2f}  max_DD={k['max_dd']:.2%}"
            )
        if r["spy"]:
            s = r["spy"]
            print(
                f"  SPY:      cum={s['cum_return']:+.2%}  ann={s['ann_return']:+.2%}  "
                f"vol={s['ann_vol']:.2%}  Sharpe={s['sharpe']:.2f}  max_DD={s['max_dd']:.2%}"
            )
        if r["60_40_kospi_tlt"]:
            b = r["60_40_kospi_tlt"]
            print(
                f"  60/40:    cum={b['cum_return']:+.2%}  ann={b['ann_return']:+.2%}  "
                f"vol={b['ann_vol']:.2%}  Sharpe={b['sharpe']:.2f}  max_DD={b['max_dd']:.2%}"
            )
        if r["portfolio"].get("failed_fetches"):
            print(f"  Failed:   {r['portfolio']['failed_fetches']}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
