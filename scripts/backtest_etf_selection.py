"""Sanity backtest: ETF-selection by risk-adjusted momentum vs. by size (PIT).

Lightweight GO/NO-GO check for the "ETF-selection hybrid" change. Heterogeneous
GAPS buckets (b2_dm_core, b3_global_tech, b5_other_intl) hold many ETFs tracking
*different* underlyings, so the within-bucket pick matters. The hybrid now picks
top-K by `risk_adjusted_momentum` (skip-1m 3/6/12m momentum rank, penalized by
realized-vol rank) instead of by size. Does that beat picking by size, net of a
10bps turnover cost, over recent history?

This is a SANITY CHECK, not a production component. It reuses the live tools:
- pykrx OHLCV (via `fetch_etf_ohlcv_batch`) for both prices and traded volume.
- `compute_factor_panel` + `risk_adjusted_momentum` for the momentum signal.

Strategy B is a POINT-IN-TIME size/liquidity benchmark. We do NOT use the static
present-day `aum_krw` from universe.json — that is 2026 AUM applied to every month
back to 2019, which hands B hindsight winners (the biggest 2026 ETFs were tiny or
unlisted in 2019-2021, and AUM growth correlates with realized momentum). Instead
B ranks by the trailing ~60-trading-day average of daily DOLLAR VOLUME
(`close * volume`) measured strictly as of each rebalance — a standard PIT
liquidity/size proxy. This is the honest "pick the big, liquid ones" benchmark.

Method (point-in-time, monthly rebalance):
  For each month-end `as_of` (after a 273-trading-day warm-up for skip-1m 12m
  momentum, requiring >= 24 months of usable history):
    - Eligibility (PIT): ETF must be listed (`listed_since <= as_of`) AND have
      >= 273 trading days of price history ending <= as_of.
    - Build factor panels using ONLY returns with date <= as_of.
    - Strategy A (momentum): within each bucket pick top-K by risk_adjusted_momentum.
    - Strategy B (size, PIT): within each bucket pick top-K by trailing-60d mean
      dollar-volume measured strictly <= as_of.
    - Hold equal-weight for the next month; record next-month return per strategy.
    - Charge turnover * 10bps when the pick set changes month-to-month.
    - A month only counts toward the headline A-vs-B series when at least
      top_k + 1 ETFs are eligible (so A and B can actually diverge); thinner
      months are reported in the coverage block but excluded from the verdict.
  Aggregate over months -> cumulative return, annualized Sharpe, max drawdown.

GO  = momentum (A) beats size (B) on cumulative return AND Sharpe, AND is not
      materially worse on max drawdown (MDD_A <= MDD_B + 2pp tolerance).
NO-GO otherwise.

PIT correctness: returns AND dollar-volume AFTER as_of are never used to form the
as_of pick; the next-month realized return is computed strictly from the
(as_of, next_as_of] window.

Usage:
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe \
        scripts/backtest_etf_selection.py [--start 2019-01-01] [--end 2025-12-31] \
        [--top-k 3] [--w-vol 0.4]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# .env auto-load (FRED/ECOS/KRX keys). Same pattern as run_backtest.py.
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
except ImportError:
    pass

from tradingagents.dataflows.pykrx_data import (  # noqa: E402
    ParquetCache,
    fetch_etf_ohlcv_batch,
)
from tradingagents.skills.portfolio.factor_scorer import (  # noqa: E402
    compute_factor_panel,
    risk_adjusted_momentum,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(message)s")
logger = logging.getLogger("etf_selection_backtest")

# Heterogeneous GAPS buckets only — within these the ETFs track *different*
# underlyings, so the within-bucket selection actually changes exposure.
# b1 (kr_equity), b4 (china), b6 (defensive), b7 (reits) and especially
# b8 (cyclical_commodity) are excluded — b8 is explicitly not heterogeneous.
HETEROGENEOUS_BUCKETS = ("b2_dm_core", "b3_global_tech", "b5_other_intl")

# Skip-1m 12m momentum needs ~252 returns ending at t-21 -> 252 + 21 = 273.
WARMUP_TRADING_DAYS = 273
MIN_MONTHS = 24
TURNOVER_COST_BPS = 10.0  # one-way turnover cost in basis points
TRADING_DAYS_PER_YEAR = 252
MDD_TOLERANCE_PP = 0.02  # A may be up to 2pp worse on MDD and still "not material"

# Strategy B (PIT size proxy): trailing window of daily dollar-volume averaged
# strictly as of each rebalance. ~60 trading days ~= 3 calendar months — a
# standard liquidity/size lookback that is point-in-time by construction.
DOLLAR_VOLUME_WINDOW = 60

CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "backtest_etf_selection_prices.parquet"


# ---------------------------------------------------------------------------
# universe
# ---------------------------------------------------------------------------
def _parse_listed_since(raw: "str | None") -> "pd.Timestamp | None":
    """Parse universe.json `listed_since` (YYYY-MM-DD) -> Timestamp, or None."""
    if not raw:
        return None
    try:
        return pd.Timestamp(raw)
    except (ValueError, TypeError):
        return None


def load_heterogeneous_universe() -> dict[str, list[dict]]:
    """bucket -> list of {ticker, name, aum_krw, listed_since, sub_category}.

    `listed_since` is a Timestamp (or None when absent/unparseable). It gates
    PIT eligibility: an ETF is only selectable on/after its listing date. The
    static `aum_krw` is retained for reference/logging only — Strategy B ranks
    by point-in-time dollar-volume, NOT by this present-day AUM (look-ahead).
    """
    raw = json.loads(
        (PROJECT_ROOT / "data" / "universe.json").read_text(encoding="utf-8")
    )
    by_bucket: dict[str, list[dict]] = {b: [] for b in HETEROGENEOUS_BUCKETS}
    for e in raw["etfs"]:
        b = e.get("gaps_bucket")
        if b in by_bucket and e.get("delisted_at") is None:
            by_bucket[b].append(
                {
                    "ticker": e["ticker"],
                    "name": e.get("name", e["ticker"]),
                    "aum_krw": float(e.get("aum_krw", 0.0)),
                    "listed_since": _parse_listed_since(e.get("listed_since")),
                    "sub_category": e.get("sub_category", ""),
                }
            )
    return by_bucket


# ---------------------------------------------------------------------------
# price + dollar-volume fetch
# ---------------------------------------------------------------------------
def fetch_returns_and_dollar_volume(
    tickers: list[str], start: date, end: date, cache_path: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch OHLCV once and build (daily_returns, daily_dollar_volume) matrices.

    Both are date x ticker frames sharing the same OHLCV pull (cached parquet),
    so close-prices and volume stay aligned. Dollar volume = close * volume in
    KRW — the raw input to Strategy B's trailing-mean PIT size proxy.

    Returns (empty, empty) on a total data miss so callers degrade gracefully.
    """
    cache = ParquetCache(cache_path)
    raw = fetch_etf_ohlcv_batch(tickers, start, end, cache=cache)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()

    close = raw.pivot(index="date", columns="ticker", values="close")
    returns = close.pct_change().dropna(how="all")

    vol = raw.pivot(index="date", columns="ticker", values="volume")
    # Dollar volume in KRW: close price * shares traded. NaN where either is NaN.
    dollar_volume = (close * vol).reindex(returns.index)
    return returns, dollar_volume


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def cumulative_return(monthly: pd.Series) -> float:
    """Compound a series of monthly simple returns."""
    if monthly.empty:
        return float("nan")
    return float((1.0 + monthly).prod() - 1.0)


