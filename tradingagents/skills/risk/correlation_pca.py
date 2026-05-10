from datetime import date

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from tradingagents.schemas.risk import PCASnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_correlation_concentration", category="risk")
def compute_correlation_concentration(
    returns: pd.DataFrame, as_of: date,
) -> PCASnapshot:
    """First eigenvalue share of returns covariance.

    >0.6 = concentrated (single market driver).
    """
    if returns.shape[1] < 2:
        raise ValueError("Need at least 2 assets for PCA")

    cleaned = returns.dropna(how="any")
    pca = PCA(n_components=min(cleaned.shape[1], 5))
    pca.fit(cleaned.values)
    first_share = float(pca.explained_variance_ratio_[0])

    return PCASnapshot(
        first_eigenvalue_share=first_share,
        n_assets_analyzed=cleaned.shape[1],
        is_concentrated=first_share > 0.6,
        source_date=as_of,
    )
