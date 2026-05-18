from datetime import date

import pandas as pd

from tradingagents.schemas.risk import FundingStressSnapshot
from tradingagents.skills.registry import register_skill


# (SOFR - 3m T-bill) spread (bps) — funding stress proxy
# TED spread(LIBOR-T-bill, 단종)의 표준 대체 지표
# < +10bps   = calm (정상 마켓)
# 10 ~ 20    = elevated (가벼운 funding pressure)
# > +20bps   = stress (은행 collateral 부족, 위기 신호)
ELEVATED_BPS = 10.0
STRESS_BPS = 20.0


def _classify_regime(spread_bps: float) -> str:
    if spread_bps < ELEVATED_BPS:
        return "calm"
    if spread_bps < STRESS_BPS:
        return "elevated"
    return "stress"


@register_skill(name="compute_funding_stress", category="risk")
def compute_funding_stress(
    sofr_series: pd.Series, tbill_3m_series: pd.Series, as_of: date,
) -> FundingStressSnapshot:
    """SOFR vs 3-month T-bill spread → 은행 funding stress 진단.

    SOFR > T-bill spread 확대 = 은행이 collateral 확보 위해 더 비싼 자금 조달.
    2008 Lehman, 2020 March COVID 모두 spike 발생.
    """
    if sofr_series is None or sofr_series.empty or tbill_3m_series.empty:
        return FundingStressSnapshot(
            sofr=0.0, tbill_3m=0.0, spread_bps=0.0, regime="calm",
            source_date=as_of, staleness_days=99,
        )

    sofr = float(sofr_series.iloc[-1])
    tbill = float(tbill_3m_series.iloc[-1])
    spread_bps = (sofr - tbill) * 100  # % → bps

    return FundingStressSnapshot(
        sofr=sofr,
        tbill_3m=tbill,
        spread_bps=spread_bps,
        regime=_classify_regime(spread_bps),
        source_date=as_of,
    )
