from unittest.mock import MagicMock

from tradingagents.skills.risk.systemic_score import SystemicScoreClassifier
from tradingagents.schemas.risk import SystemicRiskScore


def test_classifier_invokes_llm():
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    out = SystemicRiskScore(
        score=6.5, regime="risk_off",
        drivers=["VIX spike", "credit spread widening"],
        reasoning="Multiple stress signals.",
    )
    deep_llm.with_structured_output.return_value.invoke.return_value = out

    clf = SystemicScoreClassifier(quick_llm, deep_llm)
    result = clf.invoke(
        vix=28.5, vix_z=2.1, vix_pct=0.92,
        vkospi=24.0,
        ig_bps=120, ig_pct=0.75,
        hy_bps=450, hy_widening=True,
        fg_label="fear", fg_value=30,
        breadth_kr_adv=0.30, breadth_us_adv=0.35,
        pca_first_share=0.65, pca_concentrated=True,
    )
    assert result.regime == "risk_off"
