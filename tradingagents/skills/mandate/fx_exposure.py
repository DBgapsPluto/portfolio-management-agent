"""포트폴리오 통화별 FX 노출 분해 (리포팅 — spec 2026-06-04).

최종 weight를 노출 통화로 집계. 헤지(H)·국내 → KRW, 해외 UH → 본국 통화.
informational only(하드 게이트 아님). Stage 6 portfolio_manager + philosophy 가 사용.
"""
from __future__ import annotations

from tradingagents.skills.portfolio.candidate_selector import is_hedged

_JPY = ("일본", "니케이", "TOPIX", "엔")
_CNY = ("차이나", "중국", "CSI", "항셍", "HSCEI", "과창판", "홍콩")
_INR = ("인도", "Nifty", "니프티")
_EUR = ("유로", "유럽", "스탁스", "Europe")
_OTHER = ("베트남", "신흥국", "이머징", "emerging")


def exposure_currency(etf) -> str:
    """ETF 한 종목의 노출 통화. 헤지·국내 → KRW, 해외 UH → 본국 통화."""
    name = etf.name or ""
    cat = etf.category or ""
    if is_hedged(name):              # 헤지 = 환노출 제거
        return "KRW"
    if cat.startswith("국내"):        # 국내주식/국내채권
        return "KRW"
    if cat == "금리연계형/초단기채권":
        return "USD" if any(k in name for k in ("달러", "USD", "SOFR")) else "KRW"
    if any(k in name for k in _JPY):
        return "JPY"
    if any(k in name for k in _CNY):
        return "CNY"
    if any(k in name for k in _INR):
        return "INR"
    if any(k in name for k in _EUR):
        return "EUR"
    if any(k in name for k in _OTHER):
        return "기타"
    return "USD"   # 해외 default (미국·금·은·원유·원자재·달러)


def compute_fx_exposure(weights: dict[str, float], universe) -> dict[str, float]:
    """최종 weight를 통화별 노출 %로 분해. 합 ≈ Σ(알려진 ticker weight).

    universe 에 없는 ticker 는 건너뜀(합에서 제외).
    """
    meta = {e.ticker: e for e in universe.etfs}
    out: dict[str, float] = {}
    for t, w in weights.items():
        e = meta.get(t)
        if e is None:
            continue
        cur = exposure_currency(e)
        out[cur] = out.get(cur, 0.0) + w
    return out
