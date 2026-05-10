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
) -> list[Cluster]:
    """Hierarchical clustering by 1-correlation distance.

    Threshold = average correlation cutoff (0.7 default).
    Returns clusters with ≥2 members.
    """
    corr = returns.corr().fillna(0.0)
    distance = 1 - corr.values
    np.fill_diagonal(distance, 0)
    n = distance.shape[0]
    if n < 2:
        return []
    cond = distance[np.triu_indices(n, k=1)]
    Z = linkage(cond, method="average")
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
