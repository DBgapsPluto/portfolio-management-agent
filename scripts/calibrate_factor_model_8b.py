"""Tier 2 calibration entry: 8-bucket × 12-factor hierarchical fit.

Run (requires backtest/historical/samples_8b.parquet — see build_samples_8b):
  python scripts/calibrate_factor_model_8b.py --grid

Outputs to artifacts/<DATE>/tier2_calibration/:
  calibrated_beta.json, calibrated_mu.json, calibrated_tips_beta.json,
  shrinkage_grid_summary.json

NOTE: samples_8b.parquet requires regenerated Stage 1 historical data
(12-factor z + 8-bucket next-quarter returns). When unavailable, this script
raises a clear error. The calibration FRAMEWORK is unit-tested independently
on synthetic data (test_factor_calibration_hierarchical.py).
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.skills.research.factor_calibration import (
    HistoricalSample, walk_forward,
)
from tradingagents.skills.research.factor_calibration_hierarchical import (
    staggered_calibration,
)
from tradingagents.skills.research.factor_calibration_tips import (
    hybrid_calibration_tips,
)
from tradingagents.skills.research.factor_to_bucket import (
    FACTORS, BUCKETS, INITIAL_BETA,
)

logger = logging.getLogger(__name__)

SAMPLES_8B_PATH = Path("backtest/historical/samples_8b.parquet")

# Map FACTORS canonical names → samples parquet column names (factor z).
# The historical samples store z under short names; adjust if your parquet differs.
_FACTOR_COL = {
    "F1_growth": "growth_surprise",
    "F2_inflation": "inflation_surprise",
    "F3_real_rate": "real_rate",
    "F4_term_premium": "term_premium",
    "F5_credit_cycle": "credit_cycle",
    "F6_krw_regime": "krw_regime",
    "F7_equity_vol_regime": "equity_vol_regime",
    "F8_valuation": "valuation",
    "F9_market_dispersion": "market_dispersion",
    "F10_systemic_liquidity": "systemic_liquidity",
    "F11_earnings_revision": "earnings_revision",
    "F12_china_credit_impulse": "china_credit_impulse",
}


def load_samples_8b(samples_parquet: Path = SAMPLES_8B_PATH) -> list[HistoricalSample]:
    """Load 8-bucket samples (12-factor z + next-quarter 8-bucket returns).

    Raises FileNotFoundError with guidance if the parquet is absent.
    Expected columns: factor z (short or F-prefixed names) + ret_next_<bucket>.
    """
    if not samples_parquet.exists():
        raise FileNotFoundError(
            f"{samples_parquet} not found. Tier 2 calibration needs regenerated "
            f"Stage 1 historical data (12-factor z + 8-bucket next returns). "
            f"This requires pykrx (KRX login) + ECOS + FRED full-history fetch "
            f"(Issue #18 data availability). The calibration framework itself is "
            f"unit-tested on synthetic data; this script runs once real data exists."
        )
    df = pd.read_parquet(samples_parquet)
    samples = []
    for idx, row in df.iterrows():
        fz = {}
        for f in FACTORS:
            col = f if f in df.columns else _FACTOR_COL.get(f, f)
            fz[f] = float(row[col]) if col in df.columns and pd.notna(row[col]) else float("nan")
        br = {b: float(row[f"ret_next_{b}"]) for b in BUCKETS if f"ret_next_{b}" in df.columns}
        tips = (
            float(row["tips_share_realized"])
            if "tips_share_realized" in df.columns and pd.notna(row.get("tips_share_realized"))
            else None
        )
        samples.append(HistoricalSample(
            date=str(idx), factor_z=fz, bucket_returns_next=br, tips_share_realized=tips,
        ))
    return samples


def grid_search_shrinkage(samples, prior_beta):
    lambda_global_grid = [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]
    lambda_family_grid = [0.1, 0.3, 1.0]
    results = []
    for lg in lambda_global_grid:
        for lf in lambda_family_grid:
            folds = walk_forward(samples, initial_train_size=80, test_window=8,
                                 shrinkage=lg, prior_beta=prior_beta)
            median_oos = float(np.median([f.oos_sharpe for f in folds])) if folds else float("nan")
            results.append({"lambda_global": lg, "lambda_family": lf,
                            "median_oos_sharpe": median_oos, "n_folds": len(folds)})
    return pd.DataFrame(results)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid", action="store_true", help="Run shrinkage grid")
    parser.add_argument("--out-dir", type=str, default=None)
    args = parser.parse_args()
    out_dir = Path(args.out_dir or f"artifacts/{date.today().isoformat()}/tier2_calibration")
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = load_samples_8b()
    if args.grid:
        grid = grid_search_shrinkage(samples, INITIAL_BETA)
        grid.to_json(out_dir / "shrinkage_grid_summary.json", orient="records", indent=2)
        best = grid.loc[grid["median_oos_sharpe"].idxmax()]
        lg, lf = float(best["lambda_global"]), float(best["lambda_family"])
    else:
        lg, lf = 2.0, 0.5

    pre = [s for s in samples if s.date < "2010-01-01"]
    post = [s for s in samples if s.date >= "2010-01-01"]
    beta, mu = staggered_calibration(pre, post, lambda_global=lg, lambda_family=lf)
    tips_beta, _ = hybrid_calibration_tips(samples, lambda_global=lg)

    (out_dir / "calibrated_beta.json").write_text(
        json.dumps({f"{k[0]}|{k[1]}": v for k, v in beta.items()}, indent=2))
    (out_dir / "calibrated_mu.json").write_text(
        json.dumps({f"{k[0]}|{k[1]}": v for k, v in mu.items()}, indent=2))
    (out_dir / "calibrated_tips_beta.json").write_text(json.dumps(tips_beta, indent=2))
    print(f"Calibration complete. Output: {out_dir}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
