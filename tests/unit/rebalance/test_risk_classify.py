from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.rebalance.engine import make_is_risk, risk_total


def _uni():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="KODEX200", aum_krw=1e12,
                 underlying_index="KOSPI200", bucket="위험",
                 category="국내주식_지수"),
        ETFEntry(ticker="A357870", name="TIGER CD금리", aum_krw=1e11,
                 underlying_index="CD", bucket="안전",
                 category="금리연계형/초단기채권"),
    ])


def test_is_risk():
    is_risk = make_is_risk(_uni())
    assert is_risk("A069500") is True      # kr_equity → 위험
    assert is_risk("A357870") is False     # cash_mmf → 안전
    assert is_risk("CASH") is False        # 현금 → 안전


def test_risk_total_excludes_cash():
    is_risk = make_is_risk(_uni())
    w = {"A069500": 0.6, "A357870": 0.3, "CASH": 0.1}
    assert abs(risk_total(w, is_risk) - 0.6) < 1e-9
