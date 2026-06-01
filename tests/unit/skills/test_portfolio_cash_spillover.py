"""cash_spillover unit tests — conviction + redistribution invariants."""
import logging

import numpy as np
import pandas as pd
import pytest

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.cash_spillover import (
    SPILLOVER_THRESHOLD_BY_BUCKET,
    SPILLOVER_THRESHOLD_DEFAULT,
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
    result = compute_bucket_conviction("cyclical_commodity_fx", [], {}, returns)
    assert result.n_chosen == 0
    assert result.mean_alpha == 0.0
    assert result.enb == 0.0
    assert result.conviction == 0.0
    assert result.spillover_ratio == 1.0


def test_conviction_precious_uses_specific_threshold():
    """precious_metals 는 threshold 0.15 사용."""
    tickers = ["A411060", "A261220"]
    returns = _make_returns(tickers, seed=4)
    alpha_scores = {t: 0.1 for t in tickers}
    result = compute_bucket_conviction("precious_metals", tickers, alpha_scores, returns)
    assert result.threshold == SPILLOVER_THRESHOLD_BY_BUCKET["precious_metals"]
    assert result.threshold == 0.15


def test_conviction_single_chosen():
    """N=1 → ENB = 1. 공식 (mean_alpha/threshold) × (1/1) = mean_alpha/threshold."""
    tickers = ["A411060"]
    returns = _make_returns(tickers, seed=5)
    alpha_scores = {"A411060": 0.075}  # threshold/2
    result = compute_bucket_conviction("precious_metals", tickers, alpha_scores, returns)
    assert result.n_chosen == 1
    assert result.enb == pytest.approx(1.0, abs=1e-9)
    expected_conviction = 0.075 / 0.15 * 1.0 / 1.0  # = 0.5
    assert result.conviction == pytest.approx(expected_conviction, abs=1e-9)
    assert result.spillover_ratio == pytest.approx(0.5, abs=1e-9)


def _make_full_universe_returns():
    tickers = (
        [f"K{i:05d}" for i in range(4)]    # kr_equity
        + [f"G{i:05d}" for i in range(4)]  # global_equity
        + [f"P{i:05d}" for i in range(2)]  # precious_metals
        + [f"Y{i:05d}" for i in range(2)]  # cyclical_commodity_fx
        + [f"B{i:05d}" for i in range(2)]  # kr_bond
        + [f"R{i:05d}" for i in range(2)]  # credit
        + [f"D{i:05d}" for i in range(2)]  # global_duration
        + [f"C{i:05d}" for i in range(2)]  # cash_mmf
    )
    return _make_returns(tickers, seed=42)


def _baseline_bucket_target() -> BucketTarget:
    return BucketTarget(
        weights={
            "kr_equity": 0.20, "global_equity": 0.20,
            "precious_metals": 0.08, "cyclical_commodity_fx": 0.07,
            "kr_bond": 0.12, "credit": 0.05, "global_duration": 0.13,
            "cash_mmf": 0.15,
        },
        bond_tips_share=0.30,
        rationale="test",
    )


def _full_universe_chosen():
    return {
        "kr_equity":             [f"K{i:05d}" for i in range(4)],
        "global_equity":         [f"G{i:05d}" for i in range(4)],
        "precious_metals":       [f"P{i:05d}" for i in range(2)],
        "cyclical_commodity_fx": [f"Y{i:05d}" for i in range(2)],
        "kr_bond":               [f"B{i:05d}" for i in range(2)],
        "credit":                [f"R{i:05d}" for i in range(2)],
        "global_duration":       [f"D{i:05d}" for i in range(2)],
        "cash_mmf":              [f"C{i:05d}" for i in range(2)],
    }


def test_spillover_no_spillover_when_full_conviction():
    """RISK_BUCKET conviction >= 1 → spillover 0, adjusted == original."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":             {t: 0.6 for t in chosen["kr_equity"]},
        "global_equity":         {t: 0.6 for t in chosen["global_equity"]},
        "precious_metals":       {t: 0.3 for t in chosen["precious_metals"]},   # 2× 0.15
        "cyclical_commodity_fx": {t: 0.3 for t in chosen["cyclical_commodity_fx"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    assert result.total_spillover_to_cash == pytest.approx(0.0, abs=1e-9)
    assert result.cash_cap_triggered is False
    adj = result.adjusted_bucket_target
    assert adj["kr_equity"] == pytest.approx(bt["kr_equity"], abs=1e-9)
    assert adj["global_duration"] == pytest.approx(bt["global_duration"], abs=1e-9)


def test_spillover_precious_zero_alpha_goes_to_cash():
    """precious_metals alpha=0 → 100% cash spillover. 나머지 RISK_BUCKET high conv."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":             {t: 0.6 for t in chosen["kr_equity"]},
        "global_equity":         {t: 0.6 for t in chosen["global_equity"]},
        "precious_metals":       {t: 0.0 for t in chosen["precious_metals"]},
        "cyclical_commodity_fx": {t: 0.3 for t in chosen["cyclical_commodity_fx"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    assert adj["precious_metals"] == pytest.approx(0.0, abs=1e-9)
    # precious(0.08) 전체가 cash 로. cash 0.15 + 0.08 = 0.23 (cap 0.40 이하)
    assert adj["cash_mmf"] == pytest.approx(0.23, abs=1e-9)
    assert result.total_spillover_to_cash == pytest.approx(0.08, abs=1e-9)
    assert result.cash_cap_triggered is False


def test_spillover_cash_cap_overflow_redistributes():
    """RISK_BUCKET 다수 spill → cash > 40% → overflow → high-conv RISK_BUCKET."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":             {t: 0.6 for t in chosen["kr_equity"]},       # high conv (keeps)
        "global_equity":         {t: 0.0 for t in chosen["global_equity"]},   # full spillover
        "precious_metals":       {t: 0.0 for t in chosen["precious_metals"]}, # full spillover
        "cyclical_commodity_fx": {t: 0.0 for t in chosen["cyclical_commodity_fx"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    # cash_new = 0.15 + 0.20(gl_eq) + 0.08(precious) + 0.07(cyclical) = 0.50 → cap 0.40 → overflow 0.10
    # overflow 0.10 → high_conv (kr_equity only)
    assert result.cash_cap_triggered is True
    assert adj["cash_mmf"] == pytest.approx(0.40, abs=1e-9)
    assert adj["kr_equity"] == pytest.approx(0.20 + 0.10, abs=1e-9)


def test_spillover_all_low_conviction_warning(caplog):
    """모든 RISK_BUCKET alpha=0 → cash > 40% + warning."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {b: {t: 0.0 for t in chosen[b]}
              for b in ("kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx")}
    with caplog.at_level(logging.WARNING):
        result = adjust_bucket_targets(bt, chosen, alphas, returns)
    assert result.adjusted_bucket_target["cash_mmf"] > 0.40
    assert any("low-conviction" in r.message.lower() for r in caplog.records)


def test_spillover_invariants():
    """합 1 보존 + bond_tips_share 보존 + 모든 weight ≥ 0."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":             {t: 0.40 for t in chosen["kr_equity"]},
        "global_equity":         {t: 0.60 for t in chosen["global_equity"]},
        "precious_metals":       {t: 0.10 for t in chosen["precious_metals"]},
        "cyclical_commodity_fx": {t: 0.10 for t in chosen["cyclical_commodity_fx"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    assert abs(sum(adj.weights.values()) - 1.0) < 1e-9
    assert adj.bond_tips_share == bt.bond_tips_share
    for b in adj.weights:
        assert adj.weights[b] >= 0.0


def test_spillover_safe_buckets_never_spill():
    """안전자산(kr_bond/credit/global_duration)은 alpha=0 이어도 spill 안 함."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    # RISK_BUCKET 은 high conv, 안전자산은 alpha 정보 없음(전달 안 함)
    alphas = {
        "kr_equity":             {t: 0.6 for t in chosen["kr_equity"]},
        "global_equity":         {t: 0.6 for t in chosen["global_equity"]},
        "precious_metals":       {t: 0.3 for t in chosen["precious_metals"]},
        "cyclical_commodity_fx": {t: 0.3 for t in chosen["cyclical_commodity_fx"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    # 안전자산 weight 불변
    assert adj["kr_bond"] == pytest.approx(bt["kr_bond"], abs=1e-9)
    assert adj["credit"] == pytest.approx(bt["credit"], abs=1e-9)
    assert adj["global_duration"] == pytest.approx(bt["global_duration"], abs=1e-9)
    # convictions/thresholds 는 RISK_BUCKET 만 (4 키)
    assert set(result.convictions.keys()) == {
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
    }
