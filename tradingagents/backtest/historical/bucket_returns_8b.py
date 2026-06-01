"""8-bucket historical return time series construction (Tier 2).

Replaces 5-bucket bucket_returns.parquet with 8-bucket schema:
  kr_equity, global_equity, precious_metals, cyclical_commodity_fx,
  kr_bond, credit, global_duration, cash_mmf.

All returns are KRW basis (USD -> KRW via FRED usd_krw / DEXKOUS).

Source per bucket (spec S7.2, empirically verified 2026-05-28):
  kr_equity:             pykrx KOSPI 200 (1028) daily close + ~2%/yr dividend RI
  global_equity:         VEU 2007+ / ^GSPC 1991-2007 (USD->KRW)
  precious_metals:       GLD 2004+ + SLV 2006+ (50:50) / FRED gold spot pre-2004
  cyclical_commodity_fx: DJP 2006+ + DXY 70:30 / WTI+DXY pre-2006
  kr_bond:               KOSEF 148070.KS 2011+ / ECOS kr_treasury_10y duration pre-2011
  credit:                HYG 2007+ / BAA10Y returns proxy pre-2007
  global_duration:       TLT 2002+ / DGS10 duration pre-2002
  cash_mmf:              ECOS kr_treasury_3y short-rate TR

Live generation requires: FRED_API_KEY, ECOS_API_KEY, network (yfinance),
and pykrx with KRX login for kr_equity. When unavailable, individual builders
fail gracefully (return empty Series) and the orchestrator logs + continues.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _build_kr_equity_tr(start: date, end: date) -> pd.Series:
    """KOSPI 200 TR = price change + ~2%/yr dividend reinvestment (pykrx 1028)."""
    from pykrx import stock as pkstock
    df = pkstock.get_index_ohlcv_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "1028"
    )
    if df is None or df.empty:
        return pd.Series(dtype=float, name="kr_equity_tr")
    price_ret = df["종가"].pct_change()
    div_daily = 0.02 / 252
    return (price_ret + div_daily).rename("kr_equity_tr")


def _build_global_equity_tr(start: date, end: date) -> pd.Series:
    """VEU 2007+ / ^GSPC pre-2007, KRW basis."""
    import yfinance as yf
    from tradingagents.dataflows import fred
    boundary = date(2007, 3, 8)

    def _yf_returns_krw(symbol, s, e):
        df = yf.Ticker(symbol).history(start=s, end=e + timedelta(days=1), auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        price_ret = df["Close"].pct_change()
        krw_series = fred.fetch_fred_series("usd_krw", s, e)
        krw_aligned = krw_series.reindex(price_ret.index).ffill()
        krw_ret = krw_aligned.pct_change()
        return ((1 + price_ret) * (1 + krw_ret) - 1).dropna()

    pieces = []
    if start < boundary:
        pieces.append(_yf_returns_krw("^GSPC", start, min(end, boundary - timedelta(days=1))))
    if end >= boundary:
        pieces.append(_yf_returns_krw("VEU", max(start, boundary), end))
    if not pieces:
        return pd.Series(dtype=float, name="global_equity_tr")
    return pd.concat(pieces).sort_index().rename("global_equity_tr")


def _build_precious_metals_tr(start: date, end: date) -> pd.Series:
    """50:50 GLD/SLV 2006+, fallback to FRED gold spot pre-2004.

    GLD: 2004-11+, SLV: 2006-04+. Pre-2004: London gold AM (GOLDAMGBD228NLBM).
    """
    import yfinance as yf
    from tradingagents.dataflows import fred
    gld_start = date(2004, 11, 18)
    slv_start = date(2006, 4, 28)

    def _yf_ret(sym, s, e):
        df = yf.Ticker(sym).history(start=s, end=e + timedelta(days=1), auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df["Close"].pct_change()

    # USD -> KRW conversion
    krw = fred.fetch_fred_series("usd_krw", start, end)
    krw_ret = krw.pct_change()

    pieces = []
    if start < gld_start:
        # Pre-2004 fallback: FRED London gold fix. NOTE: GOLDAMGBD228NLBM was
        # delisted from FRED (2026); no live substitute. Degrade gracefully —
        # precious_metals simply begins at GLD inception (2004-11). The binding
        # calibration window starts 2006+ anyway, so pre-2004 gold is moot.
        try:
            gold = fred.fetch_fred_series(
                "GOLDAMGBD228NLBM", start, min(end, gld_start - timedelta(days=1))
            )
            if not gold.empty:
                gold_ret = gold.pct_change()
                aligned_krw = krw_ret.reindex(gold_ret.index).ffill()
                pre = ((1 + gold_ret) * (1 + aligned_krw) - 1).dropna()
                pieces.append(pre)
        except Exception as e:
            logger.warning("precious_metals pre-2004 gold fallback unavailable: %s", e)
    if end >= gld_start:
        gld = _yf_ret("GLD", max(start, gld_start), end)
        if end >= slv_start:
            slv = _yf_ret("SLV", max(start, slv_start), end)
            common = gld.index.intersection(slv.index)
            avg = 0.5 * gld.loc[common] + 0.5 * slv.loc[common]
        else:
            avg = gld
        aligned_krw = krw_ret.reindex(avg.index).ffill()
        post = ((1 + avg) * (1 + aligned_krw) - 1).dropna()
        pieces.append(post)
    if not pieces:
        return pd.Series(dtype=float, name="precious_metals_tr")
    return pd.concat(pieces).sort_index().rename("precious_metals_tr")


def _build_cyclical_commodity_fx_tr(start: date, end: date) -> pd.Series:
    """DJP 2006+ (Bloomberg Commodity Index) + DXY 70:30 weighted.
    Pre-2006: WTI (CL=F) + DXY weighted.
    """
    import yfinance as yf
    from tradingagents.dataflows import fred
    djp_start = date(2006, 10, 30)

    def _yf_ret(sym, s, e):
        df = yf.Ticker(sym).history(start=s, end=e + timedelta(days=1), auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df["Close"].pct_change()

    krw_ret = fred.fetch_fred_series("usd_krw", start, end).pct_change()
    dxy = fred.fetch_fred_series("dxy", start, end).pct_change()
    pieces = []
    if start < djp_start:
        wti = _yf_ret("CL=F", start, min(end, djp_start - timedelta(days=1)))
        dxy_pre = dxy.reindex(wti.index).ffill()
        krw_pre = krw_ret.reindex(wti.index).ffill()
        commodity = 0.70 * wti + 0.30 * dxy_pre
        pieces.append(((1 + commodity) * (1 + krw_pre) - 1).dropna())
    if end >= djp_start:
        djp = _yf_ret("DJP", max(start, djp_start), end)
        dxy_post = dxy.reindex(djp.index).ffill()
        krw_post = krw_ret.reindex(djp.index).ffill()
        commodity = 0.70 * djp + 0.30 * dxy_post
        pieces.append(((1 + commodity) * (1 + krw_post) - 1).dropna())
    if not pieces:
        return pd.Series(dtype=float, name="cyclical_commodity_fx_tr")
    return pd.concat(pieces).sort_index().rename("cyclical_commodity_fx_tr")


def _build_kr_bond_tr(start: date, end: date) -> pd.Series:
    """KOSEF 148070.KS 2011-10+, ECOS kr_treasury_10y duration approximation pre-2011.

    Duration approximation: r_t ~= -D x dy_t + y_{t-1}/360 (D = 8.5y for KTB 10y).
    """
    import yfinance as yf
    from tradingagents.dataflows import ecos
    kosef_start = date(2011, 10, 20)
    pieces = []
    if start < kosef_start:
        # Duration approximation from ECOS yields
        y = ecos.fetch_ecos_series(
            "kr_treasury_10y", start, min(end, kosef_start - timedelta(days=1)), freq="D"
        )
        if not y.empty:
            d_y = y.diff()
            r = (-8.5 * d_y / 100 + y.shift(1) / 36000).dropna()  # bps -> decimal
            pieces.append(r.rename("kr_bond_tr"))
    if end >= kosef_start:
        df = yf.Ticker("148070.KS").history(
            start=max(start, kosef_start), end=end + timedelta(days=1), auto_adjust=True
        )
        if not df.empty:
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            pieces.append(df["Close"].pct_change().dropna().rename("kr_bond_tr"))
    if not pieces:
        return pd.Series(dtype=float, name="kr_bond_tr")
    return pd.concat(pieces).sort_index().rename("kr_bond_tr")


def _build_credit_tr(start: date, end: date) -> pd.Series:
    """HYG 2007+, BAA10Y proxy pre-2007.
    BAA10Y is a *spread* -- convert to *return proxy* via -duration x dspread + carry.
    """
    import yfinance as yf
    from tradingagents.dataflows import fred
    hyg_start = date(2007, 4, 11)
    krw_ret = fred.fetch_fred_series("usd_krw", start, end).pct_change()
    pieces = []
    if start < hyg_start:
        baa = fred.fetch_fred_series(
            "us_credit_proxy", start, min(end, hyg_start - timedelta(days=1))
        )
        if not baa.empty:
            d_spread = baa.diff()
            r = (-5.0 * d_spread / 100 + baa.shift(1) / 36000).dropna()  # 5y duration approx
            pieces.append(r.rename("credit_tr"))
    if end >= hyg_start:
        df = yf.Ticker("HYG").history(
            start=max(start, hyg_start), end=end + timedelta(days=1), auto_adjust=True
        )
        if not df.empty:
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            ret_usd = df["Close"].pct_change()
            krw_a = krw_ret.reindex(ret_usd.index).ffill()
            ret_krw = ((1 + ret_usd) * (1 + krw_a) - 1).dropna()
            pieces.append(ret_krw.rename("credit_tr"))
    if not pieces:
        return pd.Series(dtype=float, name="credit_tr")
    return pd.concat(pieces).sort_index().rename("credit_tr")


def _build_global_duration_tr(start: date, end: date) -> pd.Series:
    """TLT 2002+, DGS10 duration approx pre-2002 (D=18y for 20+ Treasury)."""
    import yfinance as yf
    from tradingagents.dataflows import fred
    tlt_start = date(2002, 7, 30)
    krw_ret = fred.fetch_fred_series("usd_krw", start, end).pct_change()
    pieces = []
    if start < tlt_start:
        y = fred.fetch_fred_series("us_10y", start, min(end, tlt_start - timedelta(days=1)))
        if not y.empty:
            d_y = y.diff()
            r_usd = (-9.0 * d_y / 100 + y.shift(1) / 36000).dropna()  # 10y has D~9
            krw_a = krw_ret.reindex(r_usd.index).ffill()
            r_krw = ((1 + r_usd) * (1 + krw_a) - 1).dropna()
            pieces.append(r_krw.rename("global_duration_tr"))
    if end >= tlt_start:
        df = yf.Ticker("TLT").history(
            start=max(start, tlt_start), end=end + timedelta(days=1), auto_adjust=True
        )
        if not df.empty:
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            ret_usd = df["Close"].pct_change()
            krw_a = krw_ret.reindex(ret_usd.index).ffill()
            ret_krw = ((1 + ret_usd) * (1 + krw_a) - 1).dropna()
            pieces.append(ret_krw.rename("global_duration_tr"))
    if not pieces:
        return pd.Series(dtype=float, name="global_duration_tr")
    return pd.concat(pieces).sort_index().rename("global_duration_tr")


def _build_cash_mmf_tr(start: date, end: date) -> pd.Series:
    """ECOS kr_treasury_3y short-rate TR (annualized -> daily)."""
    from tradingagents.dataflows import ecos
    y = ecos.fetch_ecos_series("kr_treasury_3y", start, end, freq="D")
    if y.empty:
        return pd.Series(dtype=float, name="cash_mmf_tr")
    daily = (y / 36000).shift(1).rename("cash_mmf_tr")  # bps annual -> daily decimal
    return daily.dropna()


def build_bucket_returns_8b(
    start: date = date(1991, 1, 1),
    end: date = date(2024, 12, 31),
) -> pd.DataFrame:
    """Quarterly 8-bucket returns, KRW basis. Each builder failure -> empty col + warning.

    Output: DataFrame indexed by quarter_end, 8 columns (one per bucket).
    Columns: kr_equity, global_equity, precious_metals, cyclical_commodity_fx,
             kr_bond, credit, global_duration, cash_mmf.
    """
    builders = [
        ("kr_equity", _build_kr_equity_tr),
        ("global_equity", _build_global_equity_tr),
        ("precious_metals", _build_precious_metals_tr),
        ("cyclical_commodity_fx", _build_cyclical_commodity_fx_tr),
        ("kr_bond", _build_kr_bond_tr),
        ("credit", _build_credit_tr),
        ("global_duration", _build_global_duration_tr),
        ("cash_mmf", _build_cash_mmf_tr),
    ]
    populated: dict[str, pd.Series] = {}
    empty_names: list[str] = []
    for name, fn in builders:
        try:
            s = fn(start, end)
        except Exception as e:
            logger.warning("bucket %s build failed: %s", name, e)
            s = pd.Series(dtype=float)
        # Only keep series with a real DatetimeIndex; an empty/RangeIndex series
        # must NOT enter the concat or it corrupts the union index to Object dtype
        # (which would collapse every other bucket). Track it as an all-NaN column.
        if len(s) and isinstance(s.index, pd.DatetimeIndex):
            populated[name] = s.rename(name)
        else:
            empty_names.append(name)
            logger.warning("bucket %s produced no data over %s..%s", name, start, end)
    if not populated:
        empty_idx = pd.DatetimeIndex([], name="quarter_end")
        return pd.DataFrame(columns=[n for n, _ in builders], index=empty_idx)
    df = pd.concat(populated.values(), axis=1)
    # Re-introduce empty buckets as all-NaN columns on the union index.
    for name in empty_names:
        df[name] = np.nan
    df = df[[n for n, _ in builders]]  # restore canonical column order

    # Compound to quarterly. A quarter with NO daily observations for a bucket
    # (e.g. precious_metals/cyclical pre-2006 ETF inception) must yield NaN, not
    # 0.0 — otherwise those fake-zero returns silently enter calibration.
    def _q_compound(x: pd.Series) -> float:
        if x.notna().sum() == 0:
            return np.nan
        return (1 + x.fillna(0)).prod() - 1

    return df.resample("Q").agg(_q_compound)


def save_bucket_returns_8b(
    out_path: Path = Path("backtest/historical/bucket_returns_8b.parquet"),
    start: date = date(1991, 1, 1),
    end: date = date(2024, 12, 31),
) -> pd.DataFrame:
    """Build and persist quarterly 8-bucket returns to parquet."""
    df = build_bucket_returns_8b(start, end)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path)
    return df


__all__ = [
    "build_bucket_returns_8b",
    "save_bucket_returns_8b",
    "_build_kr_equity_tr",
    "_build_global_equity_tr",
    "_build_precious_metals_tr",
    "_build_cyclical_commodity_fx_tr",
    "_build_kr_bond_tr",
    "_build_credit_tr",
    "_build_global_duration_tr",
    "_build_cash_mmf_tr",
]
