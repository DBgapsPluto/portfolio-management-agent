"""14-bucket 공분산 Σ (BL prior 역산·MQU용).

PARTIAL-1: inner-join(dropna how='any') 공통윈도에서만 단일 cov→LW 수축 (pairwise 금지).
F4: 일별→W-FRI 주간 복리 리샘플 후 추정 — KR/US 비동시성(시차 상관 왜곡) 완화.
비-NaN < WEEKLY_MIN_OBS 버킷은 호출자가 baseline 핀 (meta['pinned']). a1 분산 floor.
×52 연환산, 창 104주.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADING_WEEKS = 52
WEEKLY_MIN_OBS: int = 52    # 핀 단일 통제 — 레거시 min_obs kwarg는 무시됨
WEEKLY_WINDOW: int = 104
CASH_VAR_FLOOR_ANNUAL = (0.005) ** 2  # 0.5%/년 변동성 → 연분산 floor


def _to_weekly(returns: pd.DataFrame) -> pd.DataFrame:
    """일별→W-FRI 주간 복리. min_count=1 필수: 기본 prod()는 全-NaN 주를 1.0(=수익 0)
    으로 조작해 상장 전 구간을 '데이터 있음'으로 둔갑시킨다 (계획감사 A-3 실측)."""
    return (1 + returns).resample("W-FRI").prod(min_count=1).sub(1).dropna(how="all")


def bucket_covariance(
    returns: pd.DataFrame,
    *,
    min_obs: int | None = None,
    cash_keys: tuple[str, ...] = ("a1_cash",),
    method: str = "ledoit_wolf",
) -> tuple[pd.DataFrame, dict]:
    """returns(date×bucket, 일별 KRW) → (주간 기반 연환산 LW Σ, meta).

    meta = {pinned: [핀된 버킷], n_obs: 공통윈도 주 수, shrinkage: δ}.
    핀: 주간 비-NaN 관측 < WEEKLY_MIN_OBS 인 버킷은 제외 (호출자가 w_baseline 고정).
    min_obs 레거시 kwarg는 무시 — 일별 기준(252)을 주간 프레임에 존중하면 전-핀
    → 라이브 BL 영구 baseline (감사 A-4).
    """
    meta: dict = {"pinned": [], "n_obs": 0}
    if min_obs is not None:
        logger.warning("min_obs deprecated — WEEKLY_MIN_OBS governs")
    if returns is None or returns.empty:
        return pd.DataFrame(), meta
    weekly = _to_weekly(returns)
    valid_counts = weekly.notna().sum()
    keep = [c for c in weekly.columns if valid_counts[c] >= WEEKLY_MIN_OBS]
    meta["pinned"] = [c for c in weekly.columns if c not in keep]
    if len(keep) < 2:
        meta["pinned"] = list(returns.columns)
        return pd.DataFrame(), meta
    joined = weekly[keep].dropna(how="any").tail(WEEKLY_WINDOW)
    meta["n_obs"] = len(joined)
    if len(joined) < WEEKLY_MIN_OBS:
        meta["pinned"] = list(returns.columns)
        return pd.DataFrame(), meta
    from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov

    bd: dict = {}
    # compute_robust_cov → pypfopt CovarianceShrinkage(frequency=52) annualizes
    # (×52); it returns a labeled N×N DataFrame for a clean frame. Do NOT
    # multiply by TRADING_WEEKS again (double-annualize). Realign defensively
    # to guarantee Σ is indexed/columned by `keep`.
    cov = compute_robust_cov(joined, method=method, frequency=TRADING_WEEKS,
                             breakdown_out=bd)
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
