from tradingagents.schemas.technical import TrendState, IndicatorPanel
from tradingagents.skills.registry import register_skill


@register_skill(name="detect_trend_state", category="technical")
def detect_trend_state(panel: IndicatorPanel, current_price: float) -> TrendState:
    above_ma200 = current_price > panel.ma200
    above_ma50 = current_price > panel.ma50
    ma50_above_ma200 = panel.ma50 > panel.ma200

    if above_ma200 and above_ma50 and ma50_above_ma200 and panel.rsi > 60:
        return TrendState.STRONG_UPTREND
    if above_ma200 and above_ma50:
        return TrendState.UPTREND
    if not above_ma200 and not above_ma50 and panel.rsi < 40:
        return TrendState.BREAKDOWN
    if not above_ma200 and not above_ma50:
        return TrendState.DOWNTREND
    return TrendState.NEUTRAL
