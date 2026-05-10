from unittest.mock import MagicMock

from tradingagents.skills.macro.regime_classifier import RegimeClassifier
from tradingagents.schemas.macro import RegimeClassification


def test_classifier_invokes_llm():
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    out = RegimeClassification(
        quadrant="recession_disinflation",
        confidence=0.82,
        drivers=["yield curve inverted 120 days", "Sahm triggered"],
        reasoning="Curve and labor market both signal recession.",
    )
    deep_llm.with_structured_output.return_value.invoke.return_value = out

    clf = RegimeClassifier(quick_llm, deep_llm)
    result = clf.invoke(
        spread_10y_2y_bps=-25.0, inverted_days_count=120,
        cpi_yoy=2.5, momentum_3mo=1.8, accelerating=False,
        unemployment_rate=4.5, sahm_rule_triggered=True,
    )
    assert result.quadrant == "recession_disinflation"
