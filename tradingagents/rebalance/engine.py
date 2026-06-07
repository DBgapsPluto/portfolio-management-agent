"""리밸런싱 공통 엔진 — 보유 재평가·델타 거래계획·재검증 (스펙 §7).

전부 LLM 0 — 순수 결정론. 현금 포지션은 키 "CASH"로 표현.
"""
import logging
from collections.abc import Callable

from tradingagents.dataflows.universe import Universe
from tradingagents.skills.portfolio.sub_category import bucket_for_etf
from tradingagents.skills.mandate.concentration_check import (
    RISK_BUCKET_NAMES, HARD_SINGLE_CAP, HARD_RISK_ASSET_CAP, FLOAT_TOLERANCE,
)

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


def compute_deltas(
    current: dict[str, float], target: dict[str, float],
    dials: dict, is_risk: Callable[[str], bool],
) -> tuple[dict[str, float], list[str]]:
    """목표−현재 델타. no-trade band 적용, 단 hard cap-방향 위반 해소 델타는 예외 실행.

    band 예외는 hard mandate cap(단일 0.20 / 위험 0.70) 기준 — finding #2.
    Returns (delta(실행할 것만), skipped_tickers). CASH_KEY 는 제외.
    """
    band = dials["no_trade_band"]
    cur_risk = risk_total(current, is_risk)

    tickers = (set(current) | set(target)) - {CASH_KEY}
    delta: dict[str, float] = {}
    skipped: list[str] = []
    for t in tickers:
        d = target.get(t, 0.0) - current.get(t, 0.0)
        if abs(d) >= band:
            delta[t] = d
            continue
        over_single = (current.get(t, 0.0) > HARD_SINGLE_CAP
                       and d < 0
                       and current.get(t, 0.0) + d <= HARD_SINGLE_CAP + FLOAT_TOLERANCE)
        over_risk = (cur_risk > HARD_RISK_ASSET_CAP and is_risk(t) and d < 0)
        if over_single or over_risk:
            delta[t] = d
        elif d != 0.0:
            skipped.append(t)
    return delta, skipped
