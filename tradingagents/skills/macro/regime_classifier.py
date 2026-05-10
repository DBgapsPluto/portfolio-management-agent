from pathlib import Path

from tradingagents.schemas.macro import RegimeClassification
from tradingagents.skills._base import BaseSubagent
from tradingagents.skills.registry import register_subagent


PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "macro-analysis.md"


class RegimeClassifier(BaseSubagent):
    def __init__(self, llm_quick, llm_deep):
        super().__init__(
            name="classify_regime", tier="deep",
            schema=RegimeClassification, prompt_path=PROMPT_PATH,
            llm_quick=llm_quick, llm_deep=llm_deep,
        )


@register_subagent(name="classify_regime", category="macro")
def classify_regime(llm_quick, llm_deep, **inputs) -> RegimeClassification:
    """Functional wrapper for registry. Concrete RegimeClassifier is preferred."""
    return RegimeClassifier(llm_quick, llm_deep).invoke(**inputs)
