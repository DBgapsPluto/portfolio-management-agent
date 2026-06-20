"""14-bucket 대표 proxy 시계열 (BL Σ용). 소스별 dispatch + as_of 끝점 + 버킷별 폴오버.

각 버킷 = (source, key) 우선순위 리스트. 1차 실패 시 다음 대체로 폴오버.
끝점은 항상 as_of (look-ahead 차단). native 통화 수익 (글로벌=USD, 국내=KRW).
"""
from __future__ import annotations
import logging
from datetime import date, timedelta
import pandas as pd

logger = logging.getLogger(__name__)

_EMPTY = lambda: pd.Series(dtype=float, index=pd.DatetimeIndex([]))  # noqa: E731

def _to_naive(idx_obj):
    """tz-aware DatetimeIndex -> tz-naive; leave others untouched."""
    if isinstance(idx_obj.index, pd.DatetimeIndex) and idx_obj.index.tz is not None:
        idx_obj = idx_obj.copy()
        idx_obj.index = idx_obj.index.tz_localize(None)
    return idx_obj

BUCKET_PROXY: dict[str, list[tuple[str, str]]] = {
    "a1_cash":             [("cash", "us_3m")],
    "a2_kr_rates":         [("pykrx", "148070"), ("yf", "EWY")],
    "a3_us_rates":         [("yf", "IEF")],
    "a4_safe_fx":          [("fred", "dxy"), ("yf", "UUP")],
    "a5_gold_infl":        [("yf", "GLD")],
    "b1_kr_equity":        [("pykrx", "069500"), ("yf", "EWY")],
    "b2_dm_core":          [("yf", "URTH"), ("yf", "ACWI")],
    "b3_global_tech":      [("yf", "QQQ")],
    "b4_china":            [("yf", "MCHI"), ("yf", "FXI")],
    "b5_other_intl":       [("yf", "EEM"), ("yf", "VEA")],
    "b6_defensive_equity": [("yf", "SPLV"), ("yf", "USMV")],
    "b7_reits":            [("yf", "VNQ"), ("yf", "RWO")],
    "b8_cyclical_commodity": [("yf", "DBC"), ("yf", "XLE")],
    "b9_risk_credit":      [("yf", "HYG"), ("yf", "JNK")],
}

def _raw_yf_batch_close(symbols: list[str], start: date, end: date) -> pd.DataFrame:
    from tradingagents.dataflows.cross_asset_returns import _raw_yf_batch
    raw = _raw_yf_batch(symbols, start, end)
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        lvl0 = raw.columns.get_level_values(0)
        closes = raw["Close"] if "Close" in lvl0 else (raw["Adj Close"] if "Adj Close" in lvl0 else pd.DataFrame())
    else:
        closes = raw[["Close"]] if "Close" in raw.columns else raw
    if closes is None or closes.empty:
        return pd.DataFrame()
    return _to_naive(closes.pct_change().dropna(how="all"))

def _fred_returns(key: str, start: date, end: date) -> pd.Series:
    from tradingagents.dataflows.fred import fetch_fred_series
    s = fetch_fred_series(key, start, end, as_of_date=end)
    if s is None or s.empty:
        return _EMPTY()
    return _to_naive(s.sort_index().pct_change().dropna())

def _pykrx_returns(key: str, start: date, end: date) -> pd.Series:
    from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
    df = fetch_returns_matrix([key], start, end)
    if df is None or df.empty or key not in df.columns:
        return _EMPTY()
    return _to_naive(df[key].dropna())

def _cash_returns(key: str, start: date, end: date) -> pd.Series:
    from tradingagents.dataflows.fred import fetch_fred_series
    lvl = fetch_fred_series(key, start, end, as_of_date=end)
    if lvl is None or lvl.empty:
        return _EMPTY()
    return _to_naive((lvl.sort_index() / 100.0 / 252.0).dropna())

def _fetch_one(source: str, key: str, start: date, end: date) -> pd.Series:
    if source == "yf":
        df = _raw_yf_batch_close([key], start, end)
        return df[key].dropna() if (not df.empty and key in df.columns) else _EMPTY()
    if source == "fred":
        return _fred_returns(key, start, end)
    if source == "pykrx":
        return _pykrx_returns(key, start, end)
    if source == "cash":
        return _cash_returns(key, start, end)
    return _EMPTY()

def fetch_bucket_proxy_returns(as_of: date, window_days: int = 730) -> pd.DataFrame:
    """14버킷 일별수익 DataFrame (date × bucket_key). 끝점=as_of, 버킷별 폴오버.

    빈 컬럼(전 proxy 실패)은 그대로 비워 둠 — bucket_cov가 핀 처리.
    """
    start = as_of - timedelta(days=int(window_days * 1.6))
    cols: dict[str, pd.Series] = {}
    for bkey, specs in BUCKET_PROXY.items():
        ser = _EMPTY()
        for source, key in specs:
            try:
                ser = _fetch_one(source, key, start, as_of)
            except Exception as e:  # noqa: BLE001
                logger.warning("proxy %s/%s fetch fail (%s): %s", bkey, key, source, e)
                ser = _EMPTY()
            if not ser.empty:
                break
        if not ser.empty:
            try:
                ser = ser[ser.index <= pd.Timestamp(as_of)]
            except Exception as e:  # noqa: BLE001 — e.g. tz mismatch slips through
                logger.warning("proxy %s as_of cutoff failed: %s", bkey, e)
                ser = _EMPTY()
        cols[bkey] = ser
    df = pd.DataFrame(cols)
    if len(df.index):
        df.index = pd.to_datetime(df.index)
    return df
