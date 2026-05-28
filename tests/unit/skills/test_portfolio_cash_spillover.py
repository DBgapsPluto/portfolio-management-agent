"""cash_spillover unit tests — conviction + redistribution invariants."""
import logging

import numpy as np
import pandas as pd
import pytest

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.cash_spillover import (
    CASH_CAP_FOR_SPILLOVER_TARGET,
    SPILLOVER_THRESHOLD_BY_BUCKET,
    SPILLOVER_THRESHOLD_DEFAULT,
    ConvictionResult,
    adjust_bucket_targets,
    compute_bucket_conviction,
)


def _make_returns(tickers: list[str], n_days: int = 252, vol: float = 0.02, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = rng.normal(0.0, vol, size=(n_days, len(tickers)))
    return pd.DataFrame(data, columns=tickers)


def test_conviction_full_strength():
    """mean_alpha = threshold AND ENB = √N → conviction = 1.0, spillover_ratio = 0."""
    tickers = ["A000001", "A000002", "A000003", "A000004"]
    returns = _make_returns(tickers, seed=1)
    # alpha 평균이 SPILLOVER_THRESHOLD_DEFAULT 와 동일하게 설계
    alpha_scores = {t: SPILLOVER_THRESHOLD_DEFAULT for t in tickers}
    result = compute_bucket_conviction("kr_equity", tickers, alpha_scores, returns)
    assert result.bucket == "kr_equity"
    assert result.n_chosen == 4
    assert result.mean_alpha == pytest.approx(SPILLOVER_THRESHOLD_DEFAULT, abs=1e-9)
    assert result.threshold == SPILLOVER_THRESHOLD_DEFAULT
    # ENB 가 √N 에 가까우면 conviction ≈ 1
    assert result.conviction >= 0.9
    assert result.spillover_ratio == pytest.approx(0.0, abs=0.1)


def test_conviction_zero_alpha():
    """mean_alpha = 0 → conviction = 0, spillover_ratio = 1.0."""
    tickers = ["A000001", "A000002"]
    returns = _make_returns(tickers, seed=2)
    alpha_scores = {t: 0.0 for t in tickers}
    result = compute_bucket_conviction("kr_equity", tickers, alpha_scores, returns)
    assert result.bucket == "kr_equity"
    assert result.n_chosen == 2
    assert result.mean_alpha == pytest.approx(0.0, abs=1e-9)
    assert result.threshold == SPILLOVER_THRESHOLD_DEFAULT
    assert result.conviction == pytest.approx(0.0, abs=1e-9)
    assert result.spillover_ratio == pytest.approx(1.0, abs=1e-9)


def test_conviction_empty_chosen():
    """chosen = [] → conviction 0, spillover 1.0, ENB 0."""
    returns = _make_returns(["A000001"], seed=3)
    result = compute_bucket_conviction("fx_commodity", [], {}, returns)
    assert result.n_chosen == 0
    assert result.mean_alpha == 0.0
    assert result.enb == 0.0
    assert result.conviction == 0.0
    assert result.spillover_ratio == 1.0


def test_conviction_fx_commodity_uses_specific_threshold():
    """fx_commodity 는 threshold 0.15 사용."""
    tickers = ["A411060", "A261220"]
    returns = _make_returns(tickers, seed=4)
    alpha_scores = {t: 0.1 for t in tickers}
    result = compute_bucket_conviction("fx_commodity", tickers, alpha_scores, returns)
    assert result.threshold == SPILLOVER_THRESHOLD_BY_BUCKET["fx_commodity"]
    assert result.threshold == 0.15


def test_conviction_single_chosen():
    """N=1 → ENB = 1. 공식 (mean_alpha/threshold) × (1/1) = mean_alpha/threshold."""
    tickers = ["A411060"]
    returns = _make_returns(tickers, seed=5)
    alpha_scores = {"A411060": 0.075}  # threshold/2
    result = compute_bucket_conviction("fx_commodity", tickers, alpha_scores, returns)
    assert result.n_chosen == 1
    assert result.enb == pytest.approx(1.0, abs=1e-9)
    expected_conviction = 0.075 / 0.15 * 1.0 / 1.0  # = 0.5
    assert result.conviction == pytest.approx(expected_conviction, abs=1e-9)
    assert result.spillover_ratio == pytest.approx(0.5, abs=1e-9)


def _make_full_universe_returns():
    tickers = (
        [f"K{i:05d}" for i in range(4)]    # kr_equity
        + [f"G{i:05d}" for i in range(4)]  # global_equity
        + [f"F{i:05d}" for i in range(2)]  # fx_commodity
        + [f"B{i:05d}" for i in range(4)]  # bond
        + [f"C{i:05d}" for i in range(2)]  # cash_mmf
    )
    return _make_returns(tickers, seed=42)


def _baseline_bucket_target() -> BucketTarget:
    return BucketTarget(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.15,
        bond=0.30, cash_mmf=0.15, bond_tips_share=0.30,
        rationale="test",
    )


def _full_universe_chosen():
    return {
        "kr_equity":     [f"K{i:05d}" for i in range(4)],
        "global_equity": [f"G{i:05d}" for i in range(4)],
        "fx_commodity":  [f"F{i:05d}" for i in range(2)],
        "bond":          [f"B{i:05d}" for i in range(4)],
        "cash_mmf":      [f"C{i:05d}" for i in range(2)],
    }


def test_spillover_no_spillover_when_full_conviction():
    """모든 bucket conviction >= 1 → spillover 0, adjusted == original.

    Note: spillover_ratio = 1 - conviction (Task 5 user-modified). conviction >= 1
    필요. alpha = 2 × threshold 로 conviction ≈ 2 보장 (sampling noise robust).
    """
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    # 2× threshold 로 conviction ≥ 1.0 보장
    alphas = {
        "kr_equity":     {t: 0.6 for t in chosen["kr_equity"]},      # 2× 0.3
        "global_equity": {t: 0.6 for t in chosen["global_equity"]},  # 2× 0.3
        "fx_commodity":  {t: 0.3 for t in chosen["fx_commodity"]},   # 2× 0.15
        "bond":          {t: 0.6 for t in chosen["bond"]},           # 2× 0.3
        "cash_mmf":      {t: 0.0 for t in chosen["cash_mmf"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    assert result.total_spillover_to_cash == pytest.approx(0.0, abs=1e-9)
    assert result.cash_cap_triggered is False
    adj = result.adjusted_bucket_target
    assert adj.kr_equity == pytest.approx(bt.kr_equity, abs=1e-9)
    assert adj.bond == pytest.approx(bt.bond, abs=1e-9)


def test_spillover_fx_negative_only_goes_to_cash():
    """fx_commodity 모두 alpha=0 → fx bucket 100% cash 로 spillover.

    나머지 bucket 은 2× threshold alpha → conviction ≈ 2 → spillover 0."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":     {t: 0.6 for t in chosen["kr_equity"]},
        "global_equity": {t: 0.6 for t in chosen["global_equity"]},
        "fx_commodity":  {t: 0.0 for t in chosen["fx_commodity"]},  # 음수 only (0)
        "bond":          {t: 0.6 for t in chosen["bond"]},
        "cash_mmf":      {t: 0.0 for t in chosen["cash_mmf"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    assert adj.fx_commodity == pytest.approx(0.0, abs=1e-9)
    # fx (0.15) 전체가 cash 로. cash 0.15 + 0.15 = 0.30 (cap 0.40 이하)
    assert adj.cash_mmf == pytest.approx(0.30, abs=1e-9)
    assert result.total_spillover_to_cash == pytest.approx(0.15, abs=1e-9)
    assert result.cash_cap_triggered is False


def test_spillover_cash_cap_overflow_redistributes():
    """다수 bucket spillover → cash > 40% → overflow → high-conv bucket 으로."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":     {t: 0.6 for t in chosen["kr_equity"]},        # high conv (keeps)
        "global_equity": {t: 0.0 for t in chosen["global_equity"]},    # full spillover
        "fx_commodity":  {t: 0.0 for t in chosen["fx_commodity"]},     # full spillover
        "bond":          {t: 0.0 for t in chosen["bond"]},             # full spillover
        "cash_mmf":      {t: 0.0 for t in chosen["cash_mmf"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    # cash_new = 0.15 + 0.20 + 0.15 + 0.30 = 0.80 → cap 0.40 → overflow 0.40
    # overflow 0.40 가 high_conv (kr_equity only) 로
    assert result.cash_cap_triggered is True
    assert adj.cash_mmf == pytest.approx(0.40, abs=1e-9)
    assert adj.kr_equity == pytest.approx(0.20 + 0.40, abs=1e-9)


def test_spillover_all_low_conviction_warning(caplog):
    """모두 alpha=0 → cash 100% + warning."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        bucket: {t: 0.0 for t in chosen[bucket]}
        for bucket in chosen
    }
    with caplog.at_level(logging.WARNING):
        result = adjust_bucket_targets(bt, chosen, alphas, returns)
    # 모든 bucket low conviction → high_conv 비어있음 → cash > 40% 허용
    assert result.adjusted_bucket_target.cash_mmf > 0.40
    assert any("low-conviction" in r.message.lower() for r in caplog.records)


def test_spillover_invariants():
    """합 1 보존 + bond_tips_share 보존 + 모든 weight ≥ 0."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":     {t: 0.40 for t in chosen["kr_equity"]},      # 일부 spillover
        "global_equity": {t: 0.60 for t in chosen["global_equity"]},  # 0 spillover
        "fx_commodity":  {t: 0.10 for t in chosen["fx_commodity"]},   # 일부 spillover
        "bond":          {t: 0.60 for t in chosen["bond"]},           # 0 spillover
        "cash_mmf":      {t: 0.0 for t in chosen["cash_mmf"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    total = adj.kr_equity + adj.global_equity + adj.fx_commodity + adj.bond + adj.cash_mmf
    assert abs(total - 1.0) < 1e-9
    assert adj.bond_tips_share == bt.bond_tips_share
    # 모든 weight 비음수
    for b in ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf"):
        assert getattr(adj, b) >= 0.0
