from pathlib import Path

from tradingagents.schemas.news import ImpactAssessment
from tradingagents.skills._base import BaseSubagent
from tradingagents.skills.registry import register_subagent

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "news-impact.md"


class ImpactClassifier(BaseSubagent):
    def __init__(self, llm_quick, llm_deep):
        super().__init__(
            name="classify_event_impact", tier="quick",  # quick model
            schema=ImpactAssessment, prompt_path=PROMPT_PATH,
            llm_quick=llm_quick, llm_deep=llm_deep,
        )


@register_subagent(name="classify_event_impact", category="news")
def classify_event_impact(llm_quick, llm_deep, **inputs) -> ImpactAssessment:
    return ImpactClassifier(llm_quick, llm_deep).invoke(**inputs)
