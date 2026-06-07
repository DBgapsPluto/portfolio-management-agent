"""리밸런싱 공통 엔진 — 보유 재평가·델타 거래계획·재검증 (스펙 §7).

전부 LLM 0 — 순수 결정론. 현금 포지션은 키 "CASH"로 표현.
"""
import logging

logger = logging.getLogger(__name__)

CASH_KEY = "CASH"


def reprice_holdings(
    qty: dict[str, int], cash_krw: int, prices: dict[str, float],
) -> dict[str, float]:
    """보유 수량 × 오늘 종가 + 현금 → 비중(합 1.0). 현금은 CASH_KEY.

    가격 없는 종목은 평가액 0(비중 0) + 경고.
    """
    value: dict[str, float] = {}
    for t, q in qty.items():
        p = prices.get(t, 0.0)
        if p <= 0:
            logger.warning("reprice: %s 가격 없음 → 평가액 0", t)
        value[t] = q * p
    total = sum(value.values()) + max(cash_krw, 0)
    if total <= 0:
        return {}
    weights = {t: v / total for t, v in value.items()}
    if cash_krw > 0:
        weights[CASH_KEY] = cash_krw / total
    return weights
