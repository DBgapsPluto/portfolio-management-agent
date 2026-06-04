"""Unit tests — factor-panel covariance blend."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.portfolio.cov_estimator import (
    blend_cov_from_factor_panel_dict,
    blend_cov_with_factor_proxy,
    compute_pairwise_selection_cov,
)
from tradingagents.skills.portfolio.factor_scorer import FactorPanel


def _returns_and_panel(n: int = 6, seed: int = 0):
    rng = np.random.default_rng(seed)
    cols = [f"T{i}" for i in range(n)]
    ret = pd.DataFrame(rng.normal(0, 0.01, (120, n)), columns=cols)
    panel = {
        t: FactorPanel(
            skip1m_mom_3m=0.01 * (i + 1),
            skip1m_mom_6m=0.02 * (i + 1),
            skip1m_mom_12m=0.03 * (i + 1),
            realized_vol_60d=0.10,
            sharpe_60d=0.5,
            log_aum=20.0,
        )
        for i, t in enumerate(cols)
    }
    return ret, panel


def test_compute_pairwise_selection_cov_psd_diagonal():
    ret, _ = _returns_and_panel()
    S = compute_pairwise_selection_cov(ret, min_periods=30)
    diag = np.diag(S.to_numpy())
    assert np.all(diag > 0)
    assert S.shape == (6, 6)


def test_blend_from_factor_panel_dict_changes_off_diagonal():
    ret, panel = _returns_and_panel()
    S0 = compute_pairwise_selection_cov(ret)
    breakdown: dict = {}
    S1 = blend_cov_from_factor_panel_dict(
        S0, panel, blend=0.5, breakdown_out=breakdown,
    )
    assert breakdown["factor_proxy_source"] == "cross_sectional_factor_panel"
    assert not np.allclose(S0.to_numpy(), S1.to_numpy())


def test_blend_with_factor_proxy_dispatches_dict():
    ret, panel = _returns_and_panel()
    S = compute_pairwise_selection_cov(ret)
    out = blend_cov_with_factor_proxy(S, ret, panel, blend=0.25)
    assert out.shape == S.shape
