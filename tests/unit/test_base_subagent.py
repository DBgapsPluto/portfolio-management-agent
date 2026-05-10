from unittest.mock import MagicMock
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from tradingagents.skills._base import BaseSubagent


class _OutSchema(BaseModel):
    label: str
    score: float = Field(ge=0, le=1)


def test_subagent_invoke_with_template(tmp_path):
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("Classify the input: {input}")

    quick_llm = MagicMock()
    deep_llm = MagicMock()
    out = _OutSchema(label="ok", score=0.7)
    structured = MagicMock()
    structured.invoke.return_value = out
    deep_llm.with_structured_output.return_value = structured

    sub = BaseSubagent(
        name="test_sub",
        tier="deep",
        schema=_OutSchema,
        prompt_path=prompt_file,
        llm_quick=quick_llm,
        llm_deep=deep_llm,
    )
    result = sub.invoke(input="hello")
    assert result.label == "ok"
    deep_llm.with_structured_output.assert_called_once_with(_OutSchema)


def test_subagent_uses_quick_when_tier_quick(tmp_path):
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("Hi {x}")
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    quick_llm.with_structured_output.return_value.invoke.return_value = _OutSchema(label="q", score=0.1)

    sub = BaseSubagent(
        name="quick_sub", tier="quick", schema=_OutSchema,
        prompt_path=prompt_file, llm_quick=quick_llm, llm_deep=deep_llm,
    )
    sub.invoke(x="y")
    quick_llm.with_structured_output.assert_called_once()
    deep_llm.with_structured_output.assert_not_called()
