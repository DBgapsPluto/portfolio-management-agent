from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.portfolio import bucket_cov as bc


def _good_frame(n=400, cols=None):
    cols = cols or [f"b{i}" for i in range(5)]
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame(
        rng.normal(0, 0.01, size=(n, len(cols))), index=idx, columns=cols
    )


def test_annualized_and_psd():
    df = _good_frame()
    Sigma, meta = bc.bucket_covariance(df, min_obs=252)
    daily_var = df.var().mean()
    assert Sigma.values.diagonal().mean() == pytest.approx(daily_var * 252, rel=0.5)
    eig = np.linalg.eigvalsh(Sigma.values)
    assert eig.min() > -1e-10
    assert meta["pinned"] == []


def test_inner_join_no_pairwise():
    df = _good_frame(cols=["x", "y", "z"])
    df.loc[df.index[:50], "z"] = np.nan
    Sigma, meta = bc.bucket_covariance(df, min_obs=100)
    assert not Sigma.isna().any().any()
    assert "z" in Sigma.columns


def test_short_bucket_pinned():
    df = _good_frame(cols=["x", "y", "short"])
    df["short"] = np.nan
    df.iloc[-30:, df.columns.get_loc("short")] = 0.01
    Sigma, meta = bc.bucket_covariance(df, min_obs=252)
    assert "short" in meta["pinned"]
    assert "short" not in Sigma.columns
    assert set(Sigma.columns) == {"x", "y"}


def test_cash_variance_floor():
    df = _good_frame(cols=["a1_cash", "b1"])
    df["a1_cash"] = 0.0001  # constant
    Sigma, meta = bc.bucket_covariance(df, min_obs=100, cash_keys=("a1_cash",))
    assert Sigma.loc["a1_cash", "a1_cash"] >= bc.CASH_VAR_FLOOR_ANNUAL * 0.99
