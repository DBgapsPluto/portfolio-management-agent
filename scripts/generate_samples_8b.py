"""Generate backtest/historical/samples_8b.parquet for Tier 2 calibration.

Joins, per quarter_end:
  - 12 reformed factor z  (compute_all_factors(state, mode='historical'))
  - next-quarter 8-bucket returns  (bucket_returns_8b shifted -1)

IMPORTANT VALIDITY CAVEAT (read before trusting calibration output):
The historical Stage 1 panel (quarterly_indicators.parquet) was only PARTIALLY
re-wired for Tier 0. It carries the legacy ~37-indicator set + shiller_cape, but
NOT the new reformed inputs (ACM/THREEFYTP10 term premium, INDPRO/Real-PCE growth,
GZ-EBP systemic liquidity, GPR, BIS China credit). Consequently:
  * F1..F10 are computed from the reformed estimators' GRACEFUL-DEGRADATION
    fallbacks on legacy columns (proxy-z), NOT the true reformed series.
  * F11 earnings_revision -> ~constant 0 historically (no earnings history).
  * F12 china_credit_impulse -> NaN historically (no BIS China data in panel).
So these samples support a sample/param FEASIBILITY check and a coarse vs-60/40
comparison, but NOT a fidelity-grade validation of the live 12-factor model.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd

load_dotenv()

from tradingagents.backtest.historical.stage1_builder import build_historical_stage1
from tradingagents.skills.research.factor_estimators import compute_all_factors

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_FACTOR_FIELDS = [
    "growth_surprise", "inflation_surprise", "real_rate", "term_premium",
    "credit_cycle", "krw_regime", "equity_vol_regime", "valuation",
    "market_dispersion", "systemic_liquidity", "earnings_revision",
    "china_credit_impulse",
]
_BUCKETS = [
    "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
    "kr_bond", "credit", "global_duration", "cash_mmf",
]


def _z(score) -> float:
    if score is None:
        return float("nan")
    z = getattr(score, "z_score", float("nan"))
    return float(z)


def main() -> int:
    panel = pd.read_parquet("backtest/historical/quarterly_indicators.parquet")
    bucket_ret = pd.read_parquet("backtest/historical/bucket_returns_8b.parquet")
    bucket_ret.index = pd.to_datetime(bucket_ret.index)
    next_ret = bucket_ret.shift(-1)  # next-quarter realized returns

    rows = []
    for as_of_ts in panel.index:
        as_of = as_of_ts.date() if hasattr(as_of_ts, "date") else as_of_ts
        try:
            state = build_historical_stage1(as_of, panel)
            sc = compute_all_factors(state, mode="historical")
        except Exception as e:
            logger.warning("quarter %s factor compute failed: %s", as_of, e)
            continue
        rec = {"quarter_end": as_of_ts}
        for f in _FACTOR_FIELDS:
            rec[f] = _z(getattr(sc, f, None))
        # next-quarter returns (NaN if as_of_ts not in bucket_ret index)
        if as_of_ts in next_ret.index:
            for b in _BUCKETS:
                rec[f"ret_next_{b}"] = float(next_ret.at[as_of_ts, b]) if pd.notna(next_ret.at[as_of_ts, b]) else float("nan")
        else:
            for b in _BUCKETS:
                rec[f"ret_next_{b}"] = float("nan")
        rows.append(rec)

    df = pd.DataFrame(rows).set_index("quarter_end")
    # Keep only quarters with ALL 8 next-bucket returns present (the all-available window)
    ret_cols = [f"ret_next_{b}" for b in _BUCKETS]
    before = len(df)
    df = df.dropna(subset=ret_cols)
    out = Path("backtest/historical/samples_8b.parquet")
    df.to_parquet(out)

    print(f"samples_8b: {df.shape}  {df.index.min().date()}..{df.index.max().date()}")
    print(f"  (dropped {before - len(df)} quarters lacking full 8-bucket next returns)")
    print("  factor-z non-NaN count per factor:")
    for f in _FACTOR_FIELDS:
        nn = df[f].notna().sum()
        nonconst = df[f].std()
        print(f"    {f:22s}: {nn:3d}/{len(df)} non-NaN  std={nonconst:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
