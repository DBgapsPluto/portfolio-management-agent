"""PR2b validation runner — 5 strategies' walk-forward OOS + statistics + report.

End-to-end:
1. Load samples.parquet (PR2a output)
2. Compute walk-forward OOS returns for 5 strategies:
   - calibrated (INITIAL_BETA = PR2a)
   - hand-coded prior (HAND_CODED_BETA_PR2A_PRE)
   - 60-40 KR-tilted
   - 1-N equal weight
   - Risk parity (60Q rolling σ-inverse)
   (24-cell legacy deferred — complex macro_q reconstruction.)
3. NBER USREC quarterly recession mask
4. Paired-t each benchmark vs calibrated + Cohen's d
5. Regime decomposition (expansion / recession per strategy)
6. Drawdown analysis per strategy
7. Output validation_report.md + .json

Usage:
    uv run python scripts/validate_factor_model.py \\
        --samples backtest/historical/samples.parquet \\
        --usrec-cache backtest/historical/raw/fred/USREC.parquet \\
        --output-dir artifacts/2026-05-25/validation
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
from pathlib import Path
from typing import Callable

# .env auto-load (FRED_API_KEY 등). 다른 backtest 스크립트들과 동일 패턴.
_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

import numpy as np
import pandas as pd

from tradingagents.backtest.benchmarks import (
    HAND_CODED_BETA_PR2A_PRE,
    equal_weight,
    kr_tilted_60_40,
    risk_parity,
)
from tradingagents.backtest.regime import (
    nber_recession_quarterly_from_parquet,
)
from tradingagents.backtest.statistics import (
    drawdown_analysis,
    paired_t_vs_benchmark,
    regime_decomposition,
)
from tradingagents.skills.research.factor_calibration import (
    HistoricalSample,
    compute_sharpe,
    simulate_portfolio_returns,
)
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS, INITIAL_BETA,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Reuse the parquet→sample loader from PR2a calibration script via importlib.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CALIBRATE_PATH = _PROJECT_ROOT / "scripts" / "calibrate_factor_model.py"
_spec = importlib.util.spec_from_file_location(
    "_pr2a_calibrate", _CALIBRATE_PATH,
)
_calibrate_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_calibrate_mod)
load_samples_from_parquet = _calibrate_mod.load_samples_from_parquet


def _walk_forward_oos_with_fixed_weights(
    samples: list[HistoricalSample],
    weight_fn: Callable[[list[HistoricalSample]], dict[str, float]],
    initial_train_size: int = 80,
    test_window: int = 7,
) -> tuple[np.ndarray, list[float]]:
    """Walk-forward OOS returns with a fixed-weight strategy.

    weight_fn(train_samples) → bucket weight dict (same weight applied to all
    test samples in the fold).
    """
    n = len(samples)
    all_returns: list[float] = []
    per_fold_sharpe: list[float] = []
    for end in range(initial_train_size, n - test_window + 1, test_window):
        train = samples[:end]
        test = samples[end:end + test_window]
        w = weight_fn(train)
        fold_returns = []
        for s in test:
            ret = sum(w.get(b, 0.0) * s.bucket_returns_next.get(b, 0.0) for b in BUCKETS)
            fold_returns.append(ret)
        all_returns.extend(fold_returns)
        per_fold_sharpe.append(compute_sharpe(np.array(fold_returns)))
    return np.array(all_returns), per_fold_sharpe


def _walk_forward_oos_with_beta(
    samples: list[HistoricalSample],
    beta: dict[tuple[str, str], float],
    initial_train_size: int = 80,
    test_window: int = 7,
) -> tuple[np.ndarray, list[float]]:
    """Walk-forward OOS returns using a fixed β (no training)."""
    n = len(samples)
    all_returns: list[float] = []
    per_fold_sharpe: list[float] = []
    for end in range(initial_train_size, n - test_window + 1, test_window):
        test = samples[end:end + test_window]
        fold_returns = simulate_portfolio_returns(test, beta)
        all_returns.extend(fold_returns.tolist())
        per_fold_sharpe.append(compute_sharpe(fold_returns))
    return np.array(all_returns), per_fold_sharpe


def _samples_to_returns_df(samples: list[HistoricalSample]) -> pd.DataFrame:
    """HistoricalSample list → DataFrame (rows = quarter, cols = bucket)."""
    rows = []
    for s in samples:
        row = {b: s.bucket_returns_next.get(b, 0.0) for b in BUCKETS}
        row["date"] = pd.Timestamp(s.date)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("date").sort_index()
    return df


def _risk_parity_weight_fn_factory(returns_df: pd.DataFrame):
    """Returns a weight_fn that uses risk_parity on train samples' returns df."""
    def fn(train: list[HistoricalSample]) -> dict[str, float]:
        train_dates = pd.to_datetime([s.date for s in train])
        sub = returns_df.loc[returns_df.index.isin(train_dates)]
        return risk_parity(sub, window=60)
    return fn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--usrec-cache", default="backtest/historical/raw/fred/USREC.parquet")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--initial-train-size", type=int, default=80)
    ap.add_argument("--test-window", type=int, default=7)
    args = ap.parse_args()

    samples = load_samples_from_parquet(Path(args.samples))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    recession_q = nber_recession_quarterly_from_parquet(Path(args.usrec_cache))
    logger.info("NBER recession quarters loaded: %s", int(recession_q.sum()))

    returns_df = _samples_to_returns_df(samples)

    strategies = {
        "calibrated": lambda: _walk_forward_oos_with_beta(
            samples, INITIAL_BETA,
            args.initial_train_size, args.test_window,
        ),
        "hand_coded_prior": lambda: _walk_forward_oos_with_beta(
            samples, HAND_CODED_BETA_PR2A_PRE,
            args.initial_train_size, args.test_window,
        ),
        "60_40_kr_tilted": lambda: _walk_forward_oos_with_fixed_weights(
            samples, lambda _: kr_tilted_60_40(),
            args.initial_train_size, args.test_window,
        ),
        "equal_weight": lambda: _walk_forward_oos_with_fixed_weights(
            samples, lambda _: equal_weight(),
            args.initial_train_size, args.test_window,
        ),
        "risk_parity": lambda: _walk_forward_oos_with_fixed_weights(
            samples, _risk_parity_weight_fn_factory(returns_df),
            args.initial_train_size, args.test_window,
        ),
    }

    results = {}
    for name, fn in strategies.items():
        logger.info("Computing %s walk-forward OOS", name)
        oos, fold_sharpes = fn()
        results[name] = {
            "oos_returns": oos,
            "mean_oos_sharpe": float(np.mean(fold_sharpes)) if fold_sharpes else 0.0,
            "std_oos_sharpe": float(np.std(fold_sharpes, ddof=1)) if len(fold_sharpes) > 1 else 0.0,
            "per_fold_sharpe": fold_sharpes,
            "full_period_sharpe": compute_sharpe(oos),
            "drawdown": drawdown_analysis(oos),
        }

    # OOS sample dates for regime alignment.
    n = len(samples)
    oos_sample_dates = []
    for end in range(args.initial_train_size, n - args.test_window + 1, args.test_window):
        for s in samples[end:end + args.test_window]:
            oos_sample_dates.append(pd.Timestamp(s.date))
    rec_mask = np.array([
        bool(recession_q.get(d, False)) for d in oos_sample_dates
    ])
    logger.info(
        "OOS sample dates: %s total, %s recession",
        len(oos_sample_dates), int(rec_mask.sum()),
    )

    # Pairwise stats: each benchmark vs calibrated.
    calib_returns = results["calibrated"]["oos_returns"]
    pairwise = {}
    for name in strategies.keys():
        if name == "calibrated":
            continue
        bench = results[name]["oos_returns"]
        pairwise[name] = paired_t_vs_benchmark(calib_returns, bench, alternative="greater")

    # Regime decomposition.
    returns_per_strategy = {n: r["oos_returns"] for n, r in results.items()}
    regime = regime_decomposition(returns_per_strategy, rec_mask)

    json_out = {
        "samples_n": len(samples),
        "oos_n": len(oos_sample_dates),
        "recession_n": int(rec_mask.sum()),
        "strategies": {
            name: {
                "mean_oos_sharpe": r["mean_oos_sharpe"],
                "std_oos_sharpe": r["std_oos_sharpe"],
                "per_fold_sharpe": r["per_fold_sharpe"],
                "full_period_sharpe": r["full_period_sharpe"],
                "drawdown": r["drawdown"],
            }
            for name, r in results.items()
        },
        "pairwise_vs_calibrated": pairwise,
        "regime_decomposition": regime,
        "deferred_strategies": ["24_cell_legacy"],
    }
    with open(output_dir / "validation_report.json", "w") as f:
        json.dump(json_out, f, indent=2, default=str)

    md = _write_markdown_report(json_out)
    with open(output_dir / "validation_report.md", "w") as f:
        f.write(md)

    print(json.dumps({
        "calibrated_mean_oos_sharpe": results["calibrated"]["mean_oos_sharpe"],
        "best_benchmark": _best_benchmark_name(results),
        "best_benchmark_sharpe": _best_benchmark_sharpe(results),
        "calibrated_beats_all": _calibrated_beats_all(results),
    }, indent=2))
    return 0


