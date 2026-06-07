"""현재가 fetch 공용 함수 — portfolio_manager·rebalance engine 공유 (스펙 §7.1).

KRX OpenAPI 는 T+1~T+2 지연 — as_of 당일 데이터가 없으면 직전 영업일로
최대 7일 walk-back. 빈 dict = 휴장/실패(qty=0 graceful).
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

try:
    from tradingagents.dataflows.krx_openapi import fetch_etf_close_map
except Exception:  # import 실패도 graceful — 호출 시 빈 dict
    fetch_etf_close_map = None


def fetch_current_prices(as_of: date) -> dict[str, float]:
    if fetch_etf_close_map is None:
        logger.warning("krx_openapi import 불가 — qty=0")
        return {}
    d = as_of
    for _ in range(8):  # as_of 포함 최대 8일 (주말+연휴 방어)
        try:
            prices = fetch_etf_close_map(d)
        except Exception as e:
            logger.warning("current_prices fetch 실패 (%s): %s — qty=0", d, e)
            return {}
        if prices:
            if d != as_of:
                logger.info("current_prices: %s 미제공 → 직전 %s 종가 사용", as_of, d)
            return prices
        d -= timedelta(days=1)
    logger.warning("current_prices: %s~%s 전 구간 빈 응답 — qty=0", d, as_of)
    return {}
