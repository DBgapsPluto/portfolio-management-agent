"""Stage 3.5 — Portfolio numerics (LLM 없음).

Stage 3 1차 WeightVector + returns를 받아 portfolio-level risk metric을 사전
계산. Stage 4 lens들이 이 metric을 정량 evidence로 사용.

기존 Stage 1·2·3가 못 잡는 차원:
  - HHI: 우리 portfolio 자체의 집중도
  - cluster_exposure: Stage 1 correlation_clusters에 대한 우리 weight 노출
  - CVaR/VaR: portfolio-level 1-day 95% 손실 (historical sim)
  - realized_vol_60d: 우리 portfolio의 실제 vol
"""
import logging
import math

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from tradingagents.schemas._base import StalenessAware
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.schemas.technical import Cluster
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


# Stage 4 audit (2026-05-26, Task 4): named min-data thresholds.
MIN_OBS_REALIZED_VOL: int = 60     # 60d annualized vol 계산 최소
MIN_OBS_CVAR: int = 100            # historical sim CVaR 신뢰 가능 최소
VAR_PERCENTILE: float = 95.0       # 1-day VaR confidence level


class PortfolioNumerics(StalenessAware):
    """Stage 3.5 — Stage 3 weight_vector에 대한 portfolio risk metrics."""

    # 집중도
    hhi: float = Field(
        ge=0, le=1, description="Σ w_i² — 0=fully diversified, 1=single asset",
    )
    top1_weight: float = Field(ge=0, le=1, description="최대 단일 weight")
    top3_weight_sum: float = Field(ge=0, le=1, description="top-3 weights 합")

    # Cluster exposure (Stage 1 correlation_clusters 재사용)
    cluster_exposure: dict[str, float] = Field(
        default_factory=dict,
        description="cluster_id → 클러스터에 속한 ticker들의 weight 합",
    )
    max_cluster_exposure: float = Field(
        default=0.0, ge=0, le=1,
        description="가장 큰 cluster의 weight 합 (=cluster_exposure max value)",
    )

    # Tail risk (historical simulation, 1-day)
    realized_vol_60d: float = Field(
        default=0.0, ge=0,
        description="포트폴리오 60d 일별 수익률의 std (annualized 아님)",
    )
    var_95_1d: float = Field(
        default=0.0,
        description="1-day Value-at-Risk 95% (양수=손실). 0.0235 = 2.35% 손실 예상.",
    )
    cvar_95_1d: float = Field(
        default=0.0,
        description="1-day CVaR 95% (양수=손실). VaR 초과 손실의 평균.",
    )

    # 메타
    n_assets: int = Field(ge=0)


def _portfolio_returns(
    weights: dict[str, float], returns: pd.DataFrame,
) -> pd.Series:
    """포트폴리오 일별 수익률 = Σ w_i × r_i."""
    common = [t for t in weights if t in returns.columns]
    if not common:
        return pd.Series(dtype=float)
    w_arr = np.array([weights[t] for t in common])
    r_arr = returns[common].values
    return pd.Series(r_arr @ w_arr, index=returns.index)


def _compute_cluster_exposure(
    weights: dict[str, float], clusters: list[Cluster],
) -> tuple[dict[str, float], float]:
    """cluster_id → 클러스터에 속한 ticker들의 weight 합."""
    out: dict[str, float] = {}
    for cluster in clusters:
        exposure = sum(weights.get(t, 0.0) for t in cluster.members)
        if exposure > 0:
            out[cluster.cluster_id] = round(exposure, 6)
    max_exp = max(out.values()) if out else 0.0
    return out, max_exp


@register_skill(name="compute_portfolio_numerics", category="risk")
def compute_portfolio_numerics(
    weight_vector: WeightVector,
    returns: pd.DataFrame,
    clusters: list[Cluster] | None = None,
) -> PortfolioNumerics:
    """Compute Stage 3.5 numerics from Stage 3 weight_vector + returns.

    returns: 일별 returns matrix (rows=date, cols=ticker). Stage 3에서 fetch한 것 재사용.
    clusters: Stage 1 technical_report.correlation_clusters. None이면 empty.
    """
    weights = weight_vector.weights
    n_assets = len(weights)
    if n_assets == 0:
        return PortfolioNumerics(hhi=0, top1_weight=0, top3_weight_sum=0, n_assets=0)

    # 집중도
    hhi = float(sum(w * w for w in weights.values()))
    sorted_w = sorted(weights.values(), reverse=True)
    top1 = float(sorted_w[0])
    top3_sum = float(sum(sorted_w[:3]))

    # Cluster exposure
    cluster_exp_dict, max_cluster = _compute_cluster_exposure(
        weights, clusters or [],
    )

    # Tail risk via historical sim
    pf_ret = _portfolio_returns(weights, returns)
    pf_ret_clean = pf_ret.dropna()

    if len(pf_ret_clean) >= MIN_OBS_REALIZED_VOL:
        realized_vol_60d = float(pf_ret_clean.tail(MIN_OBS_REALIZED_VOL).std())
    else:
        logger.warning(
            "portfolio_metrics: realized_vol_60d 계산 불가 (obs=%d < %d) → 0.0",
            len(pf_ret_clean), MIN_OBS_REALIZED_VOL,
        )
        realized_vol_60d = 0.0

    if len(pf_ret_clean) >= MIN_OBS_CVAR:
        losses = -pf_ret_clean.values  # 양수 = 손실
        var_95 = float(np.percentile(losses, VAR_PERCENTILE))
        tail_losses = losses[losses >= var_95]
        cvar_95 = float(tail_losses.mean()) if len(tail_losses) > 0 else var_95
    else:
        logger.warning(
            "portfolio_metrics: CVaR_95_1d 계산 불가 (obs=%d < %d) → 0.0. "
            "tail_risk_lens 의 결정이 systemic_score 만으로 좁아짐.",
            len(pf_ret_clean), MIN_OBS_CVAR,
        )
        var_95 = 0.0
        cvar_95 = 0.0

    last_date = returns.index[-1] if len(returns) > 0 else None
    source_date = (
        last_date.date() if hasattr(last_date, "date") else None
    )

    return PortfolioNumerics(
        hhi=round(hhi, 6),
        top1_weight=round(top1, 6),
        top3_weight_sum=round(top3_sum, 6),
        cluster_exposure=cluster_exp_dict,
        max_cluster_exposure=round(max_cluster, 6),
        realized_vol_60d=round(realized_vol_60d, 6),
        var_95_1d=round(var_95, 6),
        cvar_95_1d=round(cvar_95, 6),
        n_assets=n_assets,
        source_date=source_date,
    )
