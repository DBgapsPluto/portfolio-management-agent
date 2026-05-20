"""Playbook calibration (P1) — 1970+ data + Bayesian shrinkage + validation.

Usage:
    set -a && source .env && set +a
    python3 scripts/calibrate_playbooks.py
    python3 scripts/calibrate_playbooks.py --start 1991-01-01  # legacy mode
    python3 scripts/calibrate_playbooks.py --alpha 3.0 --no-validation

출력:
    data/playbook_calibration.json — fit 결과 (shrunk allocation, marginal fits, validation)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import date, datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="1970-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--alpha", type=float, default=5.0,
                        help="Bayesian shrinkage strength (α=5 → λ=α/(α+n))")
    parser.add_argument("--no-validation", action="store_true",
                        help="sub-period + walk-forward 검증 생략")
    parser.add_argument("--out", default="data/playbook_calibration.json")
    args = parser.parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    from tradingagents.backtest.classify import assign_cells, cell_frequency_table
    from tradingagents.backtest.data import (
        fetch_asset_returns_monthly_extended,
        fetch_macro_quarterly_extended,
    )
    from tradingagents.backtest.optimize import (
        fit_all_with_shrinkage, quarterly_asset_returns,
    )
    from tradingagents.backtest.validate import (
        sub_period_comparison, walk_forward_validation,
    )

    logger.info("Fetching macro %s ~ %s ...", start, end)
    macro = fetch_macro_quarterly_extended(start, end)
    logger.info("macro shape: %s", macro.shape)

    cells = assign_cells(macro)
    freq = cell_frequency_table(cells)
    logger.info("Cell counts:\n%s", freq.to_string())

    logger.info("Fetching asset returns monthly ...")
    monthly_ret = fetch_asset_returns_monthly_extended(start, end)
    returns_q = quarterly_asset_returns(monthly_ret)
    logger.info("returns_q shape: %s", returns_q.shape)

    logger.info("Fitting all with Bayesian shrinkage (α=%.1f) ...", args.alpha)
    fit = fit_all_with_shrinkage(cells, returns_q, alpha=args.alpha)

    # === Summary print ===
    print("\n=== Cycle × Tail allocation (shrunk) ===")
    print(f"{'cell':<8}{'n':>4}{'eq':>7}{'bond':>7}{'fx':>7}{'cash':>7}{'λ':>7}{'status':>12}")
    for key, r in fit["cycle_tail_allocation"].items():
        if r.get("status") in ("shrunk", "ok"):
            print(
                f"  {key:<6}{r.get('n', 0):>4}{r['equity']:>7.2f}{r['bond']:>7.2f}"
                f"{r['fx']:>7.2f}{r['cash']:>7.2f}{r.get('shrinkage_lambda', 0):>7.2f}"
                f"{r['status']:>12}"
            )
        else:
            print(f"  {key:<6}{r.get('n', 0):>4}    --- {r.get('status')}")

    print("\n=== Cycle marginal (prior) ===")
    for c, r in fit["cycle_marginal"].items():
        if r.get("status") == "ok":
            print(f"  {c}: n={r['n']:<4} eq={r['equity']:.2f} bond={r['bond']:.2f} fx={r['fx']:.2f} cash={r['cash']:.2f} Sharpe={r['sharpe']:.2f}")
        else:
            print(f"  {c}: {r.get('status')}")
    print("\n=== Tail marginal (prior) ===")
    for t, r in fit["tail_marginal"].items():
        if r.get("status") == "ok":
            print(f"  {t}: n={r['n']:<4} eq={r['equity']:.2f} bond={r['bond']:.2f} fx={r['fx']:.2f} cash={r['cash']:.2f} Sharpe={r['sharpe']:.2f}")

    print("\n=== KR share ===")
    for kr, r in fit["kr_share"].items():
        if r.get("status") in ("ok", "low_confidence"):
            print(f"  {kr}: n={r['n']:<4} kr_share={r['kr_share']:.2f} Sharpe={r['sharpe']:.2f} ({r['status']})")

    print("\n=== Bond TIPS share ===")
    for infl, r in fit["bond_tips_share"].items():
        if r.get("status") in ("ok", "low_confidence"):
            print(f"  {infl}: n={r['n']:<4} tips={r['tips_share']:.2f} Sharpe={r['sharpe']:.2f} ({r['status']})")

    # === Validation ===
    if not args.no_validation:
        logger.info("Sub-period comparison ...")
        sub = sub_period_comparison(cells, returns_q, alpha=args.alpha)
        fit["validation_sub_period"] = sub
        print(f"\n=== Sub-period drift (midpoint {sub['midpoint']}) ===")
        print(f"{'cell':<8}{'max_drift':>10}{'early_eq':>10}{'late_eq':>10}{'early_bond':>12}{'late_bond':>12}")
        for key, d in sub["cells"].items():
            if d.get("max_drift") is not None:
                print(f"  {key:<6}{d['max_drift']:>10.3f}{d['early']['equity']:>10.2f}{d['late']['equity']:>10.2f}{d['early']['bond']:>12.2f}{d['late']['bond']:>12.2f}")
            else:
                print(f"  {key:<6}    --- early={d.get('early')}, late={d.get('late')}")

        logger.info("Walk-forward validation ...")
        wf = walk_forward_validation(cells, returns_q, n_folds=5, alpha=args.alpha)
        fit["validation_walk_forward"] = wf
        print("\n=== Walk-forward (IS vs OOS Sharpe decay) ===")
        if wf.get("status") != "insufficient_data":
            agg_decays: dict = {}
            for fold in wf["folds"]:
                for key, d in fold["cells"].items():
                    if d.get("decay") is not None:
                        agg_decays.setdefault(key, []).append(d["decay"])
            for key, decays in sorted(agg_decays.items()):
                mean_decay = sum(decays) / len(decays)
                print(f"  {key}: mean_decay={mean_decay:+.3f}  n_folds={len(decays)}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fit["_meta"] = {
        "start": str(start), "end": str(end),
        "alpha": float(args.alpha),
        "generated_at": datetime.now().isoformat(),
        "macro_quarters": int(len(macro)),
        "cell_frequency": {k: int(v) for k, v in freq["n"].to_dict().items()},
    }
    out_path.write_text(json.dumps(fit, indent=2, default=str), encoding="utf-8")
    logger.info("Saved → %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
