from unittest.mock import MagicMock

from tradingagents.skills.macro.regime_classifier import RegimeClassifier
from tradingagents.schemas.macro import RegimeClassification


def test_classifier_invokes_llm():
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    out = RegimeClassification(
        quadrant="recession_disinflation",
        confidence=0.82,
        drivers=["yield curve inverted 120 days", "Sahm triggered"],
        reasoning="Curve and labor market both signal recession.",
    )
    deep_llm.with_structured_output.return_value.invoke.return_value = out

    clf = RegimeClassifier(quick_llm, deep_llm)
    result = clf.invoke(
        spread_10y_2y_bps=-25.0, inverted_days_count=120,
        cpi_yoy=2.5, momentum_3mo=1.8, accelerating=False,
        unemployment_rate=4.5, sahm_rule_triggered=True,
        # Tier-1 신규 inputs
        kr_export_yoy=-3.5, kr_export_accelerating=False,
        kr_cli_value=98.5, kr_cli_phase="contraction",
        kr_bsi_mfg=78.0, kr_bsi_contraction=True,
        us_cfnai_ma3=-0.85, us_recession_signal=True,
        us_gdp_nowcast=0.5,
        # Tier-2 신규 inputs
        us_nfci=0.7, us_nfci_regime="tight", us_nfci_tightening=True,
        us_breakeven_5y5y=2.1, us_michigan_1y=2.9, us_inflation_anchored=True,
        fed_path_bps=-80.0, fed_market_view="cut",
        # Tier-3 신규 inputs
        usd_krw=1380.0, krw_change_1m=2.5, fx_regime="usd_risk_off",
        copper_gold_signal="risk_off", copper_gold_percentile=0.15,
        china_cli_value=97.5, china_cli_phase="contraction",
        foreign_flow_20d_krw=-1_500_000_000_000.0, foreign_flow_signal="net_selling",
        # Tier-4 신규 inputs
        us_epu=180.0, us_epu_regime="elevated", us_epu_percentile=0.85,
        vvix=120.0, move=140.0, tail_risk_signal="elevated",
    )
    assert result.quadrant == "recession_disinflation"
