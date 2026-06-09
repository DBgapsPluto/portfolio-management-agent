from datetime import date

import pandas as pd

from tradingagents.schemas.risk import KRCorpSpreadSnapshot
from tradingagents.skills.registry import register_skill


def _classify_regime(percentile: float) -> str:
    if percentile < 0.5:
        return "calm"
    if percentile < 0.85:
        return "elevated"
    return "stress"


@register_skill(name="compute_kr_corp_spread", category="risk")
def compute_kr_corp_spread(
    corp_yield_3y: pd.Series, treasury_3y: pd.Series, as_of: date,
    corp_bbb_3y: pd.Series | None = None,
) -> KRCorpSpreadSnapshot:
    """한국 회사채(AA-) 3y vs 국고채 3y spread → KR 신용 risk.

    스프레드 확대 = 한국 기업 신용 stress (예: 2022년 레고랜드 사태).
    """
    if corp_yield_3y is None or corp_yield_3y.empty or treasury_3y.empty:
        return KRCorpSpreadSnapshot(
            corp_yield_3y=0.0, treasury_3y=0.0, spread_bps=0.0,
            percentile_5y=0.5, regime="calm",
            corp_bbb_yield_3y=0.0, bbb_aa_quality_spread_bps=0.0,
            source_date=as_of, staleness_days=99,
        )

    corp = float(corp_yield_3y.iloc[-1])
    tres = float(treasury_3y.iloc[-1])
    spread_bps = (corp - tres) * 100

    # 5년 percentile 계산 (일별 정렬 기준)
    aligned = pd.concat([corp_yield_3y, treasury_3y], axis=1, join="inner").dropna()
    if len(aligned) < 20:
        percentile = 0.5
    else:
        aligned.columns = ["corp", "tres"]
        spread_series = (aligned["corp"] - aligned["tres"]) * 100
        last_5y = spread_series.tail(252 * 5)
        percentile = float((last_5y < spread_bps).sum() / max(len(last_5y), 1))

    has_bbb = corp_bbb_3y is not None and not corp_bbb_3y.empty
    bbb = float(corp_bbb_3y.iloc[-1]) if has_bbb else 0.0
    quality_spread = (bbb - corp) * 100 if has_bbb else 0.0

    return KRCorpSpreadSnapshot(
        corp_yield_3y=corp,
        treasury_3y=tres,
        spread_bps=spread_bps,
        percentile_5y=percentile,
        regime=_classify_regime(percentile),
        corp_bbb_yield_3y=bbb,
        bbb_aa_quality_spread_bps=quality_spread,
        source_date=as_of,
    )
