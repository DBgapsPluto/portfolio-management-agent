"""Per-axis grid optimization for playbook calibration.

각 (cycle, tail) 조합의 quarters에서 (equity, bond, fx_commodity, cash) 4축
grid를 돌려 Sharpe 최대 allocation 산출. KR split / TIPS share는 별도 fit.

Sparse cell (n<3)은 theory fallback (hand-coded default 유지). n∈[3,10]은
low_confidence 라벨 + 실제 fit 결과 모두 보고.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


_RISK_FREE_RATE_ANNUAL = 0.02  # 2% baseline (T-bill 평균)
_MANDATE_RISK_CAP = 0.70


def quarterly_asset_returns(monthly: pd.DataFrame) -> pd.DataFrame:
    """월별 returns → 분기 compound returns. NaN-aware."""
    # (1+r) 누적곱 → 1 빼서 분기 return
    def _compound(g):
        if g.isna().all():
            return np.nan
        return (1 + g.fillna(0)).prod() - 1

    return monthly.resample("QE").apply(_compound)


def _portfolio_sharpe(
    weights: dict[str, float], returns_q: pd.DataFrame, rf_annual: float,
) -> tuple[float, float, float]:
    """portfolio annualized (Sharpe, mean, std). NaN drop."""
    pr = sum(weights[c] * returns_q[c] for c in weights)
    pr = pr.dropna()
    if len(pr) < 2:
        return (np.nan, np.nan, np.nan)
    ann_mean = pr.mean() * 4
    ann_std = pr.std(ddof=1) * 2
    sharpe = (ann_mean - rf_annual) / ann_std if ann_std > 1e-9 else 0.0
    return (sharpe, ann_mean, ann_std)


def fit_cycle_tail_allocation(
    cells: pd.DataFrame, returns_q: pd.DataFrame,
    cycle: str, tail: str,
    grid_step: float = 0.05,
) -> dict:
    """Grid search for (eq, bond, fx, cash) on a (cycle, tail) subset.

    Returns dict: {n, equity, bond, fx, cash, sharpe, ann_return, ann_vol, status}.
    """
    subset = cells[(cells["cycle"] == cycle) & (cells["tail"] == tail)]
    if len(subset) < 1:
        return {"n": 0, "status": "no_data"}

    aligned = returns_q.reindex(subset.index).dropna(
        subset=["gl_equity", "bond_nominal", "cash"],
    )
    if len(aligned) < 1:
        return {"n": 0, "status": "no_asset_return_overlap"}

    # fx_commodity는 2006+ 가용. 누락분 0으로 처리하면 fit 왜곡 → 가용 quarters로만 fit.
    aligned_fx = aligned.dropna(subset=["fx_commodity"])

    best = None
    steps = np.arange(0.0, 0.75 + 1e-9, grid_step)
    for eq in steps:
        for bd in steps:
            for fx in steps:
                if fx > 0.50: continue
                cash = 1.0 - eq - bd - fx
                if cash < -1e-9 or cash > 1.0: continue
                if eq + fx > _MANDATE_RISK_CAP + 1e-9: continue
                use_df = aligned_fx if fx > 1e-9 else aligned
                if len(use_df) < 1: continue
                weights = {
                    "gl_equity": eq, "bond_nominal": bd,
                    "fx_commodity": fx if fx > 1e-9 else 0.0,
                    "cash": cash,
                }
                # NaN safe: missing fx_commodity → 0 weight at those quarters
                if fx > 1e-9 and use_df["fx_commodity"].isna().any():
                    continue
                sharpe, mean, vol = _portfolio_sharpe(
                    weights, use_df, _RISK_FREE_RATE_ANNUAL,
                )
                if np.isnan(sharpe): continue
                if best is None or sharpe > best["sharpe"]:
                    best = {
                        "equity": float(eq), "bond": float(bd),
                        "fx": float(fx), "cash": float(cash),
                        "sharpe": float(sharpe),
                        "ann_return": float(mean), "ann_vol": float(vol),
                        "n": int(len(use_df)),
                    }
    if best is None:
        return {"n": len(subset), "status": "grid_empty"}
    best["status"] = "ok" if best["n"] >= 5 else "low_confidence"
    return best


def fit_kr_share(
    cells: pd.DataFrame, returns_q: pd.DataFrame,
    kr_direction: str,
    fixed_equity_total: float = 0.50,
    grid_step: float = 0.05,
) -> dict:
    """KR/Global split fit per kr direction.

    Fix equity_total, vary kr_share ∈ [0, 1]. Maximize Sharpe of equity-only sleeve
    (KR + Global, normalized to 1.0). 다른 자산은 별도.
    """
    subset = cells[cells["kr"] == kr_direction]
    if len(subset) < 1:
        return {"n": 0, "status": "no_data"}
    aligned = returns_q.reindex(subset.index).dropna(
        subset=["kr_equity", "gl_equity"],
    )
    if len(aligned) < 1:
        return {"n": 0, "status": "no_asset_return_overlap"}

    best = None
    for kr_share in np.arange(0.0, 1.0 + 1e-9, grid_step):
        pr = (
            kr_share * aligned["kr_equity"]
            + (1 - kr_share) * aligned["gl_equity"]
        ).dropna()
        if len(pr) < 2: continue
        ann_mean = pr.mean() * 4
        ann_std = pr.std(ddof=1) * 2
        sharpe = (ann_mean - _RISK_FREE_RATE_ANNUAL) / ann_std if ann_std > 1e-9 else 0.0
        if best is None or sharpe > best["sharpe"]:
            best = {
                "kr_share": float(kr_share),
                "gl_share": float(1 - kr_share),
                "sharpe": float(sharpe),
                "ann_return": float(ann_mean),
                "ann_vol": float(ann_std),
                "n": int(len(pr)),
            }
    if best is None:
        return {"n": len(subset), "status": "grid_empty"}
    best["status"] = "ok" if best["n"] >= 5 else "low_confidence"
    return best


def fit_bond_tips_share(
    cells: pd.DataFrame, returns_q: pd.DataFrame,
    inflation_flag: str,  # "inflation" or "disinflation"
    grid_step: float = 0.05,
) -> dict:
    """Bond 내부 TIPS share fit. inflation cell이면 inflation=True 분기 subset 사용."""
    if inflation_flag == "inflation":
        subset = cells[cells["cycle"].isin(["B", "D"])]
    else:
        subset = cells[cells["cycle"].isin(["A", "C"])]
    if len(subset) < 1:
        return {"n": 0, "status": "no_data"}
    aligned = returns_q.reindex(subset.index).dropna(
        subset=["bond_nominal", "bond_tips"],
    )
    if len(aligned) < 1:
        return {"n": 0, "status": "no_asset_return_overlap"}

    best = None
    for tips_share in np.arange(0.0, 1.0 + 1e-9, grid_step):
        pr = (
            (1 - tips_share) * aligned["bond_nominal"]
            + tips_share * aligned["bond_tips"]
        ).dropna()
        if len(pr) < 2: continue
        ann_mean = pr.mean() * 4
        ann_std = pr.std(ddof=1) * 2
        sharpe = (ann_mean - _RISK_FREE_RATE_ANNUAL) / ann_std if ann_std > 1e-9 else 0.0
        if best is None or sharpe > best["sharpe"]:
            best = {
                "tips_share": float(tips_share),
                "sharpe": float(sharpe),
                "ann_return": float(ann_mean),
                "ann_vol": float(ann_std),
                "n": int(len(pr)),
            }
    if best is None:
        return {"n": len(subset), "status": "grid_empty"}
    best["status"] = "ok" if best["n"] >= 5 else "low_confidence"
    return best


def fit_cycle_marginal_allocation(
    cells: pd.DataFrame, returns_q: pd.DataFrame, cycle: str,
    grid_step: float = 0.05,
) -> dict:
    """tail 무시 — 해당 cycle의 모든 quarters로 fit. shrinkage prior로 사용."""
    subset = cells[cells["cycle"] == cycle]
    if len(subset) < 1:
        return {"n": 0, "status": "no_data"}
    aligned = returns_q.reindex(subset.index).dropna(
        subset=["gl_equity", "bond_nominal", "cash"],
    )
    if len(aligned) < 1:
        return {"n": 0, "status": "no_asset_return_overlap"}
    aligned_fx = aligned.dropna(subset=["fx_commodity"])
    best = None
    steps = np.arange(0.0, 0.75 + 1e-9, grid_step)
    for eq in steps:
        for bd in steps:
            for fx in steps:
                if fx > 0.50: continue
                cash = 1.0 - eq - bd - fx
                if cash < -1e-9 or cash > 1.0: continue
                if eq + fx > _MANDATE_RISK_CAP + 1e-9: continue
                use_df = aligned_fx if fx > 1e-9 else aligned
                if len(use_df) < 1: continue
                if fx > 1e-9 and use_df["fx_commodity"].isna().any(): continue
                weights = {
                    "gl_equity": eq, "bond_nominal": bd,
                    "fx_commodity": fx if fx > 1e-9 else 0.0, "cash": cash,
                }
                sharpe, mean, vol = _portfolio_sharpe(
                    weights, use_df, _RISK_FREE_RATE_ANNUAL,
                )
                if np.isnan(sharpe): continue
                if best is None or sharpe > best["sharpe"]:
                    best = {
                        "equity": float(eq), "bond": float(bd),
                        "fx": float(fx), "cash": float(cash),
                        "sharpe": float(sharpe),
                        "n": int(len(use_df)), "status": "ok",
                    }
    return best or {"n": len(subset), "status": "grid_empty"}


def fit_tail_marginal_allocation(
    cells: pd.DataFrame, returns_q: pd.DataFrame, tail: str,
    grid_step: float = 0.05,
) -> dict:
    subset = cells[cells["tail"] == tail]
    if len(subset) < 1:
        return {"n": 0, "status": "no_data"}
    aligned = returns_q.reindex(subset.index).dropna(
        subset=["gl_equity", "bond_nominal", "cash"],
    )
    if len(aligned) < 1:
        return {"n": 0, "status": "no_asset_return_overlap"}
    aligned_fx = aligned.dropna(subset=["fx_commodity"])
    best = None
    steps = np.arange(0.0, 0.75 + 1e-9, grid_step)
    for eq in steps:
        for bd in steps:
            for fx in steps:
                if fx > 0.50: continue
                cash = 1.0 - eq - bd - fx
                if cash < -1e-9 or cash > 1.0: continue
                if eq + fx > _MANDATE_RISK_CAP + 1e-9: continue
                use_df = aligned_fx if fx > 1e-9 else aligned
                if len(use_df) < 1: continue
                if fx > 1e-9 and use_df["fx_commodity"].isna().any(): continue
                weights = {
                    "gl_equity": eq, "bond_nominal": bd,
                    "fx_commodity": fx if fx > 1e-9 else 0.0, "cash": cash,
                }
                sharpe, mean, vol = _portfolio_sharpe(
                    weights, use_df, _RISK_FREE_RATE_ANNUAL,
                )
                if np.isnan(sharpe): continue
                if best is None or sharpe > best["sharpe"]:
                    best = {
                        "equity": float(eq), "bond": float(bd),
                        "fx": float(fx), "cash": float(cash),
                        "sharpe": float(sharpe),
                        "n": int(len(use_df)), "status": "ok",
                    }
    return best or {"n": len(subset), "status": "grid_empty"}


def shrink_to_axis_prior(
    cell_fit: dict, cycle_fit: dict, tail_fit: dict, alpha: float = 5.0,
) -> dict:
    """Bayesian shrinkage: w_shrunk = (1-λ) × cell + λ × axis_prior, λ=α/(α+n).

    axis_prior = (cycle_fit + tail_fit) / 2 (양쪽 marginal 평균).
    cell_fit 또는 axis_prior 누락 시 가용한 것만 사용.
    """
    if cell_fit.get("status") not in ("ok", "low_confidence"):
        return cell_fit  # fit 실패 시 그대로
    n = cell_fit.get("n", 0)
    lam = alpha / (alpha + n)

    # 사용 가능한 prior 선택
    priors = [p for p in (cycle_fit, tail_fit) if p.get("status") == "ok"]
    if not priors:
        return {**cell_fit, "shrinkage_lambda": 0.0, "prior_source": "none"}

    # average of available priors
    prior_w = {}
    for k in ("equity", "bond", "fx", "cash"):
        prior_w[k] = sum(p[k] for p in priors) / len(priors)

    shrunk = {}
    for k in ("equity", "bond", "fx", "cash"):
        shrunk[k] = (1 - lam) * cell_fit[k] + lam * prior_w[k]

    # renormalize sum=1.0 + risk≤0.70 enforcement
    total = sum(shrunk.values())
    if total > 1e-9:
        shrunk = {k: v / total for k, v in shrunk.items()}
    risk = shrunk["equity"] + shrunk["fx"]
    if risk > _MANDATE_RISK_CAP:
        # scale equity+fx down proportionally, put excess into cash
        scale = _MANDATE_RISK_CAP / risk
        excess = (risk - _MANDATE_RISK_CAP)
        shrunk["equity"] *= scale
        shrunk["fx"] *= scale
        shrunk["cash"] += excess

    return {
        **{k: float(v) for k, v in shrunk.items()},
        "sharpe": cell_fit.get("sharpe"),
        "n": n, "shrinkage_lambda": float(lam),
        "prior_source": "+".join(["cycle"] if cycle_fit.get("status")=="ok" else [] + (["tail"] if tail_fit.get("status")=="ok" else [])) or "none",
        "status": "shrunk",
        "raw_fit": {k: cell_fit[k] for k in ("equity", "bond", "fx", "cash")},
        "prior_used": prior_w,
    }


def fit_all_with_shrinkage(
    cells: pd.DataFrame, returns_q: pd.DataFrame, alpha: float = 5.0,
) -> dict:
    """End-to-end fit with Bayesian shrinkage applied to (cycle, tail) cells."""
    # 1. axis marginal fits
    cycle_fits = {
        c: fit_cycle_marginal_allocation(cells, returns_q, c)
        for c in ("A", "B", "C", "D")
    }
    tail_fits = {
        t: fit_tail_marginal_allocation(cells, returns_q, t)
        for t in ("N", "T")
    }

    # 2. cell fits with shrinkage
    out: dict = {
        "cycle_tail_allocation": {},
        "cycle_marginal": cycle_fits,
        "tail_marginal": tail_fits,
        "kr_share": {},
        "bond_tips_share": {},
        "shrinkage_alpha": alpha,
    }
    for c in ("A", "B", "C", "D"):
        for t in ("N", "T"):
            raw = fit_cycle_tail_allocation(cells, returns_q, c, t)
            shrunk = shrink_to_axis_prior(raw, cycle_fits[c], tail_fits[t], alpha)
            out["cycle_tail_allocation"][f"{c}_{t}"] = shrunk

    for kr in ("F", "boom", "stress"):
        out["kr_share"][kr] = fit_kr_share(cells, returns_q, kr)
    for infl in ("inflation", "disinflation"):
        out["bond_tips_share"][infl] = fit_bond_tips_share(cells, returns_q, infl)
    return out


def fit_all(
    cells: pd.DataFrame, returns_q: pd.DataFrame,
) -> dict:
    """End-to-end fit. Returns dict structured for JSON serialization."""
    out: dict = {
        "cycle_tail_allocation": {},
        "kr_share": {},
        "bond_tips_share": {},
    }
    for c in ("A", "B", "C", "D"):
        for t in ("N", "T"):
            key = f"{c}_{t}"
            out["cycle_tail_allocation"][key] = fit_cycle_tail_allocation(
                cells, returns_q, c, t,
            )
    for kr in ("F", "boom", "stress"):
        out["kr_share"][kr] = fit_kr_share(cells, returns_q, kr)
    for infl in ("inflation", "disinflation"):
        out["bond_tips_share"][infl] = fit_bond_tips_share(cells, returns_q, infl)
    return out
