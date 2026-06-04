import logging
import threading
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)

# pykrx/KRX 가 timeout 없이 socket read 에서 무한 hang → 각 ETF 호출에 하드 timeout.
_PYKRX_CALL_TIMEOUT_S = 30


def _run_with_timeout(fn, timeout: float):
    """fn() 을 daemon thread 에서 실행, timeout 초과 시 TimeoutError (스레드-safe).

    SIGALRM 과 달리 메인 스레드가 아니어도(langgraph 병렬 노드) 동작하고, hang
    스레드는 daemon 이라 프로세스 종료를 막지 않는다. 내부 예외는 그대로 전파.
    """
    box: dict = {}

    def _worker():
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001 — 내부 예외 전파용
            box["error"] = e

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f"call exceeded {timeout}s hard timeout")
    if "error" in box:
        raise box["error"]
    return box.get("result")


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
    """Fetch one ETF's OHLCV. Returns columns [open, high, low, close, volume, ticker, date].

    pykrx 무한 hang 방어: 호출(retry 포함)을 하드 timeout 으로 감싸고, timeout/실패
    ticker 는 빈 df 로 graceful skip + 로그 (silent 누락 방지 — prices 가 technical
    analyst 전체의 유일 입력이라 한 ticker hang 이 노드 전체를 freeze 시킨다).
    """
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    try:
        raw = _run_with_timeout(
            lambda: _raw_pykrx_call(ticker, start, end), _PYKRX_CALL_TIMEOUT_S,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "ETF %s OHLCV fetch failed (%s) — skip", ticker, type(e).__name__,
        )
        return empty
    if raw is None or raw.empty:
        return empty

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


def _live_credit_balance(start: date, end: date) -> pd.Series:
    """KOFIA FreeSIS 신용거래융자 잔고 (KRW).

    pykrx 1.2.8 / KRX 공식 OpenAPI / KRX 정보데이터시스템 / 한국은행 ECOS 어디에도
    시장 전체 신용잔고가 없어 금융투자협회 FreeSIS 로 이전 (2026-06-04, 브라우저
    XHR 캡처로 plain-requests endpoint·schema 확정).
    """
    from tradingagents.dataflows.kofia_freesis import fetch_credit_loan_balance
    return fetch_credit_loan_balance(start, end)


def fetch_credit_balance(
    start: date, end: date,
    use_cache: bool = True,
    max_staleness: int = 7,
) -> pd.Series:
    """시장 전체 신용거래융자 잔고 시계열 (KRW). 소스: KOFIA FreeSIS.

    데이터 소스 (2026-06-04 실증으로 확정):
      KRX 공식 OpenAPI / KRX 정보데이터시스템 / 한국은행 ECOS 어디에도 시장 전체
      신용잔고가 없음 (pykrx `get_market_trading_value_by_date` 는 종목별 거래대금
      함수라 부적합). 유일한 소스는 금융투자협회 FreeSIS(신용공여 잔고 추이,
      STATSCU0100000070) 이며 `kofia_freesis.fetch_credit_loan_balance` 가 담당.
      실패 시 빈 Series → kr_margin_debt sentinel(signal="normal", staleness=99).

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


# KRX index code → (공식 OpenAPI IDX_NM, series). pykrx get_index_ohlcv 가
# KRX schema 변경(영문 컬럼)으로 깨져 공식 API(idx/{series}_dd_trd)로 이전.
_INDEX_CODE_MAP: dict[str, tuple[str, str]] = {
    "1001": ("코스피", "kospi"),
    "1028": ("코스피 200", "kospi"),
    "2001": ("코스닥", "kosdaq"),
}


def _live_market_index(code: str, start: date, end: date) -> pd.Series:
    """KRX 지수 종가 시계열 — 공식 OpenAPI (날짜별 루프, series_cache 가 캐시)."""
    name = f"idx_{code}"
    idx_name, series = _INDEX_CODE_MAP.get(code, (None, None))
    if idx_name is None:
        logger.warning("Market index %s: unknown code (no official mapping)", code)
        return pd.Series(dtype=float, name=name)
    try:
        from tradingagents.dataflows.krx_openapi import fetch_index_series
        data = fetch_index_series(start, end, idx_name, series)
        if not data:
            return pd.Series(dtype=float, name=name)
        idx = pd.to_datetime(list(data.keys()), format="%Y%m%d")
        return pd.Series(list(data.values()), index=idx, name=name).sort_index()
    except Exception as e:
        logger.warning("Market index %s fetch failed: %s", code, e)
        return pd.Series(dtype=float, name=name)


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
