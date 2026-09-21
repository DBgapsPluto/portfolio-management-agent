"""14-bucket 대표 proxy 시계열 (BL Σ용). 소스별 dispatch + as_of 끝점 + 버킷별 폴오버.

각 버킷 = (source, key) 우선순위 리스트. 1차 실패 시 다음 대체로 폴오버.
끝점은 항상 as_of (look-ahead 차단). KRW 기준화(F2): 언헤지-우세 버킷의 USD-소스
수익은 (1+r_usd)(1+r_fx)-1 합성 — 실제 투자자는 KRW 상장 ETF 를 사므로 Σ 는
KRW 수익 공분산이어야 한다. 헤지-우세(hedged_share≥0.5) 버킷은 local 유지(헤지 근사).
"""
from __future__ import annotations
import logging
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

from tradingagents.skills.portfolio.candidate_selector import is_hedged  # (H)/합성H 규약

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
    "a4_safe_fx":          [("fred", "usd_krw"), ("yf", "KRW=X")],  # KRW 투자자의 안전 외화 = USDKRW (F2)
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

def _to_krw(r_local: pd.Series, r_fx: pd.Series) -> pd.Series:
    """언헤지 KRW 수익 합성: (1+r_local)(1+r_fx)-1. inner-join, ffill 금지."""
    j = pd.concat({"l": r_local, "f": r_fx}, axis=1, join="inner").dropna()
    return ((1 + j["l"]) * (1 + j["f"]) - 1)


def _hedged_share_by_bucket(etfs) -> dict[str, float]:
    """버킷별 AUM 가중 환헤지 지분 — ETF *이름 규약*으로 유도 (universe에 필드 없음).
    ≥0.5 → 프록시 local 유지(헤지 근사), <0.5 → KRW composite."""
    num, den = {}, {}
    for e in etfs:
        b = getattr(e, "gaps_bucket", None)
        if not b:
            continue
        a = float(getattr(e, "aum_krw", 0) or 0)
        den[b] = den.get(b, 0.0) + a
        if is_hedged(getattr(e, "name", "")):
            num[b] = num.get(b, 0.0) + a
    return {b: (num.get(b, 0.0) / den[b] if den[b] > 0 else 0.0) for b in den}


def _load_hedged_share() -> dict[str, float] | None:
    """universe → 버킷별 헤지 지분. 로드 실패 시 None = convert-all (가장 보수적: KRW 노출 가정)."""
    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.dataflows.universe import load_universe

        uni = load_universe(Path(DEFAULT_CONFIG.get("universe_path", "./data/universe.json")))
        return _hedged_share_by_bucket(uni.etfs)
    except Exception as e:  # noqa: BLE001
        logger.warning("universe load failed (%s) — convert-all KRW fallback", e)
        return None


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

    KRW 기준화(F2): USD-소스(yf/fred) 시리즈만 hedged_share<0.5 일 때 _to_krw 합성.
    pykrx·cash 소스와 a4(자체가 USDKRW)는 제외. 빈 컬럼(전 proxy 실패)은 그대로
    비워 둠 — bucket_cov가 핀 처리.
    """
    start = as_of - timedelta(days=int(window_days * 1.6))
    hedged_share = _load_hedged_share()
    fx_cache: dict[str, pd.Series] = {}  # 함수-지역 캐시 (모듈 전역 금지 — 테스트 오염 방지)

    def _fx_returns() -> pd.Series:
        if "fx" not in fx_cache:
            fx = _EMPTY()
            for source, key in BUCKET_PROXY["a4_safe_fx"]:
                try:
                    fx = _fetch_one(source, key, start, as_of)
                except Exception as e:  # noqa: BLE001
                    logger.warning("fx proxy %s/%s fetch fail: %s", source, key, e)
                    fx = _EMPTY()
                if not fx.empty:
                    break
            fx_cache["fx"] = fx
        return fx_cache["fx"]

    cols: dict[str, pd.Series] = {}
    for bkey, specs in BUCKET_PROXY.items():
        ser = _EMPTY()
        used_source = None
        for source, key in specs:
            try:
                ser = _fetch_one(source, key, start, as_of)
            except Exception as e:  # noqa: BLE001
                logger.warning("proxy %s/%s fetch fail (%s): %s", bkey, key, source, e)
                ser = _EMPTY()
            if not ser.empty:
                used_source = source
                break
        if not ser.empty:
            try:
                ser = ser[ser.index <= pd.Timestamp(as_of)]
            except Exception as e:  # noqa: BLE001 — e.g. tz mismatch slips through
                logger.warning("proxy %s as_of cutoff failed: %s", bkey, e)
                ser = _EMPTY()
        share = None if hedged_share is None else hedged_share.get(bkey, 0.0)
        usd_source = used_source in ("yf", "fred") and bkey != "a4_safe_fx"
        if not ser.empty and usd_source and (share is None or share < 0.5):
            fx = _fx_returns()
            if fx.empty:
                logger.warning("proxy %s: FX unavailable — native USD kept", bkey)
            else:
                ser = _to_krw(ser, fx)
                logger.info("proxy %s: KRW composite (hedged_share=%s)", bkey, share)
        elif not ser.empty:
            logger.info("proxy %s: local kept (source=%s, hedged_share=%s)",
                        bkey, used_source, share)
        cols[bkey] = ser
    df = pd.DataFrame(cols)
    if len(df.index):
        df.index = pd.to_datetime(df.index)
    return df
