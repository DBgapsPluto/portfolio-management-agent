"""Tier 2 validation: VIF + effective df + walk-forward OOS Sharpe.

Acceptance: VIF <= 5, effective df <= N/3, walk-forward OOS Sharpe > 1.171.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.skills.research.factor_calibration import (
    compute_effective_df, compute_vif_matrix, walk_forward,
)
from tradingagents.skills.research.factor_to_bucket import FACTORS


def validate(samples, lambda_global, out_dir: Path):
    vif = compute_vif_matrix(samples, list(FACTORS))
    vif_max = float(np.nanmax(vif.values))
    vif_pass = vif_max <= 5.0

    X = np.array([[s.factor_z.get(f, 0.0) for f in FACTORS] for s in samples])
    # replace NaN with 0 for design matrix (factors not yet available)
    X = np.nan_to_num(X, nan=0.0)
    eff_df = compute_effective_df(X, lambda_global)
    n = len(samples)
    df_pass = eff_df <= n / 3

    folds = walk_forward(samples, initial_train_size=80, test_window=8, shrinkage=lambda_global)
    median_oos = float(np.median([f.oos_sharpe for f in folds])) if folds else float("nan")
    sharpe_pass = bool(median_oos > 1.171)

    report = {
        "vif_max": vif_max, "vif_pass": bool(vif_pass),
        "effective_df": eff_df, "n_samples": n, "df_threshold": n / 3,
        "df_pass": bool(df_pass),
        "median_oos_sharpe": median_oos, "sharpe_pass": sharpe_pass,
        "overall_pass": bool(vif_pass and df_pass and sharpe_pass),
    }
    (out_dir / "validation_report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "validation_report.md").write_text(_format_md(report))
    return report


def _format_md(r):
    chk = lambda b: "PASS" if b else "FAIL"
    return (
        "# Tier 2 Calibration Validation\n\n"
        "| Metric | Value | Threshold | Pass |\n|---|---|---|---|\n"
        f"| VIF max | {r['vif_max']:.2f} | <= 5.0 | {chk(r['vif_pass'])} |\n"
        f"| Effective df | {r['effective_df']:.1f} | <= {r['df_threshold']:.1f} | {chk(r['df_pass'])} |\n"
        f"| Median OOS Sharpe | {r['median_oos_sharpe']:.3f} | > 1.171 | {chk(r['sharpe_pass'])} |\n\n"
        f"**Overall**: {chk(r['overall_pass'])}\n"
    )


if __name__ == "__main__":
    from scripts.calibrate_factor_model_8b import load_samples_8b
    out_dir = Path("artifacts/" + pd.Timestamp.today().strftime("%Y-%m-%d") + "/tier2_calibration")
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = load_samples_8b()
    report = validate(samples, 2.0, out_dir)
    print(json.dumps(report, indent=2))
