import pytest

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.skills.mandate.concentration_check import validate_concentration


def _universe() -> Universe:
    return Universe(version="2026-05-10", etfs=[
        ETFEntry(ticker="A1", name="x", aum_krw=1e13, underlying_index="x",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A2", name="y", aum_krw=1e13, underlying_index="y",
                 bucket="위험", category="해외주식_지수"),
        ETFEntry(ticker="A3", name="z", aum_krw=1e13, underlying_index="z",
                 bucket="안전", category="국내채권_종합"),
        ETFEntry(ticker="A4", name="w", aum_krw=1e13, underlying_index="w",
                 bucket="안전", category="금리연계형/초단기채권"),
    ])


def _wv(weights: dict) -> WeightVector:
    return WeightVector(
        method=OptimizationMethod.HRP, weights=weights,
        rationale="test",
    )


def test_pass_within_caps():
    rep = validate_concentration(
        _wv({"A1": 0.20, "A2": 0.20, "A3": 0.20, "A4": 0.20, "A5": 0.20}),
        Universe(version="x", etfs=[
            ETFEntry(ticker="A1", name="x", aum_krw=1e13, underlying_index="x",
                     bucket="위험", category="국내주식_지수"),
            ETFEntry(ticker="A2", name="y", aum_krw=1e13, underlying_index="y",
                     bucket="위험", category="국내주식_지수"),
            ETFEntry(ticker="A3", name="z", aum_krw=1e13, underlying_index="z",
                     bucket="안전", category="국내채권_종합"),
            ETFEntry(ticker="A4", name="w", aum_krw=1e13, underlying_index="w",
                     bucket="안전", category="금리연계형/초단기채권"),
            ETFEntry(ticker="A5", name="v", aum_krw=1e13, underlying_index="v",
                     bucket="안전", category="금리연계형/초단기채권"),
        ]),
    )
    # A1, A2 are 위험 (0.20 each = 0.40 < 0.70), rest are 안전
    # Each weight ≤ 0.20, risk total ≤ 0.70
    assert rep.passed is True


def test_single_etf_over_20pct_fails():
    rep = validate_concentration(
        _wv({"A1": 0.25, "A2": 0.15, "A3": 0.40, "A4": 0.20}),
        _universe(),
    )
    assert rep.passed is False
    assert any(v.rule == "single_etf_cap" for v in rep.violations)


def test_risk_asset_over_70pct_fails():
    universe = Universe(version="x", etfs=[
        ETFEntry(ticker=f"A{i}", name="x", aum_krw=1e13, underlying_index="x",
                 bucket="위험", category="국내주식_지수")
        for i in range(1, 5)
    ] + [
        ETFEntry(ticker="A5", name="y", aum_krw=1e13, underlying_index="y",
                 bucket="안전", category="금리연계형/초단기채권"),
    ])
    weights = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A1": 0.20, "A2": 0.20, "A3": 0.20, "A4": 0.20, "A5": 0.20},
        rationale="risk total = 0.80",
    )
    rep = validate_concentration(weights, universe)
    assert rep.passed is False
    assert any(v.rule == "risk_asset_cap" for v in rep.violations)


def test_exactly_70pct_passes_boundary():
    """Edge: risk total = exactly 0.70 should pass."""
    rep = validate_concentration(
        _wv({"A1": 0.20, "A2": 0.20, "A3": 0.20, "A4": 0.20, "A5": 0.20}),
        Universe(version="x", etfs=[
            ETFEntry(ticker="A1", name="x", aum_krw=1e13, underlying_index="x",
                     bucket="위험", category="국내주식_지수"),
            ETFEntry(ticker="A2", name="y", aum_krw=1e13, underlying_index="y",
                     bucket="위험", category="국내주식_지수"),
            ETFEntry(ticker="A3", name="z", aum_krw=1e13, underlying_index="z",
                     bucket="위험", category="국내주식_지수"),
            ETFEntry(ticker="A4", name="w", aum_krw=1e13, underlying_index="w",
                     bucket="안전", category="금리연계형/초단기채권"),
            ETFEntry(ticker="A5", name="v", aum_krw=1e13, underlying_index="v",
                     bucket="안전", category="금리연계형/초단기채권"),
        ]),
    )
    # A1, A2, A3 are 위험 (0.20 each = 0.60 < 0.70), A4, A5 are 안전
    # Each weight ≤ 0.20, risk total = 0.60 ≤ 0.70
    assert rep.passed is True
