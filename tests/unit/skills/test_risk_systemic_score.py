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
        vix=28.5, vix_z=2.1, vix_pct=0.92, vix_change_4w=5.0,
        vkospi=24.0, vkospi_change_4w=3.0,
        ig_bps=120, ig_pct=0.75, ig_momentum_z=0.8,
        hy_bps=450, hy_widening=True, hy_momentum_z=1.6,
        fg_label="fear", fg_value=30,
        breadth_kr_adv=0.30, breadth_us_adv=0.35,
        pca_first_share=0.65, pca_concentrated=True,
        mega_cap_concentration_pct=0.10,
        # Tier-1 신규 inputs
        vix_term_ratio=0.92, vix_term_regime="backwardation",
        skew_value=142.0, skew_signal="elevated",
        vxn=32.5, vxn_spread_vs_vix=4.0,
        # Tier-2 신규 inputs
        tips_10y=2.3, real_yields_regime="very_tight",
        funding_spread_bps=25.0, funding_regime="stress",
        credit_quality_spread_bps=130.0, credit_quality_regime="elevated",
        # Tier-3 신규 inputs (KR-specific)
        kr_yc_spread_bps=-15.0, kr_yc_pct=0.05, kr_yc_inverted=True, kr_yc_regime="inverted",
        kr_corp_spread_bps=120.0, kr_corp_regime="stress",
        kr_margin_change_20d=-20.0, kr_margin_signal="deleveraging",
        kr_tier_relative_perf=-4.5, kr_tier_signal="large_cap_risk_off",
        # Tier-4 신규 inputs
        equity_bond_corr_120d=0.4, equity_bond_corr_regime="extreme_positive",
    )
    assert result.regime == "risk_off"
