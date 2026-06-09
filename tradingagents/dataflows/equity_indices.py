"""Equity index price fetcher via yfinance.

Used for tail-risk/sentiment indices that FRED does not host
(CBOE SKEW, etc.).
"""
import logging
from datetime import date, timedelta

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)


EQUITY_INDEX_TICKERS = {
    "skew": "^SKEW",        # CBOE SKEW Index
    "vix_alt": "^VIX",      # VIX backup (when FRED VIXCLS is stale)
    "vxn_alt": "^VXN",      # VXN backup
    "rut": "^RUT",          # Russell 2000 (future breadth use)
    "ndx": "^NDX",          # NASDAQ-100 (future use)
    # Tail risk (FRED VVIXCLS/MOVE 2025년경 삭제 후 yfinance가 유일 소스)
    "vvix": "^VVIX",        # CBOE VIX-of-VIX
    "move": "^MOVE",        # ICE BofA MOVE Index (Treasury vol)
    # China real-time proxies (2026-05 추가 — OECD CLI는 2-3개월 lag이라 보강 필요)
    "usdcnh": "CNY=X",      # USD/CNY 위안화 — China 정책/경제 우려 신호
                            # (offshore CNH=X/USDCNH=X 둘 다 2026 delisted → onshore
                            #  CNY=X proxy. 스케일·임계값(7.20/7.30) 동일.)
    "iron_ore": "TIO=F",    # SGX TSI Iron Ore Futures — China 건설 수요 proxy
    # Tier-2 dual_momentum 벤치마크
    "kospi200": "069500.KS",  # KODEX 200 ETF (KOSPI200 prox; ^KS200 도 가능)
    "spy": "SPY",
    # Plan B fold-in (2026-06-09): sector equity ETFs (B3/B5)
    "sox": "^SOX",       # PHLX Semiconductor Index (B3)
    "smh": "SMH",        # VanEck Semiconductor ETF (B3, 글로벌)
    "eem": "EEM",        # iShares MSCI EM (B5)
    "emb": "EMB",        # iShares EM USD Bond (B5)
    "vwo": "VWO",        # Vanguard FTSE EM (B5 보조)
}


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_yf_history(symbol: str, start: date, end: date) -> pd.DataFrame:
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    df = ticker.history(
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=False,
    )
    if df is not None and not df.empty and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_equity_index_close(
    name: str, start: date, end: date,
    use_cache: bool = True,
    max_staleness: int = 7,
) -> pd.Series:
    """Fetch daily close for an equity index by friendly name.

    Returns pd.Series indexed by datetime. Empty Series on failure.
    Cache: ~/.tradingagents/cache/equity_indices/{name}/{end}.json
    """
    if name not in EQUITY_INDEX_TICKERS:
        raise KeyError(f"unknown equity index: {name!r}")
    symbol = EQUITY_INDEX_TICKERS[name]

    def _live() -> pd.Series:
        df = _raw_yf_history(symbol, start, end)
        if df is None or df.empty or "Close" not in df.columns:
            return pd.Series(dtype=float, name=name)
        s = df["Close"].copy()
        s.name = name
        return s

    if not use_cache:
        return _live()

    from tradingagents.dataflows.series_cache import fetch_series_with_cache
    try:
        return fetch_series_with_cache(
            _live,
            namespace="equity_indices",
            cache_key=name,
            as_of=end,
            max_staleness=max_staleness,
        )
    except Exception as e:
        logger.warning("equity index %s cache+live both failed: %s", name, e)
        return pd.Series(dtype=float, name=name)
