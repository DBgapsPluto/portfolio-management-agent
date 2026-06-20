"""14-bucket 공분산 Σ (BL prior 역산·MQU용).

PARTIAL-1: inner-join(dropna how='any') 공통윈도에서만 단일 cov→LW 수축 (pairwise 금지).
비-NaN < min_obs 버킷은 호출자가 baseline 핀 (meta['pinned']). a1 분산 floor. ×252 연환산.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252
CASH_VAR_FLOOR_ANNUAL = (0.005) ** 2  # 0.5%/년 변동성 → 연분산 floor


def bucket_covariance(
    returns: pd.DataFrame,
    *,
    min_obs: int = 252,
    cash_keys: tuple[str, ...] = ("a1_cash",),
    method: str = "ledoit_wolf",
) -> tuple[pd.DataFrame, dict]:
    """returns(date×bucket, native) → (연환산 LW Σ, meta).

    meta = {pinned: [핀된 버킷], n_obs: 공통윈도 행수, shrinkage: δ}.
    핀: 비-NaN 관측 < min_obs 인 버킷은 제외 (호출자가 w_baseline 고정).
    """
    meta: dict = {"pinned": [], "n_obs": 0}
    if returns is None or returns.empty:
        return pd.DataFrame(), meta
    valid_counts = returns.notna().sum()
    keep = [c for c in returns.columns if valid_counts[c] >= min_obs]
    meta["pinned"] = [c for c in returns.columns if c not in keep]
    if len(keep) < 2:
        meta["pinned"] = list(returns.columns)
        return pd.DataFrame(), meta
    joined = returns[keep].dropna(how="any")
    meta["n_obs"] = len(joined)
    if len(joined) < min_obs:
        meta["pinned"] = list(returns.columns)
        return pd.DataFrame(), meta
    from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov

    bd: dict = {}
    # compute_robust_cov → pypfopt CovarianceShrinkage(frequency=252) already
    # annualizes (×252); it returns a labeled N×N DataFrame for a clean frame.
    # Do NOT multiply by TRADING_DAYS again (double-annualize). Realign
    # defensively to guarantee Σ is indexed/columned by `keep`.
    cov = compute_robust_cov(joined, method=method, breakdown_out=bd)
    if not isinstance(cov, pd.DataFrame):
        cov = pd.DataFrame(np.asarray(cov), index=keep, columns=keep)
    else:
        cov = cov.reindex(index=keep, columns=keep)
    Sigma = cov
    meta["shrinkage"] = bd.get("shrinkage_intensity")
    for ck in cash_keys:
        if ck in Sigma.columns and Sigma.loc[ck, ck] < CASH_VAR_FLOOR_ANNUAL:
            Sigma.loc[ck, ck] = CASH_VAR_FLOOR_ANNUAL
    Sigma = _nearest_pd(Sigma)
    return Sigma, meta


def _nearest_pd(S: pd.DataFrame) -> pd.DataFrame:
    arr = S.values
    arr = (arr + arr.T) / 2
    eig = np.linalg.eigvalsh(arr)
    if eig.min() < 1e-12:
        arr = arr + np.eye(arr.shape[0]) * (1e-12 - eig.min())
    return pd.DataFrame(arr, index=S.index, columns=S.columns)
