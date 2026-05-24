"""End-to-end historical factor z + bucket returns generation (C5).

Pipeline (Linux-first per plan; macOS arm64 verified 2026-05-24):
1. Fetch all raw series → backtest/historical/raw/
2. Aggregate to quarterly indicator panel
3. For each quarter, build Stage 1 instance
4. Run compute_all_factors(state, mode='historical')
5. Compute bucket returns (KRW basis)
6. Join into HistoricalSample-equivalent records
7. Save to backtest/historical/*.parquet

Usage:
    FRED_API_KEY=... uv run python scripts/generate_historical_factor_z.py \\
        --start 1991-01-01 --end 2024-09-30 \\
        --output-dir backtest/historical
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd

load_dotenv()

from tradingagents.backtest.historical.aggregate import assemble_quarterly_panel
from tradingagents.backtest.historical.bucket_returns import (
    BUCKETS_5, compute_bucket_returns_quarterly,
)
from tradingagents.backtest.historical.fetcher_alfred import (
    ALFRED_SERIES, fetch_alfred_vintage_quarterly,
)
from tradingagents.backtest.historical.fetcher_fred import (
    FRED_QUARTERLY_SERIES, fetch_fred_latest,
)
from tradingagents.backtest.historical.fetcher_pykrx import (
    fetch_foreign_flow_monthly, fetch_kospi200_valuation_monthly,
)
from tradingagents.backtest.historical.fetcher_yfinance import (
    YFINANCE_TICKERS, fetch_yfinance_daily,
)
from tradingagents.backtest.historical.stage1_builder import build_historical_stage1
from tradingagents.skills.research.factor_estimators import compute_all_factors

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="1991-01-01")
    ap.add_argument("--end", default="2024-09-30")
    ap.add_argument("--output-dir", default="backtest/historical")
    ap.add_argument("--raw-dir", default="backtest/historical/raw")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="Skip fetch (assume cache present)")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. Fetch all raw series ----
    if not args.skip_fetch:
        logger.info("Step 1a: FRED latest-vintage (%s series)", len(FRED_QUARTERLY_SERIES))
        for sid in FRED_QUARTERLY_SERIES:
            try:
                fetch_fred_latest(sid, start, end, cache_dir=raw_dir / "fred")
            except Exception as e:
                logger.warning("FRED %s fetch failed: %s — continuing", sid, e)

        logger.info("Step 1b: ALFRED vintage (%s series, ~9.5min)", len(ALFRED_SERIES))
        for sid in ALFRED_SERIES:
            try:
                fetch_alfred_vintage_quarterly(
                    sid, start, end, cache_dir=raw_dir / "fred_alfred",
                )
            except Exception as e:
                logger.warning("ALFRED %s fetch failed: %s — continuing", sid, e)

        logger.info("Step 1c: yfinance (%s tickers)", len(YFINANCE_TICKERS))
        for ticker in YFINANCE_TICKERS:
            try:
                fetch_yfinance_daily(ticker, start, end, cache_dir=raw_dir / "yfinance")
            except Exception as e:
                logger.warning("yfinance %s fetch failed: %s — continuing", ticker, e)

        logger.info("Step 1d: pykrx KOSPI200 valuation (monthly)")
        try:
            fetch_kospi200_valuation_monthly(
                max(start, date(2001, 1, 1)), end, cache_dir=raw_dir / "pykrx",
            )
        except Exception as e:
            logger.warning("pykrx KOSPI200 valuation fetch failed: %s", e)

        logger.info("Step 1e: pykrx foreign flow (monthly)")
        try:
            fetch_foreign_flow_monthly(
                max(start, date(2003, 1, 1)), end, cache_dir=raw_dir / "pykrx",
            )
        except Exception as e:
            logger.warning("pykrx foreign flow fetch failed: %s", e)

    # ---- 2. Aggregate ----
    logger.info("Step 2: assembling quarterly indicator panel")
    panel = assemble_quarterly_panel(start=start, end=end, raw_dir=raw_dir)
    panel_path = output_dir / "quarterly_indicators.parquet"
    panel.to_parquet(panel_path)
    logger.info("Saved %s rows × %s columns to %s", *panel.shape, panel_path)

    # ---- 3. Bucket returns (KRW basis) ----
    logger.info("Step 3: computing bucket returns (KRW basis)")
    bucket_returns = compute_bucket_returns_quarterly(
        start=start, end=end, raw_dir=raw_dir, basis="KRW",
    )
    br_path = output_dir / "bucket_returns.parquet"
    bucket_returns.to_parquet(br_path)
    logger.info("Saved bucket returns %s rows to %s", len(bucket_returns), br_path)

    # ---- 4-5. Per-quarter factor z reconstruction ----
    logger.info("Step 4-5: per-quarter factor z reconstruction (mode='historical')")
    factor_records = []
    confidence_records = []
    for as_of_ts in panel.index:
        as_of_date = as_of_ts.date() if hasattr(as_of_ts, "date") else as_of_ts
        try:
            state = build_historical_stage1(as_of_date, panel)
            scores = compute_all_factors(state, mode="historical")
            factor_records.append({
                "quarter_end": as_of_ts,
                "growth_surprise": scores.growth_surprise.z_score,
                "inflation_surprise": scores.inflation_surprise.z_score,
                "real_rate": scores.real_rate.z_score,
                "term_premium": scores.term_premium.z_score,
                "credit_cycle": scores.credit_cycle.z_score,
                "krw_regime": scores.krw_regime.z_score,
                "equity_vol_regime": scores.equity_vol_regime.z_score,
                "valuation": scores.valuation.z_score,
                "liquidity_regime": scores.liquidity_regime.z_score,
            })
            confidence_records.append({
                "quarter_end": as_of_ts,
                "growth_surprise_conf": scores.growth_surprise.confidence,
                "inflation_surprise_conf": scores.inflation_surprise.confidence,
                "real_rate_conf": scores.real_rate.confidence,
                "term_premium_conf": scores.term_premium.confidence,
                "credit_cycle_conf": scores.credit_cycle.confidence,
                "krw_regime_conf": scores.krw_regime.confidence,
                "equity_vol_regime_conf": scores.equity_vol_regime.confidence,
                "valuation_conf": scores.valuation.confidence,
                "liquidity_regime_conf": scores.liquidity_regime.confidence,
            })
        except Exception as e:
            logger.error("Quarter %s factor z compute failed: %s", as_of_date, e)

    factor_z_df = pd.DataFrame(factor_records).set_index("quarter_end")
    conf_df = pd.DataFrame(confidence_records).set_index("quarter_end")
    combined = factor_z_df.join(conf_df)
    fz_path = output_dir / "factor_z.parquet"
    combined.to_parquet(fz_path)
    logger.info("Saved factor z %s rows × %s columns to %s", *combined.shape, fz_path)

    # ---- 6. Samples.parquet — joined factor z + bucket_returns_next ----
    logger.info("Step 6: assembling HistoricalSample equivalents")
    bucket_returns_next = bucket_returns.shift(-1)
    samples_df = combined.join(
        bucket_returns_next.rename(columns={b: f"next_{b}" for b in BUCKETS_5}),
        how="inner",
    )
    samples_df = samples_df.dropna(
        subset=[f"next_{b}" for b in ("global_equity", "bond", "cash_mmf")]
    )
    samples_path = output_dir / "samples.parquet"
    samples_df.to_parquet(samples_path)
    logger.info("Saved samples %s rows × %s columns to %s",
                *samples_df.shape, samples_path)

    print(json.dumps({
        "panel_rows": int(len(panel)),
        "factor_z_rows": int(len(combined)),
        "bucket_returns_rows": int(len(bucket_returns)),
        "samples_rows": int(len(samples_df)),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
