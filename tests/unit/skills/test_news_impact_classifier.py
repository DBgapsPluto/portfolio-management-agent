from unittest.mock import MagicMock

from tradingagents.skills.news.impact_classifier import ImpactClassifier
from tradingagents.schemas.news import ImpactAssessment


def test_classifier_uses_quick_model():
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    out = ImpactAssessment(
        asset_classes_affected=["us_bond", "us_equity"],
        direction="up", severity=4,
        reasoning="Lower rates positive for bonds and equities",
    )
    quick_llm.with_structured_output.return_value.invoke.return_value = out

    clf = ImpactClassifier(quick_llm, deep_llm)
    result = clf.invoke(
        headline="Fed signals 25bp cut", source="Reuters", date="2026-05-10",
    )
    assert result.severity == 4
    quick_llm.with_structured_output.assert_called_once()
    deep_llm.with_structured_output.assert_not_called()
