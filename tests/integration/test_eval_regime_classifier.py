"""Eval — classify_regime accuracy across 8 historical regime cases.

Per design §15, this is the LLM eval that should be re-run when classifier
prompts change.

Tier 1-4 확장 후 각 case에 시대별 적절한 13개 신규 input을 보강.
pre-2000 케이스는 KR/China/EPU/VVIX 신호가 시대적으로 부재하므로 중립값 사용.

Skipped by default (requires API access). Run with:
    pytest -m eval tests/integration/test_eval_regime_classifier.py
"""
import pytest

from tradingagents.skills.macro.regime_classifier import RegimeClassifier


# 중립 default. 시대적으로 데이터 없는 경우 사용.
_NEUTRAL_DEFAULTS = dict(
    # Tier 1
    kr_export_yoy=0.0, kr_export_accelerating=False,
    kr_cli_value=100.0, kr_cli_phase="expansion",
    kr_bsi_mfg=85.0, kr_bsi_contraction=False,
    us_cfnai_ma3=0.0, us_recession_signal=False,
    us_gdp_nowcast=2.0,
    # Tier 2
    us_nfci=0.0, us_nfci_regime="neutral", us_nfci_tightening=False,
    us_breakeven_5y5y=2.0, us_michigan_1y=3.0, us_inflation_anchored=True,
    fed_path_bps=0.0, fed_market_view="hold",
    # Tier 3
    usd_krw=1300.0, krw_change_1m=0.0, fx_regime="neutral",
    copper_gold_signal="neutral", copper_gold_percentile=0.5,
    china_cli_value=100.0, china_cli_phase="expansion",
    foreign_flow_20d_krw=0.0, foreign_flow_signal="neutral",
    # Tier 4
    us_epu=100.0, us_epu_regime="normal", us_epu_percentile=0.5,
    vvix=90.0, move=100.0, tail_risk_signal="calm",
)


def _case(base: dict, **overrides) -> dict:
    """Merge neutral defaults + case-specific Tier 1-4 inputs + base 7 inputs."""
    merged = dict(_NEUTRAL_DEFAULTS)
    merged.update(overrides)
    merged.update(base)
    return merged


