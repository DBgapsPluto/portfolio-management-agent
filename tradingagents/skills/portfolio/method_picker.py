from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tradingagents.schemas.portfolio import OptimizationMethod
from tradingagents.skills._base import BaseSubagent
from tradingagents.skills.registry import register_subagent


class MethodChoice(BaseModel):
    method: OptimizationMethod
    params: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = Field(max_length=300)


PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "asset-allocation.md"


class MethodPicker(BaseSubagent):
    def __init__(self, llm_quick, llm_deep):
        super().__init__(
            name="pick_optimization_method", tier="deep",
            schema=MethodChoice, prompt_path=PROMPT_PATH,
            llm_quick=llm_quick, llm_deep=llm_deep,
        )


@register_subagent(name="pick_optimization_method", category="portfolio")
def pick_optimization_method(llm_quick, llm_deep, **inputs) -> MethodChoice:
    return MethodPicker(llm_quick, llm_deep).invoke(**inputs)
