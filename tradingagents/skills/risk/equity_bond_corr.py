from datetime import date

import pandas as pd

from tradingagents.schemas.risk import EquityBondCorrelationSnapshot
from tradingagents.skills.registry import register_skill


# 60일 rolling correlation 임계
# < -0.3       = normal_hedge      (bonds hedge equity, 60/40 작동)
# -0.3 ~ 0     = weakening_hedge   (분산효과 약화)
# 0 ~ +0.3     = positive_flip     (stagflation/inflation regime 진입)
# > +0.3       = extreme_positive  (1970s, 2022형 regime)
HEDGE_THRESHOLD = -0.3
NEUTRAL_THRESHOLD = 0.0
EXTREME_THRESHOLD = 0.3


def _classify_regime(corr: float) -> str:
    if corr < HEDGE_THRESHOLD:
        return "normal_hedge"
    if corr < NEUTRAL_THRESHOLD:
        return "weakening_hedge"
    if corr < EXTREME_THRESHOLD:
        return "positive_flip"
    return "extreme_positive"


@register_skill(name="compute_equity_bond_corr", category="risk")
def compute_equity_bond_corr(
    equity_returns: pd.Series, bond_returns: pd.Series, as_of: date,
) -> EquityBondCorrelationSnapshot:
    """SPY-TLT 60일 rolling correlation → regime change 진단.

    1970s 스태그플레이션, 2022 인플레이션 시기에 positive flip 발생.
    이 regime에서는 60/40 portfolio의 hedge 효과가 사라져 KR ETF 결정에서도
    채권 비중을 늘려도 분산 안 됨.
    """
    if equity_returns is None or equity_returns.empty or bond_returns.empty:
        return EquityBondCorrelationSnapshot(
            correlation_60d=-0.3, change_3m=0.0, regime="normal_hedge",
            source_date=as_of, staleness_days=99,
        )

    aligned = pd.concat([equity_returns, bond_returns], axis=1, join="inner").dropna()
    if len(aligned) < 60:
        return EquityBondCorrelationSnapshot(
            correlation_60d=-0.3, change_3m=0.0, regime="normal_hedge",
            source_date=as_of, staleness_days=99,
        )

    aligned.columns = ["eq", "bd"]

    # 120일 corr window (2026-05 fix from 60d — 60일은 단일 이벤트로 corr 흔들림,
    # 학계 표준 90-120d). field name correlation_60d는 backward compat 위해 유지.
    WINDOW = 120
    if len(aligned) < WINDOW:
        # 120일 부족 시 60일로 graceful degrade
        WINDOW = 60

    current_corr = float(aligned.tail(WINDOW)["eq"].corr(aligned.tail(WINDOW)["bd"]))

    # 3개월 전(약 63일 전) 동일 window 의 corr — change 계산
    if len(aligned) >= WINDOW + 63:
        prior_window = aligned.iloc[-(WINDOW + 63):-63]
        prior_corr = float(prior_window["eq"].corr(prior_window["bd"]))
        change_3m = current_corr - prior_corr
    else:
        change_3m = 0.0

    return EquityBondCorrelationSnapshot(
        correlation_60d=current_corr,  # 필드명 유지, 실제는 120d
        change_3m=change_3m,
        regime=_classify_regime(current_corr),
        source_date=as_of,
    )
