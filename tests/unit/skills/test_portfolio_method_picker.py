from unittest.mock import MagicMock

from tradingagents.schemas.portfolio import OptimizationMethod
from tradingagents.skills.portfolio.method_picker import MethodPicker, MethodChoice


def test_method_picker_uses_deep_model():
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    out = MethodChoice(
        method=OptimizationMethod.MIN_VARIANCE,
        params={},
        reasoning="Recession + risk-off → defensive.",
    )
    deep_llm.with_structured_output.return_value.invoke.return_value = out

    picker = MethodPicker(quick_llm, deep_llm)
    result = picker.invoke(
        regime_quadrant="recession_disinflation", regime_confidence=0.85,
        risk_score=7.0, risk_regime="risk_off",
        feedback="",
    )
    assert result.method == OptimizationMethod.MIN_VARIANCE
    deep_llm.with_structured_output.assert_called_once()
