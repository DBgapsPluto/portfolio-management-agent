"""Tier 2 validation: VIF + honest overfitting metric + walk-forward OOS Sharpe.

Acceptance gates:
  - VIF max <= 5.0
  - sample_per_param >= 1.5  (n_samples / n_free_beta_params; honest overfitting gate)
  - walk-forward OOS Sharpe > 1.171  (uses hierarchical objective -matches deployed β)

collinearity_df (factor-z design effective df) is retained as a DIAGNOSTIC only,
not a gate -df <= rank(X) = 12, structurally always passes N/3, so it gives no
overfitting signal for the 73-param hierarchical fit.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.skills.research.factor_calibration import (
    HARD_ZERO_CELLS, compute_effective_df, compute_vif_matrix,
)
from tradingagents.skills.research.factor_calibration_hierarchical import (
    walk_forward_hierarchical,
)
from tradingagents.skills.research.factor_to_bucket import BUCKETS, FACTORS


def validate(samples, lambda_global, out_dir: Path, lambda_family: float = 0.5):
    vif = compute_vif_matrix(samples, list(FACTORS))
    vif_max = float(np.nanmax(vif.values))
    vif_pass = vif_max <= 5.0

    # Collinearity diagnostic (NOT an overfitting gate): factor-z design df.
    # df <= rank(X) = 12 -structurally always <= N/3; kept for diagnostic use only.
    X = np.nan_to_num(
        np.array([[s.factor_z.get(f, 0.0) for f in FACTORS] for s in samples]),
        nan=0.0,
    )
    collinearity_df = compute_effective_df(X, lambda_global)

    # HONEST overfitting metric: free β params vs effective sample size.
    # 96 cells - 23 hard-zero cells = 73 free β params.
    n_free_beta = len(FACTORS) * len(BUCKETS) - len(HARD_ZERO_CELLS)  # 96 - 23 = 73
    n = len(samples)
    sample_per_param = n / n_free_beta if n_free_beta else float("inf")
    # Gate: with hierarchical shrinkage we accept sample/param >= 1.5
    # (shrinkage reduces effective df below raw count; below 1.5 even shrinkage is unsafe).
    overfit_pass = sample_per_param >= 1.5

    # OOS Sharpe measured on the HIERARCHICAL objective -matches the deployed β.
    folds = walk_forward_hierarchical(
        samples, initial_train_size=80, test_window=8,
        lambda_global=lambda_global, lambda_family=lambda_family,
    )
    median_oos = float(np.median([f.oos_sharpe for f in folds])) if folds else float("nan")
    sharpe_pass = bool(median_oos > 1.171)

    report = {
        "vif_max": vif_max, "vif_pass": bool(vif_pass),
        "collinearity_df": collinearity_df,            # diagnostic only, not a gate
        "n_free_beta_params": n_free_beta,
        "n_samples": n,
        "sample_per_param": sample_per_param,
        "overfit_pass": bool(overfit_pass),
        "median_oos_sharpe": median_oos, "sharpe_pass": sharpe_pass,
        "overall_pass": bool(vif_pass and overfit_pass and sharpe_pass),
    }
    (out_dir / "validation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "validation_report.md").write_text(_format_md(report), encoding="utf-8")
    return report


def _format_md(r):
    chk = lambda b: "PASS" if b else "FAIL"
    return (
        "# Tier 2 Calibration Validation\n\n"
        "| Metric | Value | Threshold | Pass |\n|---|---|---|---|\n"
        f"| VIF max | {r['vif_max']:.2f} | <= 5.0 | {chk(r['vif_pass'])} |\n"
        f"| factor-z collinearity df (diagnostic, not a gate) | {r['collinearity_df']:.1f} | - | - |\n"
        f"| Free beta params | {r['n_free_beta_params']} | - | - |\n"
        f"| Samples | {r['n_samples']} | - | - |\n"
        f"| sample / param | {r['sample_per_param']:.2f} | >= 1.5 | {chk(r['overfit_pass'])} |\n"
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
