from tradingagents.schemas.technical import (
    IndicatorPanel,
    TrendState,
    ETFRanking,
    Cluster,
)


def test_trend_state_enum():
    assert TrendState.STRONG_UPTREND.value == "strong_uptrend"


def test_indicator_panel():
    p = IndicatorPanel(
        ticker="A069500",
        ma200=425.0,
        ma50=440.0,
        rsi=62.0,
        macd_signal=2.5,
        atr=8.3,
    )
    assert p.ticker == "A069500"


def test_cluster_with_members():
    c = Cluster(
        cluster_id="ai_semis",
        members=["A381180", "A395160", "A446770"],
        avg_internal_correlation=0.83,
        category_label="AI/Semiconductor",
    )
    assert len(c.members) == 3
    assert c.avg_internal_correlation > 0.7
