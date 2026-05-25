"""PR2b sensitivity sweep — era split + robustness penalty + sample_quality.

End-to-end:
1. Era split: split samples at 2010-01-01, calibrate each separately, β diff.
2. Robustness penalty: rerun select_best_shrinkage with {0.10, 0.50}.
3. Sample quality stratified: per-quartile mean confidence → OOS Sharpe of
   calibrated INITIAL_BETA.

Usage:
    uv run python scripts/sensitivity_sweep.py \\
        --samples backtest/historical/samples.parquet \\
        --output-dir artifacts/2026-05-25/sensitivity
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.skills.research.factor_calibration import (
    compute_sharpe,
    hybrid_calibration,
    simulate_portfolio_returns,
)
from tradingagents.skills.research.factor_to_bucket import INITIAL_BETA

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CALIBRATE_PATH = _PROJECT_ROOT / "scripts" / "calibrate_factor_model.py"
_spec = importlib.util.spec_from_file_location("calib", _CALIBRATE_PATH)
_calib_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_calib_mod)
load_samples_from_parquet = _calib_mod.load_samples_from_parquet


def era_split_sweep(samples: list, era_split_date: str = "2010-01-01") -> dict:
    """Split samples at era_split_date → calibrate each separately → β diff."""
    split_ts = pd.Timestamp(era_split_date)
    pre = [s for s in samples if pd.Timestamp(s.date) < split_ts]
    post = [s for s in samples if pd.Timestamp(s.date) >= split_ts]
    logger.info("Era split: pre %s, post %s", len(pre), len(post))

    def _best_beta(subset):
        if len(subset) < 30:
            return None, None
        beta, sharpe = hybrid_calibration(
            subset, shrinkage=2.0, prior_beta=INITIAL_BETA,
        )
        return beta, sharpe

    pre_beta, pre_sharpe = _best_beta(pre)
    post_beta, post_sharpe = _best_beta(post)

    if pre_beta is not None and post_beta is not None:
        common = set(pre_beta.keys()) & set(post_beta.keys())
        diffs = [abs(pre_beta[k] - post_beta[k]) for k in common]
        avg_diff = float(np.mean(diffs)) if diffs else 0.0
        max_diff = float(np.max(diffs)) if diffs else 0.0
    else:
        avg_diff = None
        max_diff = None

    return {
        "pre_2010_n": len(pre),
        "post_2010_n": len(post),
        "pre_2010_in_sample_sharpe": pre_sharpe,
        "post_2010_in_sample_sharpe": post_sharpe,
        "beta_avg_abs_diff_pre_vs_post": avg_diff,
        "beta_max_abs_diff_pre_vs_post": max_diff,
        "pre_2010_beta": {f"{k[0]}_{k[1]}": v for k, v in pre_beta.items()} if pre_beta else None,
        "post_2010_beta": {f"{k[0]}_{k[1]}": v for k, v in post_beta.items()} if post_beta else None,
    }


def robustness_penalty_sweep(per_shrinkage_results: dict) -> dict:
    """select_best_shrinkage 의 0.25 계수 → {0.10, 0.50} 변경 시 best 변화."""
    def best(coef: float) -> str:
        scores = {}
        for s_str, r in per_shrinkage_results.items():
            scores[s_str] = r["mean_oos"] - coef * r["std_oos"]
        return max(scores, key=lambda k: scores[k])

    return {
        "best_at_0.10": best(0.10),
        "best_at_0.25_default": best(0.25),
        "best_at_0.50": best(0.50),
        "sensitive": best(0.10) != best(0.50),
    }


def sample_quality_sweep(samples: list, samples_parquet: Path) -> dict:
    """Sample quality stratified: per-quartile OOS Sharpe of calibrated INITIAL_BETA."""
    df = pd.read_parquet(samples_parquet)
    conf_cols = [c for c in df.columns if c.endswith("_conf")]
    if not conf_cols:
        return {"error": "no *_conf columns in samples.parquet"}
    df["sample_quality"] = df[conf_cols].mean(axis=1)
    try:
        df["quality_quartile"] = pd.qcut(
            df["sample_quality"], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop",
        )
    except ValueError:
        # Too few unique values for 4 quartiles.
        return {"error": "sample_quality has too few unique values for 4 quartiles",
                "unique_count": int(df["sample_quality"].nunique()),
                "mean_quality": float(df["sample_quality"].mean())}

    out = {}
    for q in df["quality_quartile"].cat.categories:
        sub_dates = set(df.index[df["quality_quartile"] == q])
        sub_samples = [s for s in samples if pd.Timestamp(s.date) in sub_dates]
        if len(sub_samples) < 5:
            out[str(q)] = {"n": len(sub_samples), "sharpe": None}
            continue
        returns = simulate_portfolio_returns(sub_samples, INITIAL_BETA)
        out[str(q)] = {
            "n": len(sub_samples),
            "sharpe": compute_sharpe(returns),
            "mean_return": float(np.mean(returns)),
            "mean_quality": float(df[df["quality_quartile"] == q]["sample_quality"].mean()),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--per-shrinkage-summary",
                    default="artifacts/2026-05-24/calibration_runs/per_shrinkage_summary.json")
    args = ap.parse_args()

    samples = load_samples_from_parquet(Path(args.samples))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Running era split sweep")
    era = era_split_sweep(samples)
    with open(output_dir / "era_split.json", "w") as f:
        json.dump(era, f, indent=2)

    logger.info("Running robustness penalty sweep")
    if Path(args.per_shrinkage_summary).exists():
        with open(args.per_shrinkage_summary) as f:
            psr = json.load(f)
        robustness = robustness_penalty_sweep(psr)
    else:
        robustness = {"error": f"missing {args.per_shrinkage_summary}"}
    with open(output_dir / "robustness_penalty.json", "w") as f:
        json.dump(robustness, f, indent=2)

    logger.info("Running sample quality sweep")
    quality = sample_quality_sweep(samples, Path(args.samples))
    with open(output_dir / "sample_quality.json", "w") as f:
        json.dump(quality, f, indent=2, default=str)

    md = _write_markdown_report(era, robustness, quality)
    with open(output_dir / "sensitivity_report.md", "w") as f:
        f.write(md)

    print(json.dumps({
        "era_beta_avg_abs_diff": era.get("beta_avg_abs_diff_pre_vs_post"),
        "robustness_sensitive": robustness.get("sensitive"),
        "quality_result": "ok" if "error" not in quality else quality.get("error"),
    }, indent=2, default=str))
    return 0


def _write_markdown_report(era: dict, robustness: dict, quality: dict) -> str:
    lines = ["# PR2b Sensitivity Report (2026-05-25)\n"]

    lines.append("## Section 1: Era Split (pre/post 2010-01-01)\n")
    lines.append(f"- pre-2010: N={era['pre_2010_n']}, in-sample Sharpe={era['pre_2010_in_sample_sharpe']}")
    lines.append(f"- post-2010: N={era['post_2010_n']}, in-sample Sharpe={era['post_2010_in_sample_sharpe']}")
    diff = era['beta_avg_abs_diff_pre_vs_post']
    max_diff = era['beta_max_abs_diff_pre_vs_post']
    if diff is not None:
        verdict = "STABLE" if diff < 0.03 else ("MODERATE DRIFT" if diff < 0.06 else "DRIFT")
        lines.append(f"- |β_pre - β_post|_avg = **{diff:.4f}** ({verdict})")
        lines.append(f"- |β_pre - β_post|_max = {max_diff:.4f}")
    lines.append("")

    lines.append("## Section 2: Robustness Penalty {0.10, 0.25, 0.50}\n")
    if "error" in robustness:
        lines.append(f"⚠️ {robustness['error']}")
    else:
        lines.append("| Penalty coefficient | Best shrinkage |")
        lines.append("|---|---|")
        lines.append(f"| 0.10 | {robustness['best_at_0.10']} |")
        lines.append(f"| 0.25 (default) | {robustness['best_at_0.25_default']} |")
        lines.append(f"| 0.50 | {robustness['best_at_0.50']} |")
        verdict = "SENSITIVE — best shrinkage 가 계수에 의존" if robustness["sensitive"] else "STABLE — 계수 변경 무관"
        lines.append(f"\n**Verdict**: {verdict}")
    lines.append("")

    lines.append("## Section 3: Sample Quality Stratified\n")
    if "error" in quality:
        lines.append(f"⚠️ {quality['error']}")
        if "mean_quality" in quality:
            lines.append(f"   mean confidence = {quality['mean_quality']:.4f}")
            lines.append(f"   unique values = {quality.get('unique_count', 0)}")
        lines.append("   → Quartile 분류 불가 (모든 sample 의 confidence 가 거의 동일 — baseline-fallback dominant).")
    else:
        lines.append("| Quartile | N | Mean confidence | OOS Sharpe (calibrated) |")
        lines.append("|---|---|---|---|")
        for q, r in quality.items():
            s = r.get("sharpe")
            s_str = f"{s:.3f}" if s is not None else "n/a"
            mc = r.get("mean_quality", 0.0)
            lines.append(f"| {q} | {r['n']} | {mc:.3f} | {s_str} |")
    lines.append("")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
