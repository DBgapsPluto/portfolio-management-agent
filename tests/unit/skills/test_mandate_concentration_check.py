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
                     bucket="위험", category="해외주식_지수"),
            ETFEntry(ticker="A3", name="z", aum_krw=1e13, underlying_index="z",
                     bucket="안전", category="국내채권_종합"),
            ETFEntry(ticker="A4", name="w", aum_krw=1e13, underlying_index="w",
                     bucket="안전", category="금리연계형/초단기채권"),
            ETFEntry(ticker="A5", name="v", aum_krw=1e13, underlying_index="v",
                     bucket="안전", category="금리연계형/초단기채권"),
        ]),
    )
    # A1, A2 are 위험 (0.20 each = 0.40 < 0.70), rest are 안전
    # Each weight ≤ 0.20, risk total ≤ 0.70, 각 category ≤ cap (지수 0.20<0.30, 금리 0.40<0.50)
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
                     bucket="위험", category="해외주식_지수"),
            ETFEntry(ticker="A3", name="z", aum_krw=1e13, underlying_index="z",
                     bucket="위험", category="FX 및 원자재"),
            ETFEntry(ticker="A4", name="w", aum_krw=1e13, underlying_index="w",
                     bucket="안전", category="금리연계형/초단기채권"),
            ETFEntry(ticker="A5", name="v", aum_krw=1e13, underlying_index="v",
                     bucket="안전", category="금리연계형/초단기채권"),
        ]),
    )
    # A1, A2, A3 are 위험 (0.20 each = 0.60 < 0.70), A4, A5 are 안전
    # Each weight ≤ 0.20, risk total = 0.60 ≤ 0.70
    # 각 category ≤ cap: 지수 0.20<0.30, FX 0.20=0.20 경계, 금리 0.40<0.50
    assert rep.passed is True


# ---- 세부자산(category)별 상한 (대회 §2.2) ----


def _universe_cat() -> Universe:
    """category cap 검증용 — FX 2종(합 초과 케이스) + 섹터/채권."""
    return Universe(version="x", etfs=[
        ETFEntry(ticker="F1", name="fx1", aum_krw=1e13, underlying_index="x",
                 bucket="위험", category="FX 및 원자재"),
        ETFEntry(ticker="F2", name="fx2", aum_krw=1e13, underlying_index="y",
                 bucket="위험", category="FX 및 원자재"),
        ETFEntry(ticker="S1", name="sec1", aum_krw=1e13, underlying_index="z",
                 bucket="위험", category="국내주식_섹터"),
        ETFEntry(ticker="B1", name="bond", aum_krw=1e13, underlying_index="w",
                 bucket="안전", category="금리연계형/초단기채권"),
    ])


def test_category_over_cap_fails():
    """FX 및 원자재 합 0.25 > 0.20 cap → category_cap 위반 (단일·위험은 통과)."""
    rep = validate_concentration(
        _wv({"F1": 0.13, "F2": 0.12, "CASH": 0.75}), _universe_cat())
    # F1+F2 = 0.25 > 0.20 (FX cap), 단일 모두 ≤0.20, 위험 0.25 ≤0.70
    assert rep.passed is False
    assert any(v.rule == "category_cap" for v in rep.violations)
    assert not any(v.rule == "single_etf_cap" for v in rep.violations)


def test_category_within_cap_passes():
    """모든 category ≤ cap → 통과 (CASH는 cap 면제 filler)."""
    rep = validate_concentration(
        _wv({"F1": 0.10, "F2": 0.08, "S1": 0.12, "CASH": 0.70}), _universe_cat())
    # FX 0.18≤0.20, 섹터 0.12≤0.15
    assert rep.passed is True


def test_category_boundary_passes():
    """FX 정확히 0.20 → FLOAT_TOLERANCE 경계 통과."""
    rep = validate_concentration(
        _wv({"F1": 0.10, "F2": 0.10, "CASH": 0.80}), _universe_cat())
    assert rep.passed is True
    assert not any(v.rule == "category_cap" for v in rep.violations)


def test_category_tighter_than_single_fails():
    """국내주식_섹터 cap 15% < 단일 20%: S1 0.18은 단일 통과지만 category 위반."""
    rep = validate_concentration(
        _wv({"S1": 0.18, "CASH": 0.82}), _universe_cat())
    assert rep.passed is False
    assert any(v.rule == "category_cap" for v in rep.violations)
    assert not any(v.rule == "single_etf_cap" for v in rep.violations)
