from datetime import date

import pytest
from pydantic import ValidationError

from tradingagents.schemas.macro import RegimeClassification


def test_signal_confidence_optional_default_none():
    r = RegimeClassification(
        quadrant="growth_inflation",
        confidence=0.8,
        drivers=["x"],
        reasoning="y",
        source_date=date(2026, 5, 10),
    )
    assert r.signal_confidence is None  # LLM이 안 채워도 OK (structured-output 비강요)


def test_signal_confidence_accepts_and_bounds():
    r = RegimeClassification(
        quadrant="growth_inflation",
        confidence=0.8,
        drivers=["x"],
        reasoning="y",
        source_date=date(2026, 5, 10),
        signal_confidence=0.42,
    )
    assert r.signal_confidence == 0.42
    # model_copy(update=...) does NOT re-validate in pydantic v2, so construct a
    # fresh model with the out-of-bounds value to reliably trigger validation.
    with pytest.raises(ValidationError):
        RegimeClassification(
            quadrant="growth_inflation",
            confidence=0.8,
            drivers=["x"],
            reasoning="y",
            source_date=date(2026, 5, 10),
            signal_confidence=1.5,
        )
