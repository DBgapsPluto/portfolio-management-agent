from pathlib import Path

from tradingagents.schemas.risk import SystemicRiskScore
from tradingagents.skills._base import BaseSubagent
from tradingagents.skills.registry import register_subagent


PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "risk-analysis.md"


class SystemicScoreClassifier(BaseSubagent):
    def __init__(self, llm_quick, llm_deep):
        super().__init__(
            name="score_systemic_risk", tier="deep",
            schema=SystemicRiskScore, prompt_path=PROMPT_PATH,
            llm_quick=llm_quick, llm_deep=llm_deep,
        )


@register_subagent(name="score_systemic_risk", category="risk")
def score_systemic_risk(llm_quick, llm_deep, **inputs) -> SystemicRiskScore:
    return SystemicScoreClassifier(llm_quick, llm_deep).invoke(**inputs)
