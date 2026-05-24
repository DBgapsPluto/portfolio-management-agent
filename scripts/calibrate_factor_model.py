"""Walk-forward calibration + shrinkage grid + acceptance gate (PR2a C6/C7).

Replaces the PR1 synthetic-data script. PR2a 의 samples.parquet (C5 산출) 를
input 으로 받아 5 shrinkage × 7 fold = 35 calibration runs 실행 + acceptance
gate (Critical 3 strict-default 5-condition) 평가.

End-to-end:
1. Load samples.parquet → HistoricalSample list
2. Walk-forward (initial_train=80, test=7) → 7 folds
3. Shrinkage grid loop {0.1, 0.3, 0.5, 1.0, 2.0} × 7 folds = 35 runs
4. Prior baseline OOS Sharpe (no-fit walk-forward)
5. Equi-weight β=0 baseline OOS Sharpe (informational, M3)
6. Vintage sanity (latest-vintage β 와 비교) — opt-in if 2nd samples 제공
7. Learning sensitivity diagnostic |β_0.1 - β_2.0|_avg (M2)
8. Best shrinkage selection (mean_oos - 0.25 × std_oos, M5)
9. Acceptance gate evaluation → validation_report.json

Usage:
    uv run python scripts/calibrate_factor_model.py \\
        --samples backtest/historical/samples.parquet \\
        --output-dir artifacts/<run-date>/calibration_runs \\
        [--latest-vintage-samples backtest/historical/samples_latest_vintage.parquet]
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.backtest.acceptance import evaluate_acceptance
from tradingagents.skills.research.factor_calibration import (
    HistoricalSample, aggregate_median_beta, compute_sharpe,
    simulate_portfolio_returns, walk_forward,
)
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS, FACTORS, INITIAL_BETA,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


SHRINKAGE_GRID: list[float] = [0.1, 0.3, 0.5, 1.0, 2.0]


def load_samples_from_parquet(path: Path) -> list[HistoricalSample]:
    """samples.parquet → list[HistoricalSample]."""
    df = pd.read_parquet(path)
    samples = []
    for idx, row in df.iterrows():
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
        factor_z = {f: float(row[f]) for f in FACTORS if f in row}
        bucket_returns_next = {
            b: float(row.get(f"next_{b}", np.nan)) for b in BUCKETS
        }
        if all(pd.isna(v) for v in bucket_returns_next.values()):
            continue
        samples.append(HistoricalSample(
            date=date_str,
            factor_z=factor_z,
            bucket_returns_next=bucket_returns_next,
        ))
    logger.info("Loaded %s samples", len(samples))
    return samples


def compute_prior_baseline_oos(samples, initial_train_size=80, test_window=7):
    """Hand-coded INITIAL_BETA 의 walk-forward OOS Sharpe (no fitting)."""
    n = len(samples)
    oos_sharpes = []
    for end in range(initial_train_size, n - test_window + 1, test_window):
        test = samples[end : end + test_window]
        test_returns = simulate_portfolio_returns(test, INITIAL_BETA)
        oos_sharpes.append(compute_sharpe(test_returns))
    return float(np.mean(oos_sharpes)), oos_sharpes


def compute_equi_weight_baseline_oos(samples, initial_train_size=80, test_window=7):
    """β=0 (all weight 0, factor model returns baseline only) 의 OOS Sharpe."""
    zero_beta = {k: 0.0 for k in INITIAL_BETA.keys()}
    n = len(samples)
    oos_sharpes = []
    for end in range(initial_train_size, n - test_window + 1, test_window):
        test = samples[end : end + test_window]
        test_returns = simulate_portfolio_returns(test, zero_beta)
        oos_sharpes.append(compute_sharpe(test_returns))
    return float(np.mean(oos_sharpes)), oos_sharpes


def run_shrinkage_grid(
    samples, output_dir: Path,
    initial_train_size: int = 80, test_window: int = 7,
):
    """5 shrinkage × N fold runs."""
    per_fold_dir = output_dir / "per_fold"
    per_fold_dir.mkdir(parents=True, exist_ok=True)

    per_shrinkage_results = {}
    for s in SHRINKAGE_GRID:
        logger.info("Shrinkage %s: running walk-forward", s)
        folds = walk_forward(
            samples, initial_train_size=initial_train_size,
            test_window=test_window, shrinkage=s, prior_beta=INITIAL_BETA,
        )
        for fold in folds:
            with open(per_fold_dir / f"shrinkage_{s}_fold_{fold.fold_idx}.json", "w") as f:
                json.dump({
                    "shrinkage": s, "fold_idx": fold.fold_idx,
                    "train_end_idx": fold.train_end_idx,
                    "test_start_idx": fold.test_start_idx,
                    "test_end_idx": fold.test_end_idx,
                    "in_sample_sharpe": fold.in_sample_sharpe,
                    "oos_sharpe": fold.oos_sharpe,
                    "beta": {f"{k[0]}_{k[1]}": v for k, v in fold.beta.items()},
                }, f, indent=2)
        median_beta = aggregate_median_beta(folds)
        per_shrinkage_results[str(s)] = {
            "median_beta": {f"{k[0]}_{k[1]}": v for k, v in median_beta.items()},
            "median_beta_tuples": median_beta,
            "mean_is": float(np.mean([f.in_sample_sharpe for f in folds])),
            "mean_oos": float(np.mean([f.oos_sharpe for f in folds])),
            "std_oos": float(np.std([f.oos_sharpe for f in folds], ddof=1)) if len(folds) > 1 else 0.0,
            "per_fold_oos": [f.oos_sharpe for f in folds],
            "per_fold_is": [f.in_sample_sharpe for f in folds],
            "folds": folds,
        }

    serializable = {}
    for s_key, r in per_shrinkage_results.items():
        serializable[s_key] = {
            k: v for k, v in r.items()
            if k not in ("median_beta_tuples", "folds")
        }
    with open(output_dir / "per_shrinkage_summary.json", "w") as f:
        json.dump(serializable, f, indent=2)
    return per_shrinkage_results


def select_best_shrinkage(per_shrinkage_results):
    """Best by mean_oos - 0.25 × std_oos (M5). Tie-break: smaller |IS-OOS|."""
    scores = {}
    for s_str, r in per_shrinkage_results.items():
        score = r["mean_oos"] - 0.25 * r["std_oos"]
        tiebreak = -abs(r["mean_is"] - r["mean_oos"])
        scores[s_str] = (score, tiebreak)
    best = max(scores, key=lambda k: scores[k])
    return best, per_shrinkage_results[best]


def compute_learning_sensitivity(per_shrinkage_results):
    """|β_0.1 - β_2.0|_avg (M2)."""
    b1 = per_shrinkage_results["0.1"]["median_beta_tuples"]
    b2 = per_shrinkage_results["2.0"]["median_beta_tuples"]
    diffs = [abs(b1[k] - b2[k]) for k in b1.keys() if k in b2]
    return float(np.mean(diffs)) if diffs else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--latest-vintage-samples", default=None)
    ap.add_argument("--initial-train-size", type=int, default=80)
    ap.add_argument("--test-window", type=int, default=7)
    args = ap.parse_args()

    samples = load_samples_from_parquet(Path(args.samples))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Running shrinkage grid: %s × test_window=%s",
                SHRINKAGE_GRID, args.test_window)
    results = run_shrinkage_grid(samples, output_dir,
                                  initial_train_size=args.initial_train_size,
                                  test_window=args.test_window)

    logger.info("Computing prior baseline OOS Sharpe")
    prior_oos_mean, prior_per_fold = compute_prior_baseline_oos(
        samples, args.initial_train_size, args.test_window,
    )

    logger.info("Computing equi-weight (β=0) baseline OOS Sharpe")
    equi_oos_mean, equi_per_fold = compute_equi_weight_baseline_oos(
        samples, args.initial_train_size, args.test_window,
    )
    with open(output_dir / "equi_weight_baseline.json", "w") as f:
        json.dump({
            "mean_oos_sharpe": equi_oos_mean,
            "per_fold_oos": equi_per_fold,
        }, f, indent=2)

    best_shr, best_result = select_best_shrinkage(results)
    logger.info("Best shrinkage: %s (score %.4f)", best_shr,
                best_result["mean_oos"] - 0.25 * best_result["std_oos"])
    with open(output_dir / "best_shrinkage.json", "w") as f:
        json.dump({
            "shrinkage": float(best_shr),
            "mean_is_sharpe": best_result["mean_is"],
            "mean_oos_sharpe": best_result["mean_oos"],
            "std_oos_sharpe": best_result["std_oos"],
            "median_beta": best_result["median_beta"],
        }, f, indent=2)

    vintage_sanity = {"pass": True, "skipped": True,
                      "reason": "no latest-vintage samples provided"}
    if args.latest_vintage_samples:
        logger.info("Vintage sanity check")
        lv_samples = load_samples_from_parquet(Path(args.latest_vintage_samples))
        lv_results = run_shrinkage_grid(
            lv_samples, output_dir / "vintage_latest",
            args.initial_train_size, args.test_window,
        )
        _, lv_best = select_best_shrinkage(lv_results)
        b_vintage = best_result["median_beta_tuples"]
        b_latest = lv_best["median_beta_tuples"]
        diffs = [abs(b_vintage[k] - b_latest[k]) for k in b_vintage.keys() if k in b_latest]
        avg_diff = float(np.mean(diffs)) if diffs else 0.0
        vintage_sanity = {
            "pass": avg_diff < 0.05,
            "avg_abs_diff": avg_diff,
            "skipped": False,
        }
    with open(output_dir / "vintage_sanity.json", "w") as f:
        json.dump(vintage_sanity, f, indent=2)

    sens = compute_learning_sensitivity(results)
    with open(output_dir / "learning_sensitivity.json", "w") as f:
        json.dump({
            "avg_abs_diff_shrinkage_0.1_vs_2.0": sens,
            "warning_if_below": 0.01,
            "warning_triggered": sens < 0.01,
        }, f, indent=2)

    logger.info("Evaluating acceptance gate")
    verdict = evaluate_acceptance(
        calibrated_beta=best_result["median_beta_tuples"],
        calibrated_folds=best_result["folds"],
        prior_oos_per_fold=prior_per_fold,
        prior_oos_mean=prior_oos_mean,
        equi_oos_mean=equi_oos_mean,
        vintage_sanity=vintage_sanity,
        learning_sensitivity=sens,
    )
    with open(output_dir / "validation_report.json", "w") as f:
        json.dump({
            "pass": verdict["pass"],
            "conditions": verdict["conditions"],
            "best_shrinkage": float(best_shr),
            "mean_is_sharpe": verdict["mean_is_sharpe"],
            "mean_oos_sharpe": verdict["mean_oos_sharpe"],
            "prior_oos_sharpe": prior_oos_mean,
            "equi_weight_oos_sharpe": equi_oos_mean,
            "improvement_delta": verdict["mean_oos_sharpe"] - prior_oos_mean,
            "paired_t_p": verdict["paired_t_p"],
            "diagnostic": verdict["diagnostic"],
            "calibrated_beta": {f"{k[0]}_{k[1]}": v
                                for k, v in best_result["median_beta_tuples"].items()},
        }, f, indent=2)

    print(json.dumps({
        "pass": verdict["pass"],
        "best_shrinkage": float(best_shr),
        "mean_oos_sharpe": verdict["mean_oos_sharpe"],
        "prior_oos_sharpe": prior_oos_mean,
        "improvement_delta": verdict["mean_oos_sharpe"] - prior_oos_mean,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
