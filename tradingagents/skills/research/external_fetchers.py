"""External market data fetchers used by Stage 2 factor estimators.

Two endpoints are exposed:

* :func:`fetch_krw_usd_level` — USD/KRW spot from yfinance ``KRW=X``.
* :func:`fetch_sp_trailing_pe` — trailing P/E for SPY (proxy for S&P 500).

Both functions are *temporary* — Stage 1 will eventually own KRW level
(via a dedicated KR FX skill) and S&P valuation (via a market_risk
valuation skill). See spec §3.3 Gap E (KRW) and Gap G (P/E).

The functions are wrapped with a small TTL cache (300 s) to avoid
repeated network calls within a single Stage 2 run. Any exception (or
empty result) is swallowed and a ``logger.warning`` is emitted; the
caller treats ``None`` as missing component and skips it in factor
aggregation.
"""
from __future__ import annotations

import logging
import time
from typing import Final

import yfinance as yf


logger = logging.getLogger(__name__)


_CACHE_TTL_SECONDS: Final[float] = 300.0  # 5 min
_cache: dict[str, tuple[float, float | None]] = {}


def reset_cache() -> None:
    """Clear the TTL cache. Used by tests."""
    _cache.clear()


def _get_cached(key: str) -> tuple[bool, float | None]:
    """Return ``(is_hit, value_or_none)``."""
    entry = _cache.get(key)
    if entry is None:
        return False, None
    stored_at, value = entry
    if time.monotonic() - stored_at > _CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return False, None
    return True, value


def _store(key: str, value: float | None) -> None:
    _cache[key] = (time.monotonic(), value)


def fetch_krw_usd_level(as_of: str | None = None) -> float | None:
    """Return latest USD/KRW close from yfinance (or ``None`` on any error)."""
    cache_key = f"krw:{as_of or 'spot'}"
    hit, cached = _get_cached(cache_key)
    if hit:
        return cached

    try:
        ticker = yf.Ticker("KRW=X")
        hist = ticker.history(period="5d")
        if hist is None or hist.empty or "Close" not in hist.columns:
            logger.warning("fetch_krw_usd_level: empty history for KRW=X")
            _store(cache_key, None)
            return None
        value = float(hist["Close"].iloc[-1])
    except Exception as exc:  # pragma: no cover — covered by mock test
        logger.warning("fetch_krw_usd_level: %s", exc)
        _store(cache_key, None)
        return None

    _store(cache_key, value)
    return value


def fetch_sp_trailing_pe(as_of: str | None = None) -> float | None:
    """Return SPY trailing P/E from yfinance ``.info`` (or ``None`` on any error)."""
    cache_key = f"sp_pe:{as_of or 'spot'}"
    hit, cached = _get_cached(cache_key)
    if hit:
        return cached

    try:
        ticker = yf.Ticker("SPY")
        info = ticker.info
        if not info or "trailingPE" not in info or info["trailingPE"] is None:
            logger.warning("fetch_sp_trailing_pe: missing trailingPE in SPY info")
            _store(cache_key, None)
            return None
        value = float(info["trailingPE"])
    except Exception as exc:  # pragma: no cover — covered by mock test
        logger.warning("fetch_sp_trailing_pe: %s", exc)
        _store(cache_key, None)
        return None

    _store(cache_key, value)
    return value


__all__: Final = [
    "fetch_krw_usd_level",
    "fetch_sp_trailing_pe",
    "reset_cache",
]
