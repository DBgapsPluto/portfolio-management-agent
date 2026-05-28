from datetime import date
from typing import Literal

import pandas as pd

from tradingagents.schemas.risk import KRMarginDebtSnapshot
from tradingagents.skills.registry import register_skill


# 신용잔고 signal 임계
# euphoria:     1년 percentile > 0.85 AND 20일 변화 > +10%  (과열, peak signal)
# deleveraging: 20일 변화의 1년 percentile < 0.10  OR  20일 변화 < -15%
#               (둘 다 fire 하면 forced selling — historical 절대 임계 + base-shift
#                흡수 percentile 의 OR 조합 으로 false-negative 보완)
#
# 2026-05 fix (#6, single observation calibration → dual gate):
#   기존: deleveraging = (change_20d < -15%) 절대 임계 단독.
#   문제: 2021년 1월 peak single observation 기반이라 다른 형태의 peak 에서
#         false-negative 가능. 또한 KR 신용잔고 시계열 자체가 2007+ 짧고
#         euphoria event 사례 부족.
#   변경: change_20d 의 1y rolling percentile < 0.10 추가 — base shift 자동 흡수.
#         절대 임계 -15% 와 OR 결합 (둘 중 하나라도 발화 → 보수적 trigger).
EUPHORIA_PCT = 0.85
EUPHORIA_CHANGE = 10.0
DELEVERAGING_CHANGE_PCT = 0.10   # 20d 변화의 1y 하위 10%
DELEVERAGING_CHANGE = -15.0      # 절대 임계 (legacy backstop)


def _classify_signal(
    percentile: float, change_20d: float, change_20d_percentile: float,
) -> Literal["euphoria", "deleveraging", "normal"]:
    if percentile > EUPHORIA_PCT and change_20d > EUPHORIA_CHANGE:
        return "euphoria"
    if change_20d_percentile < DELEVERAGING_CHANGE_PCT or change_20d < DELEVERAGING_CHANGE:
        return "deleveraging"
    return "normal"


@register_skill(name="compute_kr_margin_debt", category="risk")
def compute_kr_margin_debt(
    margin_series: pd.Series, as_of: date,
) -> KRMarginDebtSnapshot:
    """KRX 신용잔고 → KR retail leverage 추적.

    급증 = retail euphoria (2021년 1월처럼 peak), 급락 = margin call 강제 매도.
    """
    if margin_series is None or margin_series.empty:
        return KRMarginDebtSnapshot(
            balance_krw=0.0, change_20d_pct=0.0, percentile_1y=0.5, signal="normal",
            source_date=as_of, staleness_days=99,
        )

    current = float(margin_series.iloc[-1])

    # 20거래일 변화율
    if len(margin_series) >= 21:
        prior = float(margin_series.iloc[-21])
        change_20d = (current / prior - 1) * 100 if prior > 0 else 0.0
    else:
        change_20d = 0.0

    # 1년 percentile (252 거래일)
    last_1y = margin_series.tail(252)
    percentile = float((last_1y < current).sum() / max(len(last_1y), 1))

    # 20d 변화율의 1y rolling percentile — base-shift 흡수 deleveraging gate.
    # 데이터 < 1년 + 20일 이면 0.5 neutral (절대 임계 단독 의존).
    if len(margin_series) >= 21 + 252:
        rolling_20d = (margin_series / margin_series.shift(21) - 1) * 100
        last_1y_chg = rolling_20d.tail(252).dropna()
        if len(last_1y_chg) >= 50:
            change_20d_percentile = float(
                (last_1y_chg < change_20d).sum() / len(last_1y_chg)
            )
        else:
            change_20d_percentile = 0.5
    else:
        change_20d_percentile = 0.5

    return KRMarginDebtSnapshot(
        balance_krw=current,
        change_20d_pct=change_20d,
        percentile_1y=percentile,
        signal=_classify_signal(percentile, change_20d, change_20d_percentile),
        source_date=as_of,
    )
