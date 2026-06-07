"""리밸런싱 공통 엔진 — 보유 재평가·델타 거래계획·재검증 (스펙 §7).

전부 LLM 0 — 순수 결정론. 현금 포지션은 키 "CASH"로 표현.
"""
import logging
from collections.abc import Callable

from tradingagents.dataflows.universe import Universe
from tradingagents.skills.portfolio.sub_category import bucket_for_etf
from tradingagents.skills.mandate.concentration_check import RISK_BUCKET_NAMES

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


def make_is_risk(universe: Universe) -> Callable[[str], bool]:
    """ticker → 위험자산 여부. CASH·미분류·universe 외 ticker는 False."""
    meta = {e.ticker: e for e in universe.etfs}
    def is_risk(ticker: str) -> bool:
        if ticker == CASH_KEY:
            return False
        e = meta.get(ticker)
        return bool(e) and bucket_for_etf(e) in RISK_BUCKET_NAMES
    return is_risk


def risk_total(weights: dict[str, float], is_risk: Callable[[str], bool]) -> float:
    return sum(w for t, w in weights.items() if is_risk(t))
