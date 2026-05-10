from tradingagents.schemas.risk import (
    VolatilitySnapshot,
    SpreadSnapshot,
    SentimentSnapshot,
    BreadthSnapshot,
    PCASnapshot,
    SystemicRiskScore,
)


def test_volatility_with_zscore():
    v = VolatilitySnapshot(
        index_name="VIX",
        current_value=18.5,
        zscore_30d=0.4,
        percentile_5y=0.55,
    )
    assert v.current_value == 18.5


def test_systemic_risk_score_bounded():
    s = SystemicRiskScore(
        score=6.5,
        regime="risk_off",
        drivers=["VIX spike", "credit spread widening"],
    )
    assert 0 <= s.score <= 10


def test_pca_concentration():
    p = PCASnapshot(
        first_eigenvalue_share=0.72,
        n_assets_analyzed=12,
        is_concentrated=True,
    )
    assert p.is_concentrated is True
