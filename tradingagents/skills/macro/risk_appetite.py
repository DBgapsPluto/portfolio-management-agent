from datetime import date

import pandas as pd

from tradingagents.schemas.macro import RiskAppetiteSnapshot
from tradingagents.skills.registry import register_skill


def _classify_signal(percentile: float) -> str:
    if percentile > 0.7:
        return "risk_on"
    if percentile < 0.3:
        return "risk_off"
    return "neutral"


@register_skill(name="compute_risk_appetite", category="macro")
def compute_risk_appetite(
    copper: pd.Series, gold: pd.Series, as_of: date,
) -> RiskAppetiteSnapshot:
    """Copper/Gold ratio percentile rank (1y).

    Ratio 상승 = cyclical 위에 cu 매수 우위 = risk-on. 10y yield와 0.7+ 상관.
    """
    aligned = pd.concat([copper, gold], axis=1, join="inner").dropna()
    aligned.columns = ["cu", "au"]
    if aligned.empty:
        # 데이터 없으면 sentinel
        return RiskAppetiteSnapshot(
            copper_price=0.0, gold_price=0.0, ratio=0.0,
            ratio_percentile_1y=0.5, signal="neutral",
            source_date=as_of, staleness_days=99,
        )

    aligned["ratio"] = aligned["cu"] / aligned["au"] * 100.0
    current_ratio = float(aligned["ratio"].iloc[-1])

    # 5년 percentile (≈252×5 거래일, 2026-05 fix).
    # 이전: 1y window — 2024-2025 Cu supply shock (DRC 광산 폐쇄, smelting capacity
    # 부족 등)으로 ratio가 fundamental과 분리되어 signal degrade. 5y로 확장해
    # 단발성 supply 노이즈에 robust 하게.
    last_5y = aligned["ratio"].tail(252 * 5)
    percentile = float((last_5y < current_ratio).sum() / max(len(last_5y), 1))

    return RiskAppetiteSnapshot(
        copper_price=float(aligned["cu"].iloc[-1]),
        gold_price=float(aligned["au"].iloc[-1]),
        ratio=current_ratio,
        ratio_percentile_1y=percentile,  # 필드명은 backward compat 위해 유지, 의미는 5y
        signal=_classify_signal(percentile),
        source_date=as_of,
    )
