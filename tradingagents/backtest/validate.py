"""Calibration 검증 — sub-period split + walk-forward 5-fold.

playbook fit 자체는 안 바꾸고, fit의 *안정성 / overfit 위험*만 측정.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.backtest.optimize import (
    fit_all_with_shrinkage, fit_cycle_tail_allocation,
)


def sub_period_comparison(
    cells: pd.DataFrame, returns_q: pd.DataFrame, alpha: float = 5.0,
) -> dict:
    """1970-1997 vs 1998-2024 split fit 비교. cell별 weight drift 표.

    Returns {cell_key: {early: {...}, late: {...}, drift: {asset: abs_diff}}}.
    """
    midpoint = cells.index[len(cells) // 2]
    early = cells[cells.index < midpoint]
    late = cells[cells.index >= midpoint]

    fit_e = fit_all_with_shrinkage(early, returns_q, alpha)
    fit_l = fit_all_with_shrinkage(late, returns_q, alpha)

    drift: dict = {"midpoint": str(midpoint.date()), "cells": {}}
    for key in fit_e["cycle_tail_allocation"]:
        e = fit_e["cycle_tail_allocation"][key]
        l = fit_l["cycle_tail_allocation"][key]
        if e.get("status") in ("shrunk", "ok") and l.get("status") in ("shrunk", "ok"):
            entry = {
                "early":  {a: e.get(a) for a in ("equity", "bond", "fx", "cash")},
                "late":   {a: l.get(a) for a in ("equity", "bond", "fx", "cash")},
                "n_early": e.get("n"), "n_late": l.get("n"),
                "max_drift": float(max(
                    abs(e[a] - l[a]) for a in ("equity", "bond", "fx", "cash")
                )),
            }
        else:
            entry = {
                "early": e.get("status"), "late": l.get("status"),
                "max_drift": None,
            }
        drift["cells"][key] = entry
    return drift


def walk_forward_validation(
    cells: pd.DataFrame, returns_q: pd.DataFrame,
    n_folds: int = 5, alpha: float = 5.0,
) -> dict:
    """5-fold rolling. 각 fold: 이전 quarters로 fit, fold quarters로 evaluate.

    측정: 각 cell의 in-sample vs out-of-sample Sharpe 차이.
    """
    quarters = sorted(cells.index)
    if len(quarters) < n_folds * 4:
        return {"status": "insufficient_data", "n": len(quarters)}

    fold_size = len(quarters) // n_folds
    out: dict = {"folds": [], "n_folds": n_folds}
    for f in range(1, n_folds):  # fold 0은 train-only
        train_end_idx = f * fold_size
        test_end_idx = min((f + 1) * fold_size, len(quarters))
        train_q = quarters[:train_end_idx]
        test_q = quarters[train_end_idx:test_end_idx]
        train_cells = cells.loc[train_q]
        test_cells = cells.loc[test_q]

        fit = fit_all_with_shrinkage(train_cells, returns_q, alpha)

        # Evaluate each cell's allocation on test quarters of same cell
        fold_summary = {
            "train_range": (str(train_q[0].date()), str(train_q[-1].date())),
            "test_range":  (str(test_q[0].date()), str(test_q[-1].date())),
            "cells": {},
        }
        for key, fit_cell in fit["cycle_tail_allocation"].items():
            if fit_cell.get("status") not in ("shrunk", "ok"):
                continue
            c, t = key.split("_")
            test_subset = test_cells[
                (test_cells["cycle"] == c) & (test_cells["tail"] == t)
            ]
            if len(test_subset) < 1:
                continue
            aligned = returns_q.reindex(test_subset.index).dropna(
                subset=["gl_equity", "bond_nominal", "cash"],
            )
            if len(aligned) < 1:
                continue
            weights = {
                "gl_equity": fit_cell["equity"],
                "bond_nominal": fit_cell["bond"],
                "fx_commodity": fit_cell["fx"],
                "cash": fit_cell["cash"],
            }
            # NaN-aware portfolio return
            pr = sum(weights[c_] * aligned[c_].fillna(0.0) for c_ in weights)
            oos_sharpe = float(
                (pr.mean() * 4 - 0.02) / (pr.std(ddof=1) * 2 + 1e-9),
            ) if len(pr) >= 2 else float("nan")
            fold_summary["cells"][key] = {
                "n_test": int(len(test_subset)),
                "is_sharpe": fit_cell.get("sharpe"),
                "oos_sharpe": oos_sharpe,
                "decay": (
                    fit_cell.get("sharpe", 0) - oos_sharpe
                    if not np.isnan(oos_sharpe) else None
                ),
            }
        out["folds"].append(fold_summary)
    return out
