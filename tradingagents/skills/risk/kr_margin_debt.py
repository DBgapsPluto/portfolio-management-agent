from datetime import date

import pandas as pd

from tradingagents.schemas.risk import KRMarginDebtSnapshot
from tradingagents.skills.registry import register_skill


# 신용잔고 signal 임계
# euphoria: 1년 percentile > 0.85 AND 20일 변화 > +10%  (과열, peak signal)
# deleveraging: 20일 변화 < -15% (forced selling, 위기 신호)
EUPHORIA_PCT = 0.85
EUPHORIA_CHANGE = 10.0
DELEVERAGING_CHANGE = -15.0


def _classify_signal(percentile: float, change_20d: float) -> str:
    if percentile > EUPHORIA_PCT and change_20d > EUPHORIA_CHANGE:
        return "euphoria"
    if change_20d < DELEVERAGING_CHANGE:
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

    return KRMarginDebtSnapshot(
        balance_krw=current,
        change_20d_pct=change_20d,
        percentile_1y=percentile,
        signal=_classify_signal(percentile, change_20d),
        source_date=as_of,
    )
