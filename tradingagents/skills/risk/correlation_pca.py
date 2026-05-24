import logging
from datetime import date

import pandas as pd
from sklearn.decomposition import PCA

from tradingagents.schemas.risk import PCASnapshot
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)

# 작은 universe 에서 적응 임계가 1 에 근접해 신호가 사실상 dead-zone — n=5 면
# threshold=0.894 라 1st PC 가 89.4%+ 설명해야 concentrated. LLM 이 "신호 없음"
# 과 "정말 분산됨" 을 구분 못하므로 명시적으로 staleness sentinel 박는다.
MIN_RELIABLE_ASSETS = 10


@register_skill(name="compute_correlation_concentration", category="risk")
def compute_correlation_concentration(
    returns: pd.DataFrame, as_of: date,
) -> PCASnapshot:
    """First eigenvalue share of returns covariance + asset-count-aware concentration.

    2026-05 fix: 절대 임계 0.6은 자산 수가 적으면 (5개) 거의 항상 만족 →
    "concentrated" 의미 없음. 자산 수에 따른 baseline (random portfolio의
    expected first eigenvalue ≈ 1/√n) 대비 비율로 판정.

    concentrated if first_share >= max(0.4, 2.0 / √n_assets)
        n=5  → max(0.4, 0.894) = 0.894 (거의 모든 경우 concentrated 아님)
        n=10 → max(0.4, 0.632)
        n=16 → max(0.4, 0.500)
        n=25 → max(0.4, 0.4)
        n>=25 → 0.4 floor

    절대 0.4는 large universe에서 single PC가 40%+ 설명 = 실제 concentrated.

    n < MIN_RELIABLE_ASSETS (10) 인 경우 staleness_days=99 sentinel —
    임계가 너무 높아 concentrated 신호가 silent dead-zone 이 되는 것을 LLM 에
    명시적으로 알림.
    """
    if returns.shape[1] < 2:
        raise ValueError("Need at least 2 assets for PCA")

    cleaned = returns.dropna(how="any")
    n = cleaned.shape[1]
    pca = PCA(n_components=min(n, 5))
    pca.fit(cleaned.values)
    first_share = float(pca.explained_variance_ratio_[0])

    threshold = max(0.4, 2.0 / (n ** 0.5))
    is_concentrated = first_share >= threshold

    staleness = 0
    if n < MIN_RELIABLE_ASSETS:
        logger.warning(
            "PCA concentration: n=%d < %d — threshold=%.3f makes signal dead-zone, "
            "marking staleness=99 so LLM ignores",
            n, MIN_RELIABLE_ASSETS, threshold,
        )
        staleness = 99

    return PCASnapshot(
        first_eigenvalue_share=first_share,
        n_assets_analyzed=n,
        is_concentrated=is_concentrated,
        source_date=as_of,
        staleness_days=staleness,
    )
