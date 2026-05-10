from unittest.mock import MagicMock
import pytest
from pydantic import BaseModel, Field, ValidationError

from tradingagents.skills._helpers import invoke_with_structured_retry


class _Out(BaseModel):
    label: str
    score: float = Field(ge=0, le=1)


def test_first_call_succeeds():
    llm = MagicMock()
    structured = MagicMock()
    structured.invoke.return_value = _Out(label="ok", score=0.5)
    llm.with_structured_output.return_value = structured

    result = invoke_with_structured_retry(llm, _Out, [{"role": "user", "content": "x"}])
    assert result.label == "ok"
    assert structured.invoke.call_count == 1


def test_first_validation_fails_retry_succeeds():
    llm = MagicMock()
    structured = MagicMock()

    calls = {"n": 0}
    def fake_invoke(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValidationError.from_exception_data("Out", [])
        return _Out(label="recovered", score=0.7)
    structured.invoke = fake_invoke
    llm.with_structured_output.return_value = structured

    result = invoke_with_structured_retry(llm, _Out, [{"role": "user", "content": "x"}])
    assert result.label == "recovered"
    assert calls["n"] == 2


def test_two_failures_raises():
    llm = MagicMock()
    structured = MagicMock()
    def always_fail(messages):
        raise ValidationError.from_exception_data("Out", [])
    structured.invoke = always_fail
    llm.with_structured_output.return_value = structured

    with pytest.raises(ValidationError):
        invoke_with_structured_retry(llm, _Out, [{"role": "user", "content": "x"}], max_retries=1)
