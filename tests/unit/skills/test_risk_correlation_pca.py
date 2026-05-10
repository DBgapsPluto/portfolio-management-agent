from datetime import date
import numpy as np
import pandas as pd

from tradingagents.skills.risk.correlation_pca import compute_correlation_concentration


def test_concentrated_when_one_factor():
    rng = np.random.default_rng(42)
    n = 252
    factor = rng.normal(size=n)
    df = pd.DataFrame({
        f"a{i}": factor + rng.normal(scale=0.05, size=n)
        for i in range(8)
    })
    snap = compute_correlation_concentration(df, date(2026, 5, 10))
    assert snap.is_concentrated is True
    assert snap.first_eigenvalue_share > 0.8