def _best_benchmark_name(results: dict) -> str:
    names = [n for n in results if n != "calibrated"]
    return max(names, key=lambda n: results[n]["mean_oos_sharpe"])


def _best_benchmark_sharpe(results: dict) -> float:
    return max(
        results[n]["mean_oos_sharpe"] for n in results if n != "calibrated"
    )


def _calibrated_beats_all(results: dict) -> bool:
    calib = results["calibrated"]["mean_oos_sharpe"]
    return all(
        calib > results[n]["mean_oos_sharpe"]
        for n in results if n != "calibrated"
    )


def _write_markdown_report(data: dict) -> str:
    lines = []
    lines.append("# PR2b Validation Report (2026-05-25)\n")
    lines.append("## Executive Summary\n")
    calib_sharpe = data["strategies"]["calibrated"]["mean_oos_sharpe"]
    best_bench = max(
        (n for n in data["strategies"] if n != "calibrated"),
        key=lambda n: data["strategies"][n]["mean_oos_sharpe"],
    )
    best_bench_sharpe = data["strategies"][best_bench]["mean_oos_sharpe"]
    delta = calib_sharpe - best_bench_sharpe
    verdict = "PASS" if delta > 0 else "FAIL"
    lines.append(
        f"Calibrated (PR2a) mean OOS Sharpe = **{calib_sharpe:.3f}**. "
        f"Best non-calibrated benchmark = **{best_bench}** ({best_bench_sharpe:.3f}). "
        f"Δ = {delta:+.3f}. Verdict: **{verdict}**.\n"
    )

    lines.append("## Section 1: Benchmark Comparison (Full Period)\n")
    lines.append("| Strategy | Mean OOS Sharpe | Std OOS | Full-period Sharpe | Max DD | vs Calibrated p | Cohen's d | N |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name, r in data["strategies"].items():
        if name == "calibrated":
            lines.append(
                f"| {name} | {r['mean_oos_sharpe']:.3f} | {r['std_oos_sharpe']:.3f} | "
                f"{r['full_period_sharpe']:.3f} | {r['drawdown']['max_drawdown']:.3f} | — | — | — |"
            )
        else:
            p = data["pairwise_vs_calibrated"][name]
            lines.append(
                f"| {name} | {r['mean_oos_sharpe']:.3f} | {r['std_oos_sharpe']:.3f} | "
                f"{r['full_period_sharpe']:.3f} | {r['drawdown']['max_drawdown']:.3f} | "
                f"{p['paired_t_p']:.3f} | {p['cohens_d']:+.3f} | {p['n']} |"
            )

    lines.append("\n## Section 2: NBER Regime Decomposition\n")
    rec_n = data["recession_n"]
    exp_n = data["oos_n"] - rec_n
    lines.append(f"OOS samples: total **{data['oos_n']}**, expansion **{exp_n}**, recession **{rec_n}**.\n")
    lines.append("| Strategy | Expansion Sharpe | Recession Sharpe | Spread |")
    lines.append("|---|---|---|---|")
    for name, r in data["regime_decomposition"].items():
        exp_s = r["expansion_sharpe"]
        rec_s = r["recession_sharpe"]
        lines.append(f"| {name} | {exp_s:+.3f} (N={r['expansion_n']}) | {rec_s:+.3f} (N={r['recession_n']}) | {exp_s - rec_s:+.3f} |")

    lines.append("\n## Section 3: Drawdown Analysis\n")
    lines.append("| Strategy | Max DD | Peak idx | Trough idx | Recovery idx | Duration (Q) |")
    lines.append("|---|---|---|---|---|---|")
    for name, r in data["strategies"].items():
        dd = r["drawdown"]
        rec = dd["recovery_idx"] if dd["recovery_idx"] is not None else "—"
        lines.append(
            f"| {name} | {dd['max_drawdown']:.3f} | {dd['drawdown_peak_idx']} | "
            f"{dd['drawdown_trough_idx']} | {rec} | {dd['duration_quarters']} |"
        )

    lines.append("\n## Section 4: Deferred\n")
    for s in data["deferred_strategies"]:
        lines.append(f"- {s}: 24-cell legacy 는 macro_q DataFrame reconstruction 이 필요 (별도 PR 또는 task).")

    lines.append("\n## Section 5: Conclusion\n")
    if delta > 0.05:
        lines.append(f"PR2a calibrated 가 5 benchmark 중 가장 우월 (Δ={delta:+.3f} > 0.05).")
    elif delta > 0:
        lines.append(f"PR2a calibrated 가 marginally 우월 (Δ={delta:+.3f}).")
    else:
        lines.append(f"⚠️ PR2a calibrated 가 best benchmark ({best_bench}) 대비 underperform (Δ={delta:+.3f}). INITIAL_BETA 재검토 필요.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
