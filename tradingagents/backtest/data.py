"""Backtest data fetching — macro classifiers + asset returns.

전체 1990-2024 (또는 2003+ for TIPS) 분기/월 데이터. FRED + yfinance.

데이터 부족 시 (예: 1970s stagflation에 TIPS ETF 없음) NaN으로 두고 caller
에서 sample size 부족 cell은 theory fallback.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from tradingagents.dataflows.fred import fetch_fred_series

logger = logging.getLogger(__name__)


# === Macro classifier 시리즈 (FRED) ===
# 주의: BAMLH0A0HYM2 (ICE BofA HY OAS)는 2023 vintage 변경 후 historical 가용 불가.
# 대신 BAA10Y (Moody's BAA - 10y Treasury, 1990+)를 credit stress proxy로 사용.
# 이는 IG 등급이라 좁지만 credit cycle 추적 충분 + long history 보장.
_FRED_MACRO = {
    "cpi":       "CPIAUCSL",
    "recession": "USREC",
    "credit_spread": "BAA10Y",
}


# === Asset return proxies (yfinance) ===
# Pre-ETF 시기는 인덱스 직접 사용. Total return ETF 우선.
_ASSET_PROXIES = {
    "gl_equity":     "^GSPC",       # S&P 500 (1957+)
    "kr_equity":     "^KS11",       # KOSPI (1996+)
    "bond_nominal":  "IEF",          # 7-10y UST ETF (2002+); fallback DGS10
    "bond_tips":     "TIP",          # TIPS ETF (2003+)
    "fx_commodity":  "DJP",          # iPath Commodity (2006+); fallback GLD+USO blend
    "cash":          "^IRX",         # 3m T-bill rate (yield, not return)
}


def _api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY env var required for backtest data")
    return key


def fetch_macro_quarterly(start: date, end: date) -> pd.DataFrame:
    """1분기당 1행. columns:
        cpi_yoy             : CPI YoY % (≥3% → inflation cell, D1)
        recession           : 0/1 NBER dummy (D1)
        credit_spread_bps   : BAA10Y 분기 평균 (bps), credit stress proxy (D2)
        kr_eq_return_q      : 분기 KOSPI return
        gl_eq_return_q      : 분기 SPX return
    """
    key = _api_key()

    cpi = fetch_fred_series("us_cpi", start, end, api_key=key).dropna()
    rec = fetch_fred_series("USREC", start, end, api_key=key).dropna()
    cs = fetch_fred_series("BAA10Y", start, end, api_key=key).dropna()

    spx = _yf_close("^GSPC", start, end)
    kospi = _yf_close("^KS11", start, end)

    cpi_yoy = (cpi.pct_change(12) * 100).resample("QE").last().rename("cpi_yoy")
    rec_q = rec.resample("QE").max().astype(float).rename("recession")
    cs_q = (cs.resample("QE").mean() * 100.0).rename("credit_spread_bps")
    spx_q = spx.resample("QE").last().pct_change().rename("gl_eq_return_q")
    kospi_q = kospi.resample("QE").last().pct_change().rename("kr_eq_return_q")

    df = pd.concat([cpi_yoy, rec_q, cs_q, spx_q, kospi_q], axis=1)
    df.index.name = "quarter_end"
    return df.dropna(subset=["cpi_yoy", "recession", "credit_spread_bps"])


def fetch_asset_returns_monthly(start: date, end: date) -> pd.DataFrame:
    """월별 total return. columns: kr_equity, gl_equity, bond_nominal, bond_tips,
    fx_commodity, cash. NaN = 데이터 없음 (ETF 출시 전 등)."""
    out: dict[str, pd.Series] = {}

    out["gl_equity"]    = _monthly_return(_yf_close("^GSPC", start, end))
    out["kr_equity"]    = _monthly_return(_yf_close("^KS11", start, end))
    out["bond_nominal"] = _monthly_return(_yf_close("IEF", start, end))
    out["bond_tips"]    = _monthly_return(_yf_close("TIP", start, end))
    out["fx_commodity"] = _monthly_return(_yf_close("DJP", start, end))

    # cash: 3m T-bill yield → monthly return = yield/12 (approximation)
    try:
        tbill = _yf_close("^IRX", start, end)  # ^IRX is in % (annual)
        # monthly close → monthly return ≈ yield / 12 / 100
        out["cash"] = (tbill.resample("ME").last() / 12.0 / 100.0)
    except Exception as e:
        logger.warning("cash proxy fetch failed: %s", e)
        out["cash"] = pd.Series(dtype=float)

    df = pd.DataFrame(out)
    df.index.name = "month_end"
    return df


def _yf_close(ticker: str, start: date, end: date) -> pd.Series:
    """yfinance Close 시리즈, daily. 실패 시 빈 시리즈."""
    try:
        df = yf.download(
            ticker, start=start, end=end + timedelta(days=1),
            auto_adjust=True, progress=False, threads=False,
        )
        if df.empty:
            return pd.Series(dtype=float, name=ticker)
        # yfinance multi-column DataFrame compatibility
        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"].iloc[:, 0]
        else:
            close = df["Close"]
        close.index = pd.to_datetime(close.index)
        return close.tz_localize(None) if close.index.tz is not None else close
    except Exception as e:
        logger.warning("yfinance %s fetch failed: %s", ticker, e)
        return pd.Series(dtype=float, name=ticker)


def _monthly_return(daily_close: pd.Series) -> pd.Series:
    if daily_close.empty:
        return pd.Series(dtype=float)
    return daily_close.resample("ME").last().pct_change()


# 1970-2000 연말 London PM gold 가격 (USD/oz, 공식 LBMA + 보조 sources).
# D-N calibration (1970s stagflation) 위해 hardcode. 월별로 log-linear interpolate.
_GOLD_HISTORICAL_YEAREND: dict[int, float] = {
    1970: 37.4, 1971: 43.6, 1972: 64.9, 1973: 106.5, 1974: 183.8,
    1975: 140.3, 1976: 134.5, 1977: 165.3, 1978: 226.0, 1979: 524.0,
    1980: 589.5, 1981: 397.5, 1982: 456.9, 1983: 382.4, 1984: 308.3,
    1985: 327.0, 1986: 391.2, 1987: 484.1, 1988: 410.3, 1989: 401.0,
    1990: 391.0, 1991: 353.4, 1992: 333.0, 1993: 391.8, 1994: 383.3,
    1995: 387.0, 1996: 369.3, 1997: 290.2, 1998: 287.5, 1999: 290.6,
    2000: 273.6,
}


def _hardcoded_gold_returns_monthly() -> pd.Series:
    """1971-01 ~ 2000-12 월별 gold 수익률 (연 끝값 log-linear interpolate)."""
    import numpy as np
    years = sorted(_GOLD_HISTORICAL_YEAREND.keys())
    # 연말 (12월 마지막날) 시점에 데이터 매핑
    yearend_dates = pd.to_datetime([f"{y}-12-31" for y in years])
    yearend_prices = pd.Series(
        [_GOLD_HISTORICAL_YEAREND[y] for y in years], index=yearend_dates,
    )
    # 월간 reindex + log interpolate (가격 양수 보장)
    monthly_idx = pd.date_range("1970-12-31", "2000-12-31", freq="ME")
    log_p = np.log(yearend_prices).reindex(
        yearend_prices.index.union(monthly_idx),
    ).interpolate(method="time")
    monthly_log = log_p.reindex(monthly_idx)
    monthly_price = np.exp(monthly_log)
    return monthly_price.pct_change().dropna()


def yield_based_bond_tr(yields_pct: pd.Series, duration: float = 7.5) -> pd.Series:
    """Approximate monthly bond TR from yield series (pre-ETF era proxy).

    TR_m ≈ -duration × (y_m - y_{m-1}) + y_{m-1}/12
    y는 % annual yield, 출력은 월간 decimal return.

    duration=7.5는 10y Treasury 평균 modified duration.
    """
    if yields_pct.empty:
        return pd.Series(dtype=float)
    y_dec = yields_pct / 100.0
    monthly_y = y_dec.resample("ME").last()
    delta_y = monthly_y.diff()
    coupon_carry = monthly_y.shift(1) / 12.0
    tr = -duration * delta_y + coupon_carry
    return tr.dropna()


def fetch_macro_quarterly_extended(start: date, end: date) -> pd.DataFrame:
    """1970-2024 분기. credit_spread는 BAA-AAA (Moody's, 1919+).

    Pre-1990 quarters 보강 — 특히 D cycle (1970s stagflation) sample 증가.
    """
    key = _api_key()
    cpi = fetch_fred_series("us_cpi", start, end, api_key=key).dropna()
    rec = fetch_fred_series("USREC", start, end, api_key=key).dropna()
    # Moody's BAA - AAA spread, both available since 1919 (monthly)
    baa = fetch_fred_series("BAA", start, end, api_key=key).dropna()
    aaa = fetch_fred_series("AAA", start, end, api_key=key).dropna()
    spread_pct = (baa - aaa).dropna()
    spx = _yf_close("^GSPC", start, end)
    kospi = _yf_close("^KS11", start, end)

    cpi_yoy = (cpi.pct_change(12) * 100).resample("QE").last().rename("cpi_yoy")
    rec_q = rec.resample("QE").max().astype(float).rename("recession")
    cs_q = (spread_pct.resample("QE").mean() * 100.0).rename("credit_spread_bps")
    spx_q = spx.resample("QE").last().pct_change().rename("gl_eq_return_q")
    kospi_q = (
        kospi.resample("QE").last().pct_change().rename("kr_eq_return_q")
        if not kospi.empty else pd.Series(dtype=float, name="kr_eq_return_q")
    )
    df = pd.concat([cpi_yoy, rec_q, cs_q, spx_q, kospi_q], axis=1)
    df.index.name = "quarter_end"
    return df.dropna(subset=["cpi_yoy", "recession", "credit_spread_bps"])


def fetch_asset_returns_monthly_extended(start: date, end: date) -> pd.DataFrame:
    """1970-2024 월별 return. pre-ETF era는 yield-based proxy.

    - bond_nominal: IEF (2002+) ∪ DGS10 yield-based TR (pre-2002)
    - fx_commodity: DJP (2006+) ∪ 금 spot (1968+)
    - cash: TB3MS (1934+, monthly)
    - bond_tips: TIP (2003+) only
    - kr_equity: ^KS11 (1996+) only
    """
    key = _api_key()
    spx = _yf_close("^GSPC", start, end)
    kospi = _yf_close("^KS11", start, end)

    ief = _yf_close("IEF", start, end)
    dgs10 = fetch_fred_series("us_10y", start, end, api_key=key).dropna()
    bond_nominal_etf = _monthly_return(ief)
    bond_nominal_yld = yield_based_bond_tr(dgs10, duration=7.5)
    # ETF 우선, ETF 없는 시기는 yield-based
    bond_nominal = bond_nominal_etf.combine_first(bond_nominal_yld).rename("bond_nominal")

    tip = _yf_close("TIP", start, end)
    bond_tips = _monthly_return(tip).rename("bond_tips")

    djp = _yf_close("DJP", start, end)
    djp_ret = _monthly_return(djp)
    # Gold: GC=F (2000+) + hardcoded annual prices (1970-2000) for D-N calibration.
    gold = _yf_close("GC=F", start, end)
    gold_modern = _monthly_return(gold)
    gold_hist = _hardcoded_gold_returns_monthly()
    gold_monthly = gold_modern.combine_first(gold_hist)
    fx_commodity = djp_ret.combine_first(gold_monthly).rename("fx_commodity")

    tb3 = fetch_fred_series("TB3MS", start, end, api_key=key).dropna()
    cash = (tb3.resample("ME").last() / 12.0 / 100.0).rename("cash") \
        if not tb3.empty else pd.Series(dtype=float, name="cash")

    gl_equity = _monthly_return(spx).rename("gl_equity")
    kr_equity = (
        _monthly_return(kospi).rename("kr_equity")
        if not kospi.empty else pd.Series(dtype=float, name="kr_equity")
    )

    df = pd.concat(
        [gl_equity, kr_equity, bond_nominal, bond_tips, fx_commodity, cash],
        axis=1,
    )
    df.index.name = "month_end"
    return df
