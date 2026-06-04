from types import SimpleNamespace

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.skills.mandate.fx_exposure import (
    exposure_currency, compute_fx_exposure,
)


def _etf(name, category):
    return SimpleNamespace(name=name, category=category)


def test_exposure_currency_domestic_and_hedged():
    assert exposure_currency(_etf("KODEX 200", "국내주식_지수")) == "KRW"
    assert exposure_currency(_etf("KODEX WTI원유선물(H)", "FX 및 원자재")) == "KRW"
    assert exposure_currency(_etf("TIGER 미국MSCI리츠(합성 H)", "해외주식_섹터")) == "KRW"


def test_exposure_currency_foreign():
    assert exposure_currency(_etf("TIGER 미국S&P500", "해외주식_지수")) == "USD"
    assert exposure_currency(_etf("ACE KRX금현물", "FX 및 원자재")) == "USD"
    assert exposure_currency(_etf("TIGER 일본니케이225", "해외주식_지수")) == "JPY"
    assert exposure_currency(_etf("TIGER 차이나항셍테크", "해외주식_지수")) == "CNY"
    assert exposure_currency(_etf("KODEX 인도Nifty50", "해외주식_지수")) == "INR"
    assert exposure_currency(_etf("ACE 베트남VN30(합성)", "해외주식_지수")) == "기타"


def test_exposure_currency_mmf_split():
    assert exposure_currency(_etf("KODEX CD금리액티브(합성)", "금리연계형/초단기채권")) == "KRW"
    assert exposure_currency(
        _etf("TIGER 미국달러SOFR금리액티브(합성)", "금리연계형/초단기채권")) == "USD"


def _uni():
    rows = [
        ("A069500", "KODEX 200", "국내주식_지수"),
        ("A360750", "TIGER 미국S&P500", "해외주식_지수"),
        ("A241180", "TIGER 일본니케이225", "해외주식_지수"),
        ("A261220", "KODEX WTI원유선물(H)", "FX 및 원자재"),
    ]
    etfs = [ETFEntry(ticker=t, name=n, aum_krw=1.0,
                     underlying_index="i", bucket="위험", category=c)
            for t, n, c in rows]
    return Universe(version="t", etfs=etfs)


def test_compute_fx_exposure_aggregates_by_currency():
    weights = {"A069500": 0.25, "A360750": 0.40, "A241180": 0.10, "A261220": 0.25}
    out = compute_fx_exposure(weights, _uni())
    assert out["USD"] == 0.40
    assert out["JPY"] == 0.10
    assert out["KRW"] == 0.50          # 국내 0.25 + 헤지된 WTI 0.25
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_compute_fx_exposure_skips_unknown_ticker():
    out = compute_fx_exposure({"A069500": 0.5, "A999999": 0.5}, _uni())
    assert out == {"KRW": 0.5}        # A999999 universe 부재 → 제외
