import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster

from tradingagents.schemas.technical import Cluster
from tradingagents.skills.registry import register_skill


@register_skill(name="find_correlation_clusters", category="technical")
def find_correlation_clusters(
    returns: pd.DataFrame,
    threshold: float = 0.7,
    universe_lookup: dict[str, str] | None = None,
    linkage_method: str = "average",
    min_periods: int | None = None,
) -> list[Cluster]:
    """Hierarchical clustering by 1-correlation distance.

    Threshold = average correlation cutoff (0.7 default).
    Returns clusters with ≥2 members.

    F5/D1-1 kwargs (defaults preserve production behavior byte-identically):
    - linkage_method: scipy linkage method. "complete" guarantees every pair
      inside a cluster correlates >= threshold (no average-linkage chain-merge)
      — the D0-2 full-universe decision.
    - min_periods: pandas corr min pairwise overlap. On a full-universe frame
      short-history tickers overlap little; insufficient overlap -> NaN ->
      fillna(0.0) (same fill as production) instead of a noisy tiny-sample corr.
    """
    corr = returns.corr(min_periods=min_periods).fillna(0.0)
    distance = 1 - corr.values
    np.fill_diagonal(distance, 0)
    n = distance.shape[0]
    if n < 2:
        return []
    cond = distance[np.triu_indices(n, k=1)]
    Z = linkage(cond, method=linkage_method)
    labels = fcluster(Z, t=1 - threshold, criterion="distance")

    clusters: list[Cluster] = []
    for cid in set(labels):
        members_idx = [i for i, l in enumerate(labels) if l == cid]
        if len(members_idx) < 2:
            continue
        members = [returns.columns[i] for i in members_idx]
        sub_corr = corr.iloc[members_idx, members_idx]
        avg_corr = float((sub_corr.values.sum() - len(members)) / (len(members) ** 2 - len(members)))
        label = (
            ", ".join((universe_lookup or {}).get(m, m) for m in members[:3])
            + ("..." if len(members) > 3 else "")
        )[:80]
        clusters.append(Cluster(
            cluster_id=f"cluster_{cid}",
            members=list(members),
            avg_internal_correlation=avg_corr,
            category_label=label,
        ))
    return clusters
