from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.rebalance.engine import validate_rebalance


def _uni():
    etfs = []
    for t in ["A069500", "A229200", "A233740"]:           # kr_equity (RISK)
        etfs.append(ETFEntry(ticker=t, name=t, aum_krw=1e12,
                    underlying_index="x", bucket="위험", category="국내주식_지수"))
    for t in ["A357870", "A357880", "A357890", "A357900"]:  # cash_mmf (SAFE)
        etfs.append(ETFEntry(ticker=t, name=t, aum_krw=1e11,
                    underlying_index="x", bucket="안전", category="금리연계형/초단기채권"))
    return Universe(version="t", etfs=etfs)


def test_single_cap_breach_on_realized_is_caught():
    # 0.203 잔존이 단일 cap(0.20) 위반으로 잡혀야 (finding #2).
    realized = {"A069500": 0.203, "A357870": 0.20, "A357880": 0.20,
                "A357890": 0.20, "A357900": 0.197}
    report = validate_rebalance(realized, universe=_uni(), clusters=[],
                                previous_weights=None, current_value=1_000_000, floor_pct=0.0)
    assert not report.passed
    assert any(v.rule == "single_etf_cap" for v in report.hard_violations)


def test_clean_realized_passes():
    # 각 ≤0.20, 위험합(kr_equity) = 0.15+0.15 = 0.30 ≤0.70.
    realized = {"A069500": 0.15, "A229200": 0.15, "A357870": 0.18,
                "A357880": 0.18, "A357890": 0.18, "A357900": 0.16}
    report = validate_rebalance(realized, universe=_uni(), clusters=[],
                                previous_weights=None, current_value=1_000_000, floor_pct=0.0)
    assert report.passed


def test_cash_excluded_from_validation():
    # 현금 0.05 포함. cap 은 cash 포함 분모로 평가 → 각 ETF ≤0.20 유지.
    realized = {"A069500": 0.15, "A229200": 0.14, "A357870": 0.18,
                "A357880": 0.18, "A357890": 0.18, "A357900": 0.12, "CASH": 0.05}
    report = validate_rebalance(realized, universe=_uni(), clusters=[],
                                previous_weights=None, current_value=1_000_000, floor_pct=0.0)
    assert report.passed


def test_cash_inclusive_no_false_single_or_risk_breach():
    # BUG 2: 현금이 분모에 남아야 한다. 재정규화하면(/0.62) A069500=0.306>0.20 으로
    # 거짓 단일 cap 위반이 나고, 위험합도 0.61 로 부풀려진다.
    # 현금 포함 분모 기준: 각 ETF ≤0.20, 위험합 0.38 ≤0.70 → 통과해야 한다.
    realized = {"A069500": 0.19, "A229200": 0.19, "A357870": 0.18,
                "A357880": 0.06, "CASH": 0.38}
    report = validate_rebalance(realized, universe=_uni(), clusters=[],
                                previous_weights=None, current_value=1_000_000, floor_pct=0.0)
    assert report.passed
    assert not any(v.rule in ("single_etf_cap", "risk_asset_cap")
                   for v in report.hard_violations)
