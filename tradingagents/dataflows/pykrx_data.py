import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_pykrx_call(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Direct pykrx call. Wrapped for mocking + retry on transient failures.

    Strips the leading "A" used in our universe.json (e.g. "A069500" → "069500")
    because pykrx expects pure 6-digit ticker codes. Empty fetch otherwise.
    """
    from pykrx import stock
    normalized = ticker.lstrip("A") if ticker.startswith("A") else ticker
    return stock.get_market_ohlcv(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), normalized,
    )


def fetch_etf_ohlcv(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch one ETF's OHLCV. Returns columns [open, high, low, close, volume, ticker, date]."""
    raw = _raw_pykrx_call(ticker, start, end)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    rename = {
        "시가": "open", "고가": "high", "저가": "low",
        "종가": "close", "거래량": "volume",
    }
    df = raw.rename(columns=rename)[["open", "high", "low", "close", "volume"]]
    df["ticker"] = ticker
    df.index.name = "date"
    return df.reset_index()


class ParquetCache:
    """Parquet-backed price cache for ETF OHLCV (D10)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> pd.DataFrame:
        empty = pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
        if not self.path.exists():
            return empty
        try:
            return pd.read_parquet(self.path)
        except (OSError, ValueError):
            # Corrupt/truncated cache (e.g. an interrupted write leaving a
            # <8-byte file → pyarrow ArrowInvalid, a ValueError subclass).
            # Degrade to a cache miss so callers re-fetch instead of crashing.
            return empty

    def has(self, ticker: str, start: date, end: date) -> bool:
        df = self.read()
        if df.empty:
            return False
        sub = df[df["ticker"] == ticker]
        if sub.empty:
            return False
        sub_dates = pd.to_datetime(sub["date"]).dt.date
        return sub_dates.min() <= start and sub_dates.max() >= end

    def write_append(self, new_data: pd.DataFrame) -> None:
        existing = self.read()
        merged = pd.concat([existing, new_data], ignore_index=True)
        merged = merged.drop_duplicates(subset=["ticker", "date"], keep="last")
        merged.to_parquet(self.path, index=False)


def fetch_etf_ohlcv_batch(
    tickers: list[str],
    start: date,
    end: date,
    cache: ParquetCache | None = None,
) -> pd.DataFrame:
    """Fetch multiple ETFs' OHLCV (time-series, ticker-by-ticker).

    2026-05 Bug-F fix: `fetch_etf_ohlcv` returns a DataFrame with only OHLCV
    columns (no 'ticker'/'date') when the upstream pykrx call yields empty.
    Previously this raised KeyError on the column slice; now empties are
    skipped so historical backtests with mixed-availability tickers don't die.
    """
    frames: list[pd.DataFrame] = []
    for t in tickers:
        if cache is not None and cache.has(t, start, end):
            cached = cache.read()
            sub = cached[cached["ticker"] == t]
            sub_dates = pd.to_datetime(sub["date"]).dt.date
            mask = (sub_dates >= start) & (sub_dates <= end)
            frames.append(sub[mask][["ticker", "date", "open", "high", "low", "close", "volume"]])
            continue
        df = fetch_etf_ohlcv(t, start, end)
        if df.empty:
            continue
        if cache is not None:
            cache.write_append(df)
        frames.append(df[["ticker", "date", "open", "high", "low", "close", "volume"]])
    if not frames:
        return pd.DataFrame(
            columns=["ticker", "date", "open", "high", "low", "close", "volume"]
        )
    return pd.concat(frames, ignore_index=True)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_foreign_flow_call(start: date, end: date, market: str = "KOSPI") -> pd.DataFrame:
    """KRX 투자자별 일일 순매수 거래대금 (KRW). 외국인/기관/개인."""
    from pykrx import stock
    return stock.get_market_trading_value_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), market,
    )


def fetch_foreign_flow(
    start: date, end: date, market: str = "KOSPI",
) -> pd.Series:
    """외국인 일별 KOSPI 순매수 (KRW). 양수 = 순매수, 음수 = 순매도.

    Returns pd.Series indexed by date, values in KRW. Empty on failure.
    """
    try:
        raw = _raw_foreign_flow_call(start, end, market)
    except Exception as e:
        logger.warning("Foreign flow fetch failed: %s", e)
        return pd.Series(dtype=float, name="foreign_net")

    if raw is None or raw.empty:
        return pd.Series(dtype=float, name="foreign_net")

    # 컬럼명 — pykrx 버전에 따라 한글 "외국인합계" 또는 "외국인"
    col = None
    for candidate in ("외국인합계", "외국인"):
        if candidate in raw.columns:
            col = candidate
            break
    if col is None:
        logger.warning("Foreign column not found in pykrx flow: %s", list(raw.columns))
        return pd.Series(dtype=float, name="foreign_net")

    s = raw[col].copy()
    s.name = "foreign_net"
    return s


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_credit_balance_call(start: date, end: date) -> pd.DataFrame:
    """KRX 일별 신용공여(=신용잔고) — 전체 시장 합계."""
    from pykrx import stock
    return stock.get_market_trading_value_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), market="KOSPI",
        etf=False, etn=False, elw=False, detail=True,
    )


def _live_credit_balance(start: date, end: date) -> pd.Series:
    try:
        raw = _raw_credit_balance_call(start, end)
    except Exception as e:
        logger.warning("Credit balance fetch failed: %s", e)
        return pd.Series(dtype=float, name="credit_balance")

    if raw is None or raw.empty:
        return pd.Series(dtype=float, name="credit_balance")

    candidates = ["신용공여", "신용잔고", "융자잔고", "신용거래융자"]
    col = next((c for c in candidates if c in raw.columns), None)
    if col is None:
        logger.warning("Credit column not found in pykrx output: %s", list(raw.columns))
        return pd.Series(dtype=float, name="credit_balance")
    s = raw[col].copy()
    s.name = "credit_balance"
    return s


def fetch_credit_balance(
    start: date, end: date,
    use_cache: bool = True,
    max_staleness: int = 7,
) -> pd.Series:
    """KRX 신용잔고 시계열 (KRW). pykrx detail=True의 '신용공여' 컬럼 사용.

    KNOWN LIMITATION (2026-05 audit, pykrx 1.2.8):
      `get_market_trading_value_by_date(detail=True)`가 현재 거래주체별
      "거래대금"(외국인합계/기관계/개인 등) 컬럼만 반환하고 "신용공여" /
      "신용잔고" 컬럼은 포함하지 않는다. KRX가 신용잔고 endpoint를 분리한
      것으로 추정 — 함수명은 trading_value지만 detail=True 시 historical로
      신용 데이터가 같이 왔던 시절의 기대값과 다름.
      → 빈 Series 반환 → kr_margin_debt sentinel(signal="normal", staleness=99).
      해결책: 네이버 증권 신용잔고 페이지 스크레이프 (`finance.naver.com`의
      투자자별 신용공여 잔고 페이지) 또는 KRX 정보데이터시스템 OpenAPI 직접
      호출. 둘 다 신규 모듈 작성 필요.

    Cache: ~/.tradingagents/cache/pykrx_index/credit_balance/{end}.json
    """
    if not use_cache:
        return _live_credit_balance(start, end)

    from tradingagents.dataflows.series_cache import fetch_series_with_cache
    try:
        return fetch_series_with_cache(
            lambda: _live_credit_balance(start, end),
            namespace="pykrx_index",
            cache_key="credit_balance",
            as_of=end,
            max_staleness=max_staleness,
        )
    except Exception:
        return pd.Series(dtype=float, name="credit_balance")


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_index_ohlcv_call(code: str, start: date, end: date) -> pd.DataFrame:
    """KRX 시장 인덱스 OHLCV — KOSPI(1001), KOSDAQ(2001), KOSPI200(1028) 등."""
    from pykrx import stock
    return stock.get_index_ohlcv(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code,
    )


def _live_market_index(code: str, start: date, end: date) -> pd.Series:
    try:
        raw = _raw_index_ohlcv_call(code, start, end)
        if raw is None or raw.empty or "종가" not in raw.columns:
            return pd.Series(dtype=float, name=f"idx_{code}")
        return raw["종가"].rename(f"idx_{code}")
    except Exception as e:
        logger.warning("Market index %s fetch failed: %s", code, e)
        return pd.Series(dtype=float, name=f"idx_{code}")


def fetch_market_index(
    code: str, start: date, end: date,
    use_cache: bool = True,
    max_staleness: int = 7,
) -> pd.Series:
    """KRX 인덱스 종가 시계열.

    1001=KOSPI, 2001=KOSDAQ, 1028=KOSPI200. 실패 시 빈 Series.
    Cache: ~/.tradingagents/cache/pykrx_index/idx_{code}/{end}.json
    """
    if not use_cache:
        return _live_market_index(code, start, end)

    from tradingagents.dataflows.series_cache import fetch_series_with_cache
    try:
        return fetch_series_with_cache(
            lambda: _live_market_index(code, start, end),
            namespace="pykrx_index",
            cache_key=f"idx_{code}",
            as_of=end,
            max_staleness=max_staleness,
        )
    except Exception:
        return pd.Series(dtype=float, name=f"idx_{code}")


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_pykrx_snapshot_call(target_date: date) -> pd.DataFrame:
    """Direct pykrx snapshot call — all ETFs on a single date in one shot."""
    from pykrx import stock
    return stock.get_etf_ohlcv_by_ticker(target_date.strftime("%Y%m%d"))


def fetch_etf_snapshot_by_date(
    target_date: date, cache: ParquetCache | None = None,
) -> pd.DataFrame:
    """One pykrx call returns OHLCV for ALL KRX-listed ETFs on target_date."""
    raw = _raw_pykrx_snapshot_call(target_date)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])

    df = raw.reset_index().rename(columns={
        "티커": "ticker", "시가": "open", "고가": "high", "저가": "low",
        "종가": "close", "거래량": "volume",
    })
    df["date"] = pd.Timestamp(target_date)
    df = df[["ticker", "date", "open", "high", "low", "close", "volume"]]
    if cache is not None:
        cache.write_append(df)
    return df
