import numpy as np
import pandas as pd

from tradingagents.skills.technical.correlation_cluster import find_correlation_clusters


def test_finds_one_cluster_when_assets_correlate():
    rng = np.random.default_rng(42)
    n = 252
    factor = rng.normal(size=n)
    df = pd.DataFrame({
        "AI_1": factor + rng.normal(scale=0.05, size=n),
        "AI_2": factor + rng.normal(scale=0.05, size=n),
        "AI_3": factor + rng.normal(scale=0.05, size=n),
        "INDEPENDENT": rng.normal(size=n),
    })
    returns = df.pct_change().dropna() if False else df  # already returns-like
    clusters = find_correlation_clusters(returns, threshold=0.7)
    # AI_1/2/3 should cluster together
    assert any(set(c.members) >= {"AI_1", "AI_2", "AI_3"} for c in clusters)
