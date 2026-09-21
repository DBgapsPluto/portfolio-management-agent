import numpy as np
import pandas as pd

from tradingagents.skills.technical.correlation_cluster import find_correlation_clusters


def _exact_corr_frame(R: np.ndarray, columns: list[str], n: int = 200) -> pd.DataFrame:
    """Frame whose SAMPLE correlation equals R exactly.

    Centered random matrix -> QR (orthonormal, mean-zero columns => sample corr
    = identity) -> multiply by Cholesky factor of R. Removes fixture noise so
    linkage-threshold assertions are sharp, not probabilistic.
    """
    rng = np.random.default_rng(7)
    X = rng.normal(size=(n, len(columns)))
    X -= X.mean(axis=0)
    Q, _ = np.linalg.qr(X)
    Y = Q @ np.linalg.cholesky(R).T
    return pd.DataFrame(Y, columns=columns)


def test_linkage_method_kwarg_complete_vs_average():
    # corr: AB=0.80, AC=0.74, BC=0.68 -> distances AB=0.20 AC=0.26 BC=0.32.
    # Cut at 1-0.7=0.30: average linkage merges C into {A,B} (avg(0.26,0.32)=0.29
    # <= 0.30) but complete linkage keeps C out (max=0.32 > 0.30). This is the
    # D0-2 "no chain-merge" semantics the dial-ON path relies on (F5).
    R = np.array([[1.0, 0.80, 0.74],
                  [0.80, 1.0, 0.68],
                  [0.74, 0.68, 1.0]])
    df = _exact_corr_frame(R, ["A", "B", "C"])

    avg = find_correlation_clusters(df, threshold=0.7)   # default = average
    assert {frozenset(c.members) for c in avg} == {frozenset({"A", "B", "C"})}

    comp = find_correlation_clusters(df, threshold=0.7, linkage_method="complete")
    assert {frozenset(c.members) for c in comp} == {frozenset({"A", "B"})}


def test_min_periods_kwarg_guards_short_overlap():
    # A has 252d, B only overlaps A for its last 50 rows (perfectly correlated
    # there). Default (min_periods=None -> pandas pairwise) clusters them off a
    # 50-row corr; min_periods=126 turns that corr into NaN -> fillna(0.0) ->
    # no cluster. Full-universe pool contains short-history ETFs, hence the kwarg.
    rng = np.random.default_rng(11)
    n = 252
    base = rng.normal(size=n)
    a = base + rng.normal(scale=0.01, size=n)
    b = np.full(n, np.nan)
    b[-50:] = base[-50:] + rng.normal(scale=0.01, size=50)
    df = pd.DataFrame({"A": a, "B": b})

    loose = find_correlation_clusters(df, threshold=0.7)
    assert {frozenset(c.members) for c in loose} == {frozenset({"A", "B"})}

    strict = find_correlation_clusters(df, threshold=0.7, min_periods=126)
    assert strict == []


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
