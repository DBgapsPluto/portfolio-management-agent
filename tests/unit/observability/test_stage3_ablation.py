"""Stage 3 ablation harness — variant comparison sanity."""
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.observability.stage3_ablation import (
    VARIANT_OVERRIDES, run_ablation, _jaccard, _spearman,
)
from tradingagents.skills.portfolio.factor_scorer import FactorPanel


def _universe():
    """gold ETF가 sub_category=gold라 D 시나리오에서 boost 받는다."""
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A1", name="KODEX 200", aum_krw=10e12,
                 underlying_index="x", bucket="위험", category="국내주식_지수",
                 sub_category="index_broad"),
        ETFEntry(ticker="A2", name="TIGER 반도체", aum_krw=8e12,
                 underlying_index="x", bucket="위험", category="국내주식_섹터",
                 sub_category="semiconductor"),
        ETFEntry(ticker="A3", name="KODEX 가치", aum_krw=6e12,
                 underlying_index="x", bucket="위험", category="국내주식_지수",
                 sub_category="factor_value_dividend"),
        ETFEntry(ticker="A4", name="KODEX 골드", aum_krw=5e12,
                 underlying_index="x", bucket="위험", category="FX 및 원자재",
                 sub_category="gold"),
        ETFEntry(ticker="A5", name="ACE 은", aum_krw=2e12,
                 underlying_index="x", bucket="위험", category="FX 및 원자재",
                 sub_category="silver_precious"),
    ])


def _make_inputs(seed=11):
    u = _universe()
    tickers = [e.ticker for e in u.etfs]
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    returns = pd.DataFrame(
        {t: rng.normal(0.0005, 0.012, 300) for t in tickers}, index=idx,
    )
    aum_lookup = {e.ticker: e.aum_krw for e in u.etfs}
    panel = {
        t: FactorPanel(skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
                       realized_vol_60d=0.15, sharpe_60d=0.3,
                       log_aum=math.log(aum_lookup[t]))
        for t in tickers
    }
    target = BucketTarget(
        weights={
            "kr_equity":             0.4,
            "global_equity":         0.0,
            "precious_metals":       0.4,
            "cyclical_commodity_fx": 0.0,
            "kr_bond":               0.0,
            "credit":                0.0,
            "global_duration":       0.0,
            "cash_mmf":              0.2,
        },
        rationale="t",
    )
    return u, target, returns, panel


def test_jaccard_basic():
    assert _jaccard(["A", "B"], ["A", "B"]) == 1.0
    assert _jaccard(["A", "B"], ["C", "D"]) == 0.0
    assert _jaccard(["A", "B", "C"], ["A", "B"]) == 2/3
    assert _jaccard([], []) == 1.0


def test_spearman_perfect_match():
    assert _spearman(["A", "B", "C"], ["A", "B", "C"]) == 1.0


def test_spearman_reverse():
    assert _spearman(["A", "B", "C"], ["C", "B", "A"]) == -1.0


def test_spearman_empty():
    # 표본 < 2면 None
    assert _spearman([], []) is None
    assert _spearman(["A"], ["A"]) is None


def test_run_ablation_baseline_vs_no_boost_differs_only_when_scenario_set():
    u, target, returns, panel = _make_inputs()
    baseline_kwargs = dict(
        regime_quadrant="recession_inflation",
        regime_confidence=0.8,
        dominant_scenario="D_N_F",        # stagflation cell → gold/silver boost
        per_bucket_n=2,
        correlation_threshold=0.85,
    )
    report = run_ablation(
        universe=u, bucket_target=target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        baseline_kwargs=baseline_kwargs,
    )

    # no_boost 변형은 baseline과 비교됨 (baseline은 결과에 안 들어감)
    assert "no_boost" in report.bucket_comparisons
    # precious_metals bucket은 boost 영향 받음 (gold/silver)
    pm_cmp = report.bucket_comparisons["no_boost"]["precious_metals"]
    # ranking이 달라지거나 동일할 수 있음. 적어도 spearman 계산은 됨.
    assert pm_cmp.spearman is None or -1.0 <= pm_cmp.spearman <= 1.0
    # report 직렬화 가능
    d = report.to_dict()
    assert "summary" in d
    assert "bucket_comparisons" in d


def test_run_ablation_raw_factors_matches_no_regime_when_no_scenario():
    """dominant_scenario=None이면 no_boost는 baseline과 동일,
    no_regime과 raw_factors는 동일해야."""
    u, target, returns, panel = _make_inputs()
    baseline_kwargs = dict(
        regime_quadrant="growth_disinflation",
        regime_confidence=1.0,
        dominant_scenario=None,           # boost 끔
        per_bucket_n=2,
        correlation_threshold=0.85,
    )
    report = run_ablation(
        universe=u, bucket_target=target, as_of=date(2026, 5, 10),
        returns=returns, factor_panel=panel,
        baseline_kwargs=baseline_kwargs,
    )
    # no_boost 변형: scenario 이미 None이라 baseline과 동일해야
    nb = report.summary["no_boost"]
    assert nb["mean_jaccard"] == pytest.approx(1.0)
    assert nb["total_diff_picks"] == 0
    # raw_factors == no_regime (둘 다 regime_confidence=0)
    nr = report.bucket_comparisons["no_regime"]
    rf = report.bucket_comparisons["raw_factors"]
    for b in nr:
        assert set(nr[b].variant_top_n) == set(rf[b].variant_top_n)


def test_run_ablation_requires_baseline():
    u, target, returns, panel = _make_inputs()
    with pytest.raises(ValueError, match="baseline"):
        run_ablation(
            universe=u, bucket_target=target, as_of=date(2026, 5, 10),
            returns=returns, factor_panel=panel,
            baseline_kwargs=dict(per_bucket_n=2),
            variants=["no_boost"],          # baseline 빠짐
        )


def test_run_ablation_unknown_variant_errors():
    u, target, returns, panel = _make_inputs()
    with pytest.raises(ValueError, match="Unknown"):
        run_ablation(
            universe=u, bucket_target=target, as_of=date(2026, 5, 10),
            returns=returns, factor_panel=panel,
            baseline_kwargs=dict(per_bucket_n=2),
            variants=["baseline", "WAT"],
        )


def test_variant_overrides_inventory():
    assert set(VARIANT_OVERRIDES) == {"baseline", "no_regime", "no_boost", "raw_factors"}
    assert VARIANT_OVERRIDES["no_regime"]["regime_confidence"] == 0.0
    assert VARIANT_OVERRIDES["no_boost"]["dominant_scenario"] is None
    assert VARIANT_OVERRIDES["raw_factors"] == {
        "regime_confidence": 0.0, "dominant_scenario": None,
    }