def annualized_sharpe(monthly: pd.Series) -> float:
    """Annualized Sharpe from monthly returns (rf=0). NaN if <2 obs or zero vol."""
    m = monthly.dropna()
    if len(m) < 2:
        return float("nan")
    sd = float(m.std(ddof=1))
    if sd == 0.0:
        return float("nan")
    return float(m.mean() / sd * np.sqrt(12.0))


def max_drawdown(monthly: pd.Series) -> float:
    """Max drawdown of the cumulative equity curve from monthly returns.

    Returns a non-negative magnitude (e.g. 0.18 == -18% peak-to-trough).
    """
    m = monthly.dropna()
    if m.empty:
        return float("nan")
    equity = (1.0 + m).cumprod()
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(-drawdown.min())


# ---------------------------------------------------------------------------
# core backtest
# ---------------------------------------------------------------------------
def month_end_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Last available trading day of each calendar month present in `index`."""
    s = pd.Series(index, index=index)
    grouped = s.groupby([index.year, index.month]).max()
    return sorted(grouped.tolist())


def _panels_as_of(
    returns: pd.DataFrame,
    as_of: pd.Timestamp,
    tickers: list[str],
    aum: dict[str, float],
) -> dict[str, "object | None"]:
    """Build factor panels for `tickers` using ONLY returns with date <= as_of.

    PIT guard: slices returns to .loc[:as_of] before computing any factor.
    Tickers without enough usable history get a None panel (handled downstream).
    """
    hist = returns.loc[:as_of]
    panels: dict[str, object | None] = {}
    for t in tickers:
        if t not in hist.columns:
            panels[t] = None
            continue
        series = hist[t].dropna()
        # need >= warm-up days for the 12m skip-1m window to be defined
        if len(series) < WARMUP_TRADING_DAYS:
            panels[t] = None
            continue
        panels[t] = compute_factor_panel(series, aum.get(t, 1.0))
    return panels


def _pick_top_k_momentum(
    panels: dict[str, object | None], w_vol: float, k: int
) -> list[str]:
    """Top-K tickers by risk_adjusted_momentum (higher = better).

    -inf scores (all momentum windows None) sort last; tickers with a None
    panel are excluded entirely (no usable history).
    """
    eligible = {t: p for t, p in panels.items() if p is not None}
    if not eligible:
        return []
    scores = risk_adjusted_momentum(eligible, w_vol=w_vol)
    ranked = sorted(
        scores.items(),
        key=lambda kv: (kv[1], kv[0]),  # tie-break by ticker for determinism
        reverse=True,
    )
    picks = [t for t, sc in ranked if sc != float("-inf")][:k]
    if not picks:  # everyone is -inf but has a panel -> fall back to first k
        picks = [t for t, _ in ranked][:k]
    return picks


def _pit_dollar_volume(
    dollar_volume: pd.DataFrame,
    as_of: pd.Timestamp,
    tickers: list[str],
    window: int = DOLLAR_VOLUME_WINDOW,
) -> dict[str, float]:
    """Trailing-`window` mean daily dollar-volume per ticker, strictly <= as_of.

    PIT guard: slices to rows with index <= as_of, takes the last `window`
    observations, and averages. Tickers with no traded-volume history in the
    window get 0.0 (they sort last in Strategy B). This is the point-in-time
    size/liquidity proxy that replaces static present-day AUM.
    """
    hist = dollar_volume.loc[:as_of]
    out: dict[str, float] = {}
    for t in tickers:
        if t not in hist.columns:
            out[t] = 0.0
            continue
        series = hist[t].dropna()
        if series.empty:
            out[t] = 0.0
            continue
        out[t] = float(series.iloc[-window:].mean())
    return out


def _pick_top_k_dollar_volume(
    eligible_tickers: list[str], dvol: dict[str, float], k: int
) -> list[str]:
    """Top-K eligible tickers by trailing PIT dollar-volume (higher = bigger/liquider)."""
    ranked = sorted(
        eligible_tickers,
        key=lambda t: (dvol.get(t, 0.0), t),
        reverse=True,
    )
    return ranked[:k]


def _next_month_return(
    returns: pd.DataFrame, picks: list[str], start: pd.Timestamp, end: pd.Timestamp
) -> float | None:
    """Equal-weight next-month return over (start, end] for `picks`.

    Compounds each ticker's daily returns strictly AFTER `start` through `end`,
    then equal-weights across the picks that have data in the window.
    """
    if not picks:
        return None
    window = returns.loc[(returns.index > start) & (returns.index <= end)]
    if window.empty:
        return None
    per_ticker: list[float] = []
    for t in picks:
        if t not in window.columns:
            continue
        r = window[t].dropna()
        if r.empty:
            continue
        per_ticker.append(float((1.0 + r).prod() - 1.0))
    if not per_ticker:
        return None
    return float(np.mean(per_ticker))


def _turnover(prev: list[str], curr: list[str]) -> float:
    """Fraction of an equal-weight book that changes between two pick sets.

    Both books are equal-weight 1/len. Turnover = 0.5 * sum |w_curr - w_prev|.
    """
    if not curr and not prev:
        return 0.0
    wp = {t: 1.0 / len(prev) for t in prev} if prev else {}
    wc = {t: 1.0 / len(curr) for t in curr} if curr else {}
    names = set(wp) | set(wc)
    return 0.5 * sum(abs(wc.get(t, 0.0) - wp.get(t, 0.0)) for t in names)


def run_bucket_backtest(
    bucket: str,
    members: list[dict],
    returns: pd.DataFrame,
    dollar_volume: pd.DataFrame,
    rebal_dates: list[pd.Timestamp],
    top_k: int,
    w_vol: float,
) -> dict:
    """Run A (momentum) vs B (PIT dollar-volume size proxy) for a single bucket.

    Eligibility per month is point-in-time: an ETF must be listed
    (`listed_since <= as_of`) AND have >= WARMUP_TRADING_DAYS of price history
    ending <= as_of. A month only counts toward the headline A-vs-B series when
    at least `top_k + 1` ETFs are eligible (so the two strategies can actually
    pick different sets); thinner months are tracked separately.

    Returns per-month net returns for both strategies plus coverage counts.
    """
    tickers = [m["ticker"] for m in members]
    aum = {m["ticker"]: m["aum_krw"] for m in members}
    listed_since = {m["ticker"]: m["listed_since"] for m in members}

    a_returns: list[float] = []
    b_returns: list[float] = []
    months: list[pd.Timestamp] = []
    coverage: list[int] = []  # eligible count at every rebalance (full honesty)
    thin_months = 0          # months with 2..top_k eligible (excluded from verdict)

    prev_a: list[str] = []
    prev_b: list[str] = []
    cost = TURNOVER_COST_BPS / 10_000.0
    min_eligible = top_k + 1

    for i in range(len(rebal_dates) - 1):
        as_of = rebal_dates[i]
        nxt = rebal_dates[i + 1]

        panels = _panels_as_of(returns, as_of, tickers, aum)
        # PIT eligibility: listed on/before as_of AND has enough price history.
        eligible = []
        for t, p in panels.items():
            if p is None:
                continue
            ls = listed_since.get(t)
            if ls is not None and ls > as_of:
                continue  # not yet listed at this rebalance
            eligible.append(t)
        coverage.append(len(eligible))

        if len(eligible) < min_eligible:
            # Fewer than top_k + 1 eligible — A and B are forced to overlap, so
            # the month carries no A-vs-B signal. Track it for the coverage
            # block but EXCLUDE it from the headline series. Keep prev picks
            # (no forced turnover on a thin/data-gap month).
            if len(eligible) >= 2:
                thin_months += 1
            continue

        picks_a = _pick_top_k_momentum(
            {t: panels[t] for t in eligible}, w_vol, top_k
        )
        dvol = _pit_dollar_volume(dollar_volume, as_of, eligible)
        picks_b = _pick_top_k_dollar_volume(eligible, dvol, top_k)

        ret_a = _next_month_return(returns, picks_a, as_of, nxt)
        ret_b = _next_month_return(returns, picks_b, as_of, nxt)
        if ret_a is None or ret_b is None:
            continue

        to_a = _turnover(prev_a, picks_a)
        to_b = _turnover(prev_b, picks_b)

        a_returns.append(ret_a - to_a * cost)
        b_returns.append(ret_b - to_b * cost)
        months.append(nxt)
        prev_a, prev_b = picks_a, picks_b

    a_series = pd.Series(a_returns, index=pd.DatetimeIndex(months))
    b_series = pd.Series(b_returns, index=pd.DatetimeIndex(months))
    return {
        "bucket": bucket,
        "n_members": len(tickers),
        "a_series": a_series,
        "b_series": b_series,
        "n_months": len(a_series),
        "thin_months": thin_months,
        "coverage": coverage,
        "min_coverage": min(coverage) if coverage else 0,
        "max_coverage": max(coverage) if coverage else 0,
        "median_coverage": int(np.median(coverage)) if coverage else 0,
    }


def summarize(label: str, a: pd.Series, b: pd.Series) -> dict:
    """Compute cumret / Sharpe / MDD for both strategies and a verdict."""
    cum_a, cum_b = cumulative_return(a), cumulative_return(b)
    shp_a, shp_b = annualized_sharpe(a), annualized_sharpe(b)
    mdd_a, mdd_b = max_drawdown(a), max_drawdown(b)

    beats_cum = (not np.isnan(cum_a)) and (not np.isnan(cum_b)) and cum_a > cum_b
    beats_shp = (not np.isnan(shp_a)) and (not np.isnan(shp_b)) and shp_a > shp_b
    not_worse_mdd = (
        np.isnan(mdd_a) or np.isnan(mdd_b) or mdd_a <= mdd_b + MDD_TOLERANCE_PP
    )
    go = bool(beats_cum and beats_shp and not_worse_mdd)

    return {
        "label": label,
        "cum_a": cum_a,
        "cum_b": cum_b,
        "shp_a": shp_a,
        "shp_b": shp_b,
        "mdd_a": mdd_a,
        "mdd_b": mdd_b,
        "n_months": len(a),
        "go": go,
    }


# ---------------------------------------------------------------------------
# printing
# ---------------------------------------------------------------------------
def _fmt_pct(x: float) -> str:
    return "  n/a " if x is None or np.isnan(x) else f"{x * 100:+7.2f}%"


def _fmt_num(x: float) -> str:
    return " n/a " if x is None or np.isnan(x) else f"{x:6.2f}"


def print_table(rows: list[dict]) -> None:
    header = (
        f"{'scope':<18} {'mon':>4} "
        f"{'cumA':>9} {'cumB':>9} {'ShpA':>7} {'ShpB':>7} "
        f"{'mddA':>9} {'mddB':>9}  verdict"
    )
    print("\n" + "=" * len(header))
    print(
        "ETF-SELECTION SANITY BACKTEST  —  A=risk-adj-momentum   "
        "B=PIT-dollar-volume(size)   (net of 10bps)"
    )
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for r in rows:
        verdict = "GO " if r["go"] else "no-go"
        print(
            f"{r['label']:<18} {r['n_months']:>4} "
            f"{_fmt_pct(r['cum_a'])} {_fmt_pct(r['cum_b'])} "
            f"{_fmt_num(r['shp_a'])} {_fmt_num(r['shp_b'])} "
            f"{_fmt_pct(r['mdd_a'])} {_fmt_pct(r['mdd_b'])}  {verdict}"
        )
    print("=" * len(header))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=_parse_date, default=_parse_date("2019-01-01"))
    ap.add_argument("--end", type=_parse_date, default=_parse_date("2025-12-31"))
    ap.add_argument("--top-k", type=int, default=3, dest="top_k")
    ap.add_argument("--w-vol", type=float, default=0.4, dest="w_vol")
    args = ap.parse_args()

    logger.info(
        "ETF-selection sanity backtest: %s -> %s, K=%d, w_vol=%.2f",
        args.start, args.end, args.top_k, args.w_vol,
    )

    universe = load_heterogeneous_universe()
    all_tickers = sorted({m["ticker"] for ms in universe.values() for m in ms})
    logger.info(
        "Heterogeneous universe: %d ETFs across %s",
        len(all_tickers), ", ".join(universe.keys()),
    )

    logger.info("Fetching daily OHLCV (close + volume) via pykrx (cached) ...")
    try:
        returns, dollar_volume = fetch_returns_and_dollar_volume(
            all_tickers, args.start, args.end, cache_path=str(CACHE_PATH)
        )
    except Exception as e:  # noqa: BLE001
        logger.error("OHLCV fetch raised %s: %s", type(e).__name__, e)
        returns, dollar_volume = pd.DataFrame(), pd.DataFrame()

    if returns is None or returns.empty:
        print(
            "\nDATA UNAVAILABLE — cannot run live backtest.\n"
            "  fetch_etf_ohlcv_batch returned no data (no network / pykrx blocked / "
            "empty frames).\n"
            "  The script is correct and committed; re-run where pykrx has "
            "connectivity.\n"
        )
        return 0

    returns.index = pd.DatetimeIndex(returns.index)
    returns = returns.sort_index()
    dollar_volume.index = pd.DatetimeIndex(dollar_volume.index)
    dollar_volume = dollar_volume.sort_index()
    logger.info(
        "Got returns: %d trading days x %d tickers (%s -> %s)",
        returns.shape[0], returns.shape[1],
        returns.index.min().date(), returns.index.max().date(),
    )

    rebal_dates = month_end_dates(returns.index)
    # Drop early month-ends that fall inside the warm-up window — the first
    # usable as_of must have >= WARMUP_TRADING_DAYS of history behind it.
    if len(returns.index) <= WARMUP_TRADING_DAYS:
        print(
            "\nDATA UNAVAILABLE — cannot run live backtest.\n"
            f"  Only {len(returns.index)} trading days fetched; need > "
            f"{WARMUP_TRADING_DAYS} for skip-1m 12m momentum warm-up.\n"
        )
        return 0

    warmup_cutoff = returns.index[WARMUP_TRADING_DAYS]
    rebal_dates = [d for d in rebal_dates if d >= warmup_cutoff]
    logger.info(
        "Rebalance month-ends after warm-up: %d (first usable as_of >= %s)",
        len(rebal_dates), warmup_cutoff.date(),
    )

    if len(rebal_dates) - 1 < MIN_MONTHS:
        print(
            "\nDATA UNAVAILABLE — insufficient history for a meaningful backtest.\n"
            f"  Usable rebalance months: {max(0, len(rebal_dates) - 1)} "
            f"(need >= {MIN_MONTHS}).\n"
            "  The script is correct and committed; re-run over a longer window.\n"
        )
        return 0

    # Per-bucket backtests + aggregate (equal-weight across buckets each month).
    bucket_results: list[dict] = []
    a_frames: dict[str, pd.Series] = {}
    b_frames: dict[str, pd.Series] = {}
    for bucket, members in universe.items():
        if not members:
            continue
        res = run_bucket_backtest(
            bucket, members, returns, dollar_volume, rebal_dates,
            args.top_k, args.w_vol,
        )
        bucket_results.append(res)
        a_frames[bucket] = res["a_series"]
        b_frames[bucket] = res["b_series"]
        logger.info(
            "  %-16s members=%2d  counted_months=%2d  thin_excluded=%2d  "
            "coverage[min/med/max]=%d/%d/%d",
            bucket, res["n_members"], res["n_months"], res["thin_months"],
            res["min_coverage"], res["median_coverage"], res["max_coverage"],
        )

    # Aggregate = equal-weight blend of the three bucket strategies per month.
    agg_a = pd.DataFrame(a_frames).mean(axis=1, skipna=True).dropna()
    agg_b = pd.DataFrame(b_frames).mean(axis=1, skipna=True).dropna()

    rows: list[dict] = []
    for res in bucket_results:
        if res["n_months"] == 0:
            logger.warning("  %s: no usable months (thin coverage) — skipped in table",
                           res["bucket"])
            continue
        rows.append(summarize(res["bucket"], res["a_series"], res["b_series"]))
    agg_row = summarize("AGGREGATE", agg_a, agg_b)
    rows.append(agg_row)

    print_table(rows)

    # Coverage honesty block. `counted_months` are the months that clear the
    # >= top_k+1 eligibility bar and feed the verdict; `thin_excluded` are
    # months with 2..top_k eligible (A and B forced to overlap) reported here
    # but kept OUT of the headline series.
    print(
        "\nCOVERAGE (PIT-eligible ETFs = listed & full skip-1m 12m history "
        "at each rebalance):"
    )
    for res in bucket_results:
        print(
            f"  {res['bucket']:<16} members={res['n_members']:>2}  "
            f"counted_months={res['n_months']:>2}  "
            f"thin_excluded={res['thin_months']:>2}  "
            f"eligible min/median/max = "
            f"{res['min_coverage']}/{res['median_coverage']}/{res['max_coverage']}"
        )
    total_thin = sum(r["thin_months"] for r in bucket_results)
    print(
        f"  Thin months (2..{args.top_k} eligible, A/B forced to overlap) are "
        f"EXCLUDED from the verdict: {total_thin} total across buckets."
    )
    thin = [r for r in bucket_results if r["min_coverage"] < args.top_k + 1]
    if thin:
        print(
            "  NOTE: some rebalances were thin in "
            + ", ".join(r["bucket"] for r in thin)
            + f" (eligible < top_k+1={args.top_k + 1}) — those months are not in "
            "the A-vs-B series above."
        )

    print(
        f"\nVERDICT: {'GO' if agg_row['go'] else 'NO-GO'}  "
        f"(aggregate, K={args.top_k}, w_vol={args.w_vol}, net of {TURNOVER_COST_BPS:.0f}bps)"
    )
    print(
        "  GO criterion = momentum(A) beats PIT-size(B) on cumulative return AND "
        f"Sharpe, AND MDD_A <= MDD_B + {MDD_TOLERANCE_PP * 100:.0f}pp."
    )
    print(
        "  B = trailing-60d mean dollar-volume (point-in-time), NOT static "
        "present-day AUM (look-ahead removed)."
    )
    if agg_row["go"]:
        print(
            "  -> Risk-adjusted-momentum selection beat the PIT size/liquidity "
            "benchmark out-of-sample. Sanity check supports the hybrid."
        )
    else:
        why = []
        if not (agg_row["cum_a"] > agg_row["cum_b"]):
            why.append("cumret(A)<=cumret(B)")
        if not (agg_row["shp_a"] > agg_row["shp_b"]):
            why.append("Sharpe(A)<=Sharpe(B)")
        if not (
            np.isnan(agg_row["mdd_a"]) or np.isnan(agg_row["mdd_b"])
            or agg_row["mdd_a"] <= agg_row["mdd_b"] + MDD_TOLERANCE_PP
        ):
            why.append("MDD(A) materially worse")
        print(
            "  -> Momentum selection did NOT clear the bar ("
            + "; ".join(why) + "). Treat the hybrid as unproven on this window."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
