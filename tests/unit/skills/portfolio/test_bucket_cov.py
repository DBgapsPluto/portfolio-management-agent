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
    Sigma, meta = bc.bucket_covariance(df)
    daily_var = df.var().mean()
    # 주간 연환산(×52)이지만 iid 에서 weekly_var≈5×daily_var → ≈260×daily_var.
    assert Sigma.values.diagonal().mean() == pytest.approx(daily_var * 252, rel=0.5)
    eig = np.linalg.eigvalsh(Sigma.values)
    assert eig.min() > -1e-10
    assert meta["pinned"] == []


def test_inner_join_no_pairwise():
    df = _good_frame(cols=["x", "y", "z"])
    df.loc[df.index[:50], "z"] = np.nan
    Sigma, meta = bc.bucket_covariance(df)
    assert not Sigma.isna().any().any()
    assert "z" in Sigma.columns


def test_short_bucket_pinned():
    df = _good_frame(cols=["x", "y", "short"])
    df["short"] = np.nan
    df.iloc[-30:, df.columns.get_loc("short")] = 0.01   # ≈6주 < WEEKLY_MIN_OBS
    Sigma, meta = bc.bucket_covariance(df)
    assert "short" in meta["pinned"]
    assert "short" not in Sigma.columns
    assert set(Sigma.columns) == {"x", "y"}


def test_cash_variance_floor():
    df = _good_frame(cols=["a1_cash", "b1"])
    df["a1_cash"] = 0.0001  # constant
    Sigma, meta = bc.bucket_covariance(df, cash_keys=("a1_cash",))
    assert Sigma.loc["a1_cash", "a1_cash"] >= bc.CASH_VAR_FLOOR_ANNUAL * 0.99


# === F4: 주간 리샘플 + 핀 단일 통제 (plan 2026-08-15 WP-A A2) ===


def test_weekly_resample_compounding_and_nan_weeks():
    idx = pd.bdate_range("2026-01-05", periods=10)
    r = pd.DataFrame({"a": [0.01]*10, "b": [np.nan]*5 + [0.0]*5}, index=idx)
    wk = bc._to_weekly(r)
    assert abs(wk["a"].iloc[0] - (1.01**5 - 1)) < 1e-12
    assert np.isnan(wk["b"].iloc[0])         # 全-NaN 주는 NaN 유지 (min_count=1)


def test_legacy_min_obs_kwarg_ignored():
    idx = pd.bdate_range("2024-01-01", periods=800)   # ≈167주 ≥ WEEKLY_MIN_OBS
    r = pd.DataFrame(np.random.default_rng(0).normal(0, .01, (800, 3)),
                     index=idx, columns=list("abc"))
    cov, meta = bc.bucket_covariance(r, min_obs=252)   # 레거시 인자
    assert not cov.empty and meta["pinned"] == []              # 무시되어야 함


def test_annualization_is_52():
    idx = pd.bdate_range("2022-01-03", periods=800)
    r = pd.DataFrame(np.random.default_rng(1).normal(0, .01, (800, 3)),
                     index=idx, columns=list("abc"))
    cov, _ = bc.bucket_covariance(r)
    approx = bc._to_weekly(r).var().mean() * 52
    assert 0.6 * approx < np.diag(cov.values).mean() < 1.4 * approx


def test_short_history_bucket_pinned_weekly():
    idx = pd.bdate_range("2024-01-01", periods=800)
    rng = np.random.default_rng(2)
    r = pd.DataFrame({"a": rng.normal(0, .01, 800), "c": rng.normal(0, .01, 800)},
                     index=idx)
    late = pd.Series(np.nan, index=idx); late.iloc[-100:] = 0.001   # ≈20주 < 52
    r["late"] = late
    cov, meta = bc.bucket_covariance(r)
    assert "late" in meta["pinned"] and "late" not in cov.columns


def test_window_truncated_to_104w():
    idx = pd.bdate_range("2020-01-06", periods=1600)
    r = pd.DataFrame(np.random.default_rng(3).normal(0, .01, (1600, 2)),
                     index=idx, columns=["a", "b"])
    _, meta = bc.bucket_covariance(r)
    assert meta["n_obs"] <= 104