HISTORICAL_CASES = [
    ("2008-12 Lehman aftermath, CPI plunging",
     _case(
         dict(
             # Dec 2008: CPI YoY dropped to 0.1% (from 5.6% peak in Jul). Clear disinflation.
             spread_10y_2y_bps=140.0, inverted_days_count=180,
             cpi_yoy=0.1, momentum_3mo=-10.0, accelerating=False,
             unemployment_rate=7.3, sahm_rule_triggered=True,
         ),
         # Tier 1: deep contraction
         kr_export_yoy=-25.0, kr_export_accelerating=False,
         kr_cli_value=95.0, kr_cli_phase="contraction",
         kr_bsi_mfg=65.0, kr_bsi_contraction=True,
         us_cfnai_ma3=-2.5, us_recession_signal=True,
         us_gdp_nowcast=-3.0,
         # Tier 2: crisis financial conditions, downside infl, deep cuts
         us_nfci=2.5, us_nfci_regime="crisis", us_nfci_tightening=True,
         us_breakeven_5y5y=1.0, us_michigan_1y=2.0, us_inflation_anchored=False,
         fed_path_bps=-300.0, fed_market_view="cut",
         # Tier 3: USD risk-off, foreign selling, China contraction
         usd_krw=1450.0, krw_change_1m=15.0, fx_regime="usd_risk_off",
         copper_gold_signal="risk_off", copper_gold_percentile=0.05,
         china_cli_value=95.0, china_cli_phase="contraction",
         foreign_flow_20d_krw=-3_000_000_000_000.0, foreign_flow_signal="net_selling",
         # Tier 4: extreme everywhere
         us_epu=300.0, us_epu_regime="extreme", us_epu_percentile=1.0,
         vvix=200.0, move=250.0, tail_risk_signal="extreme",
     ),
     "recession_disinflation"),

    ("2022-06 peak inflation, growth",
     _case(
         dict(
             spread_10y_2y_bps=10.0, inverted_days_count=0,
             cpi_yoy=9.1, momentum_3mo=8.0, accelerating=True,
             unemployment_rate=3.6, sahm_rule_triggered=False,
         ),
         kr_export_yoy=10.0, kr_export_accelerating=False,
         kr_cli_value=99.0, kr_cli_phase="peak",
         kr_bsi_mfg=92.0, kr_bsi_contraction=False,
         us_cfnai_ma3=0.0, us_recession_signal=False, us_gdp_nowcast=-0.5,
         us_nfci=-0.3, us_nfci_regime="easy", us_nfci_tightening=True,
         us_breakeven_5y5y=2.7, us_michigan_1y=5.4, us_inflation_anchored=False,
         fed_path_bps=150.0, fed_market_view="hike",
         usd_krw=1300.0, krw_change_1m=3.0, fx_regime="usd_risk_off",
         copper_gold_signal="neutral", copper_gold_percentile=0.5,
         china_cli_value=100.0, china_cli_phase="expansion",
         foreign_flow_20d_krw=-2_000_000_000_000.0, foreign_flow_signal="net_selling",
         us_epu=200.0, us_epu_regime="extreme", us_epu_percentile=0.95,
         vvix=110.0, move=120.0, tail_risk_signal="elevated",
     ),
     "growth_inflation"),

    ("2020-04 COVID recession + supply shock",
     _case(
         dict(
             spread_10y_2y_bps=50.0, inverted_days_count=0,
             cpi_yoy=0.3, momentum_3mo=-1.0, accelerating=False,
             unemployment_rate=14.7, sahm_rule_triggered=True,
         ),
         kr_export_yoy=-25.0, kr_export_accelerating=False,
         kr_cli_value=92.0, kr_cli_phase="contraction",
         kr_bsi_mfg=60.0, kr_bsi_contraction=True,
         us_cfnai_ma3=-6.0, us_recession_signal=True, us_gdp_nowcast=-30.0,
         us_nfci=2.5, us_nfci_regime="crisis", us_nfci_tightening=True,
         us_breakeven_5y5y=0.8, us_michigan_1y=2.0, us_inflation_anchored=False,
         fed_path_bps=-100.0, fed_market_view="cut",
         usd_krw=1280.0, krw_change_1m=8.0, fx_regime="usd_risk_off",
         copper_gold_signal="risk_off", copper_gold_percentile=0.05,
         china_cli_value=95.0, china_cli_phase="contraction",
         foreign_flow_20d_krw=-2_000_000_000_000.0, foreign_flow_signal="net_selling",
         us_epu=400.0, us_epu_regime="extreme", us_epu_percentile=1.0,
         vvix=200.0, move=180.0, tail_risk_signal="extreme",
     ),
     "recession_disinflation"),

    ("2017-Q3 Goldilocks expansion",
     _case(
         dict(
             spread_10y_2y_bps=80.0, inverted_days_count=0,
             cpi_yoy=2.0, momentum_3mo=1.8, accelerating=False,
             unemployment_rate=4.2, sahm_rule_triggered=False,
         ),
         kr_export_yoy=20.0, kr_export_accelerating=True,
         kr_cli_value=101.0, kr_cli_phase="expansion",
         kr_bsi_mfg=95.0, kr_bsi_contraction=False,
         us_cfnai_ma3=0.3, us_recession_signal=False, us_gdp_nowcast=2.5,
         us_nfci=-0.7, us_nfci_regime="easy", us_nfci_tightening=False,
         us_breakeven_5y5y=2.0, us_michigan_1y=2.5, us_inflation_anchored=True,
         fed_path_bps=50.0, fed_market_view="hold",
         usd_krw=1130.0, krw_change_1m=-2.0, fx_regime="krw_strong",
         copper_gold_signal="risk_on", copper_gold_percentile=0.85,
         china_cli_value=101.0, china_cli_phase="expansion",
         foreign_flow_20d_krw=2_000_000_000_000.0, foreign_flow_signal="net_buying",
         us_epu=100.0, us_epu_regime="normal", us_epu_percentile=0.5,
         vvix=85.0, move=70.0, tail_risk_signal="calm",
     ),
     "growth_disinflation"),

    ("1973-12 stagflation (oil shock)",
     _case(
         dict(
             spread_10y_2y_bps=-20.0, inverted_days_count=90,
             cpi_yoy=8.7, momentum_3mo=9.0, accelerating=True,
             unemployment_rate=4.9, sahm_rule_triggered=True,
         ),
         us_cfnai_ma3=-0.5, us_recession_signal=False, us_gdp_nowcast=1.0,
         us_nfci=1.5, us_nfci_regime="crisis", us_nfci_tightening=True,
         us_breakeven_5y5y=4.0, us_michigan_1y=8.0, us_inflation_anchored=False,
         fed_path_bps=100.0, fed_market_view="hike",
         us_epu=150.0, us_epu_regime="elevated", us_epu_percentile=0.8,
         vvix=100.0, move=120.0, tail_risk_signal="elevated",
         # KR/China 데이터 부재 → 중립 default
     ),
     "recession_inflation"),

    ("2007-12 pre-GFC late cycle",
     _case(
         dict(
             spread_10y_2y_bps=5.0, inverted_days_count=30,
             cpi_yoy=4.1, momentum_3mo=4.5, accelerating=True,
             unemployment_rate=5.0, sahm_rule_triggered=False,
         ),
         kr_export_yoy=15.0, kr_export_accelerating=True,
         kr_cli_value=102.0, kr_cli_phase="peak",
         kr_bsi_mfg=98.0, kr_bsi_contraction=False,
         us_cfnai_ma3=-0.2, us_recession_signal=False, us_gdp_nowcast=1.5,
         us_nfci=0.2, us_nfci_regime="neutral", us_nfci_tightening=True,
         us_breakeven_5y5y=2.4, us_michigan_1y=3.5, us_inflation_anchored=True,
         fed_path_bps=-50.0, fed_market_view="cut",
         usd_krw=930.0, krw_change_1m=-1.0, fx_regime="neutral",
         copper_gold_signal="risk_on", copper_gold_percentile=0.8,
         china_cli_value=104.0, china_cli_phase="expansion",
         foreign_flow_20d_krw=-500_000_000_000.0, foreign_flow_signal="neutral",
         us_epu=120.0, us_epu_regime="normal", us_epu_percentile=0.6,
         vvix=85.0, move=85.0, tail_risk_signal="calm",
     ),
     "growth_inflation"),

    ("2014-12 disinflation expansion",
     _case(
         dict(
             spread_10y_2y_bps=150.0, inverted_days_count=0,
             cpi_yoy=0.8, momentum_3mo=-1.5, accelerating=False,
             unemployment_rate=5.6, sahm_rule_triggered=False,
         ),
         kr_export_yoy=2.0, kr_export_accelerating=False,
         kr_cli_value=99.0, kr_cli_phase="contraction",
         kr_bsi_mfg=85.0, kr_bsi_contraction=False,
         us_cfnai_ma3=0.2, us_recession_signal=False, us_gdp_nowcast=2.0,
         us_nfci=-0.5, us_nfci_regime="easy", us_nfci_tightening=False,
         us_breakeven_5y5y=1.6, us_michigan_1y=2.8, us_inflation_anchored=True,
         fed_path_bps=50.0, fed_market_view="hold",
         usd_krw=1100.0, krw_change_1m=2.0, fx_regime="neutral",
         copper_gold_signal="risk_off", copper_gold_percentile=0.2,
         china_cli_value=99.0, china_cli_phase="contraction",
         foreign_flow_20d_krw=500_000_000_000.0, foreign_flow_signal="neutral",
         us_epu=110.0, us_epu_regime="normal", us_epu_percentile=0.5,
         vvix=85.0, move=75.0, tail_risk_signal="calm",
     ),
     "growth_disinflation"),

    ("2026-05 inverted + rising unemployment + KR contraction",
     _case(
         dict(
             spread_10y_2y_bps=-10.0, inverted_days_count=120,
             cpi_yoy=2.8, momentum_3mo=2.0, accelerating=False,
             unemployment_rate=4.5, sahm_rule_triggered=True,
         ),
         kr_export_yoy=-3.0, kr_export_accelerating=False,
         kr_cli_value=98.0, kr_cli_phase="contraction",
         kr_bsi_mfg=82.0, kr_bsi_contraction=False,
         us_cfnai_ma3=-0.4, us_recession_signal=False, us_gdp_nowcast=0.5,
         us_nfci=0.3, us_nfci_regime="neutral", us_nfci_tightening=True,
         us_breakeven_5y5y=2.4, us_michigan_1y=3.0, us_inflation_anchored=True,
         fed_path_bps=-80.0, fed_market_view="cut",
         usd_krw=1380.0, krw_change_1m=2.5, fx_regime="usd_risk_off",
         copper_gold_signal="risk_off", copper_gold_percentile=0.25,
         china_cli_value=98.0, china_cli_phase="contraction",
         foreign_flow_20d_krw=-1_500_000_000_000.0, foreign_flow_signal="net_selling",
         us_epu=170.0, us_epu_regime="elevated", us_epu_percentile=0.85,
         vvix=110.0, move=130.0, tail_risk_signal="elevated",
     ),
     "recession_disinflation"),
]


@pytest.mark.eval
@pytest.mark.parametrize("case_name,inputs,expected", HISTORICAL_CASES)
def test_regime_classifier_accuracy(case_name, inputs, expected):
    """Real-LLM eval. Skipped by default (mark `eval`)."""
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.llm_clients import create_llm_client

    quick = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["quick_think_llm"],
    ).get_llm()
    deep = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["deep_think_llm"],
    ).get_llm()

    clf = RegimeClassifier(quick, deep)
    result = clf.invoke(**inputs)
    assert result.quadrant == expected, (
        f"{case_name}: got {result.quadrant}, expected {expected}"
    )
    # Tier 1-4 확장 후 임계 완화. prompt가 ambiguity 시 conf 0.6-0.7 하향을 명시했음.
    # 0.6 이상이면 acceptable. 더 낮으면 분류 자체가 의문스러운 case.
    assert result.confidence >= 0.6, (
        f"{case_name}: confidence too low {result.confidence}"
    )
