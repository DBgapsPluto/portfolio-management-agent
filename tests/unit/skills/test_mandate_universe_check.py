from datetime import date

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.skills.mandate.universe_check import validate_universe


def _universe() -> Universe:
    return Universe(version="2026-05-10", etfs=[
        ETFEntry(ticker="A069500", name="x", aum_krw=1e13,
                 underlying_index="x", bucket="위험", category="국내주식_지수"),
    ])


def test_all_tickers_in_universe_pass():
    wv = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A069500": 1.0},
        rationale="x",
    )
    rep = validate_universe(wv, _universe())
    assert rep.passed is True


def test_unknown_ticker_fails():
    wv = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A069500": 0.5, "A999999": 0.5},
        rationale="x",
    )
    rep = validate_universe(wv, _universe())
    assert rep.passed is False
    assert any(v.rule == "universe_membership" for v in rep.violations)
