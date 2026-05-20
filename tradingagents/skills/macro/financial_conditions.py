from datetime import date

import pandas as pd

from tradingagents.schemas.macro import FinancialConditionsSnapshot
from tradingagents.skills.registry import register_skill


# 10y percentile-based regime (2026-05 fix).
# 이전: 절대 임계 (-0.5/0.5/1.0) — 2008년 이후 시장 구조 변경(QE 영구화 등)으로
# 2010+ NFCI 평균이 -0.3 부근. "0 = 평균"이 더 이상 정확하지 않음. NFCI는 weekly
# 라서 10y ≈ 520 obs 충분히 안정적.
EASY_PCT = 0.20      # 10y 하위 20%
NEUTRAL_PCT = 0.70   # 10y 20-70%
TIGHT_PCT = 0.90     # 10y 70-90%
# > 0.90 → crisis


def _classify_regime(percentile_10y: float) -> str:
    if percentile_10y < EASY_PCT:
        return "easy"
    if percentile_10y < NEUTRAL_PCT:
        return "neutral"
    if percentile_10y < TIGHT_PCT:
        return "tight"
    return "crisis"


@register_skill(name="compute_financial_conditions", category="macro")
def compute_financial_conditions(
    nfci_series: pd.Series, anfci_series: pd.Series, as_of: date,
) -> FinancialConditionsSnapshot:
    """NFCI + ANFCI → 10y percentile-based regime + 4주 추세 tightening flag."""
    nfci = float(nfci_series.iloc[-1])
    anfci = float(anfci_series.iloc[-1])

    # 10y percentile (weekly, ~520 obs)
    last_10y = nfci_series.tail(520)
    if len(last_10y) >= 50:
        percentile = float((last_10y < nfci).sum() / len(last_10y))
        regime = _classify_regime(percentile)
    else:
        # 데이터 부족 시 절대 임계 fallback
        if nfci < -0.5:
            regime = "easy"
        elif nfci < 0.5:
            regime = "neutral"
        elif nfci < 1.0:
            regime = "tight"
        else:
            regime = "crisis"

    # 4주(=약 1개월) 변화. NFCI는 weekly. 5개 미만이면 0.
    if len(nfci_series) >= 5:
        change_4w = float(nfci_series.iloc[-1] - nfci_series.iloc[-5])
    else:
        change_4w = 0.0
    tightening = change_4w > 0.2

    return FinancialConditionsSnapshot(
        nfci=nfci,
        anfci=anfci,
        regime=regime,
        tightening=tightening,
        source_date=as_of,
    )
