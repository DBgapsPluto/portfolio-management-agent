"""Eval — score_systemic_risk accuracy across 8 historical market stress cases.

market_risk 4-Tier 확장 후 (6 → 33 dimension) prompt 검증.

각 case에 33 inputs 모두 명시 (Tier 1-4 신호 포함).
expected: (score_min, score_max) range + expected regime.

Skipped by default (requires API access). Run with:
    pytest -m eval tests/integration/test_eval_systemic_score.py
"""
import pytest

from tradingagents.skills.risk.systemic_score import SystemicScoreClassifier


# 중립 default — 데이터 부재 case 또는 보조 dimension용
_NEUTRAL_DEFAULTS = dict(
    # Baseline
    vix=18.0, vix_z=0.0, vix_pct=0.5, vix_change_4w=0.0,
    vkospi=20.0, vkospi_change_4w=0.0,
    ig_bps=110.0, ig_pct=0.5, ig_momentum_z=0.0,
    hy_bps=350.0, hy_widening=False, hy_momentum_z=0.0,
    fg_label="neutral", fg_value=50,
    breadth_kr_adv=0.55, breadth_us_adv=0.55,
    pca_first_share=0.5, pca_concentrated=False,
    mega_cap_concentration_pct=0.50,
    # Tier 1
    vix_term_ratio=1.05, vix_term_regime="contango",
    skew_value=118.0, skew_signal="low",
    vxn=22.0, vxn_spread_vs_vix=2.0,
    # Tier 2
    tips_10y=1.0, real_yields_regime="neutral",
    funding_spread_bps=5.0, funding_regime="calm",
    credit_quality_spread_bps=80.0, credit_quality_regime="calm",
    # Tier 3
    kr_yc_spread_bps=60.0, kr_yc_pct=0.55, kr_yc_inverted=False, kr_yc_regime="normal",
    kr_corp_spread_bps=60.0, kr_corp_regime="calm",
    kr_margin_change_20d=0.0, kr_margin_signal="normal",
    kr_tier_relative_perf=0.0, kr_tier_signal="neutral",
    # Tier 4
    equity_bond_corr_120d=-0.4, equity_bond_corr_regime="normal_hedge",
)


def _case(**overrides) -> dict:
    merged = dict(_NEUTRAL_DEFAULTS)
    merged.update(overrides)
    return merged


# (case_name, inputs, score_min, score_max, expected_regime)
HISTORICAL_CASES = [
    (
        "2008-10 Lehman aftermath (peak crisis)",
        _case(
            vix=60.0, vix_z=4.0, vix_pct=0.99, vix_change_4w=30.0,
            vkospi=55.0, vkospi_change_4w=25.0,
            ig_bps=400.0, ig_pct=0.99, ig_momentum_z=2.5,
            hy_bps=1500.0, hy_widening=True, hy_momentum_z=2.8,
            fg_label="extreme_fear", fg_value=10,
            breadth_kr_adv=0.10, breadth_us_adv=0.15,
            pca_first_share=0.85, pca_concentrated=True,
            vix_term_ratio=0.75, vix_term_regime="backwardation",
            skew_value=150.0, skew_signal="extreme",
            vxn=70.0, vxn_spread_vs_vix=10.0,
            tips_10y=2.5, real_yields_regime="very_tight",
            funding_spread_bps=80.0, funding_regime="stress",
            credit_quality_spread_bps=300.0, credit_quality_regime="stress",
            kr_yc_spread_bps=-20.0, kr_yc_inverted=True, kr_yc_regime="inverted",
            kr_corp_spread_bps=250.0, kr_corp_regime="stress",
            kr_margin_change_20d=-30.0, kr_margin_signal="deleveraging",
            kr_tier_relative_perf=-8.0, kr_tier_signal="large_cap_risk_off",
            equity_bond_corr_120d=0.5, equity_bond_corr_regime="extreme_positive",
        ),
        8.5, 10.0, "risk_off",
    ),
    (
        "2020-03 COVID March crash",
        _case(
            vix=82.0, vix_z=5.0, vix_pct=1.0, vix_change_4w=50.0,
            vkospi=70.0, vkospi_change_4w=40.0,
            ig_bps=380.0, ig_pct=0.97, ig_momentum_z=2.7,
            hy_bps=1100.0, hy_widening=True, hy_momentum_z=2.9,
            fg_label="extreme_fear", fg_value=5,
            breadth_kr_adv=0.05, breadth_us_adv=0.10,
            pca_first_share=0.92, pca_concentrated=True,
            vix_term_ratio=0.70, vix_term_regime="backwardation",
            skew_value=155.0, skew_signal="extreme",
            vxn=85.0, vxn_spread_vs_vix=3.0,
            tips_10y=-0.5, real_yields_regime="accommodative",
            funding_spread_bps=100.0, funding_regime="stress",
            credit_quality_spread_bps=280.0, credit_quality_regime="stress",
            kr_yc_spread_bps=10.0, kr_yc_inverted=False, kr_yc_regime="flat",
            kr_corp_spread_bps=200.0, kr_corp_regime="stress",
            kr_margin_change_20d=-25.0, kr_margin_signal="deleveraging",
            kr_tier_relative_perf=-6.0, kr_tier_signal="large_cap_risk_off",
            equity_bond_corr_120d=0.35, equity_bond_corr_regime="extreme_positive",
        ),
        9.0, 10.0, "risk_off",
    ),
    (
        "2017-Q3 Goldilocks calm",
        _case(
            vix=10.5, vix_z=-1.2, vix_pct=0.05, vix_change_4w=-1.0,
            vkospi=11.0, vkospi_change_4w=-0.5,
            ig_bps=95.0, ig_pct=0.20, ig_momentum_z=-0.5,
            hy_bps=320.0, hy_widening=False, hy_momentum_z=-0.3,
            fg_label="greed", fg_value=70,
            breadth_kr_adv=0.70, breadth_us_adv=0.68,
            pca_first_share=0.40, pca_concentrated=False,
            vix_term_ratio=1.20, vix_term_regime="contango",
            skew_value=125.0, skew_signal="normal",
            vxn=14.0, vxn_spread_vs_vix=3.5,
            tips_10y=0.5, real_yields_regime="neutral",
            funding_spread_bps=3.0, funding_regime="calm",
            credit_quality_spread_bps=70.0, credit_quality_regime="calm",
            kr_yc_spread_bps=70.0, kr_yc_inverted=False, kr_yc_regime="normal",
            kr_corp_spread_bps=50.0, kr_corp_regime="calm",
            kr_margin_change_20d=3.0, kr_margin_signal="normal",
            kr_tier_relative_perf=1.5, kr_tier_signal="neutral",
            equity_bond_corr_120d=-0.45, equity_bond_corr_regime="normal_hedge",
        ),
        0.0, 3.0, "risk_on",
    ),
    (
        "2018-12 Powell pivot / Q4 selloff",
        _case(
            vix=30.0, vix_z=2.3, vix_pct=0.92, vix_change_4w=12.0,
            vkospi=24.0, vkospi_change_4w=8.0,
            ig_bps=170.0, ig_pct=0.78, ig_momentum_z=1.8,
            hy_bps=540.0, hy_widening=True, hy_momentum_z=2.0,
            fg_label="fear", fg_value=20,
            breadth_kr_adv=0.30, breadth_us_adv=0.25,
            pca_first_share=0.65, pca_concentrated=True,
            vix_term_ratio=0.92, vix_term_regime="backwardation",
            skew_value=135.0, skew_signal="elevated",
            vxn=38.0, vxn_spread_vs_vix=8.0,
            tips_10y=1.0, real_yields_regime="neutral",
            funding_spread_bps=15.0, funding_regime="elevated",
            credit_quality_spread_bps=130.0, credit_quality_regime="elevated",
            kr_yc_spread_bps=20.0, kr_yc_inverted=False, kr_yc_regime="flat",
            kr_corp_spread_bps=100.0, kr_corp_regime="elevated",
            kr_margin_change_20d=-10.0, kr_margin_signal="normal",
            kr_tier_relative_perf=-3.5, kr_tier_signal="large_cap_risk_off",
            equity_bond_corr_120d=-0.2, equity_bond_corr_regime="weakening_hedge",
        ),
        6.0, 9.0, "risk_off",  # 2018-12 bear market entry — 9점도 합리적
    ),
    (
        "2022-06 peak inflation equity selloff",
        _case(
            vix=28.0, vix_z=2.0, vix_pct=0.88, vix_change_4w=6.0,
            vkospi=23.0, vkospi_change_4w=5.0,
            ig_bps=150.0, ig_pct=0.72, ig_momentum_z=1.5,
            hy_bps=500.0, hy_widening=True, hy_momentum_z=1.8,
            fg_label="extreme_fear", fg_value=15,
            breadth_kr_adv=0.30, breadth_us_adv=0.32,
            pca_first_share=0.70, pca_concentrated=True,
            vix_term_ratio=0.98, vix_term_regime="flat",
            skew_value=140.0, skew_signal="elevated",
            vxn=35.0, vxn_spread_vs_vix=7.0,
            tips_10y=0.6, real_yields_regime="neutral",
            funding_spread_bps=10.0, funding_regime="elevated",
            credit_quality_spread_bps=140.0, credit_quality_regime="elevated",
            kr_yc_spread_bps=15.0, kr_yc_inverted=False, kr_yc_regime="flat",
            kr_corp_spread_bps=110.0, kr_corp_regime="elevated",
            kr_margin_change_20d=-15.0, kr_margin_signal="deleveraging",
            kr_tier_relative_perf=-3.0, kr_tier_signal="large_cap_risk_off",
            equity_bond_corr_120d=0.40, equity_bond_corr_regime="extreme_positive",
        ),
        7.0, 9.0, "risk_off",
    ),
    (
        "2014-12 mild disinflation (calm)",
        _case(
            vix=16.0, vix_z=0.3, vix_pct=0.40, vix_change_4w=2.0,
            vkospi=15.0, vkospi_change_4w=1.0,
            ig_bps=130.0, ig_pct=0.55, ig_momentum_z=0.5,
            hy_bps=480.0, hy_widening=True, hy_momentum_z=0.8,
            fg_label="neutral", fg_value=50,
            breadth_kr_adv=0.50, breadth_us_adv=0.52,
            pca_first_share=0.45, pca_concentrated=False,
            vix_term_ratio=1.10, vix_term_regime="contango",
            skew_value=128.0, skew_signal="normal",
            vxn=18.0, vxn_spread_vs_vix=2.0,
            tips_10y=0.5, real_yields_regime="neutral",
            funding_spread_bps=5.0, funding_regime="calm",
            credit_quality_spread_bps=95.0, credit_quality_regime="calm",
            kr_yc_spread_bps=55.0, kr_yc_inverted=False, kr_yc_regime="normal",
            kr_corp_spread_bps=70.0, kr_corp_regime="calm",
            kr_margin_change_20d=-2.0, kr_margin_signal="normal",
            kr_tier_relative_perf=-1.0, kr_tier_signal="neutral",
            equity_bond_corr_120d=-0.40, equity_bond_corr_regime="normal_hedge",
        ),
        3.0, 5.0, "neutral",
    ),
    (
        "2024-06 AI rally with narrow breadth",
        _case(
            vix=13.0, vix_z=-0.5, vix_pct=0.20, vix_change_4w=-1.5,
            vkospi=15.0, vkospi_change_4w=0.0,
            ig_bps=88.0, ig_pct=0.15, ig_momentum_z=-0.2,
            hy_bps=290.0, hy_widening=False, hy_momentum_z=-0.5,
            fg_label="greed", fg_value=72,
            breadth_kr_adv=0.40, breadth_us_adv=0.35,
            pca_first_share=0.72, pca_concentrated=True,
            vix_term_ratio=1.18, vix_term_regime="contango",
            skew_value=145.0, skew_signal="extreme",
            vxn=20.0, vxn_spread_vs_vix=7.0,
            tips_10y=2.1, real_yields_regime="very_tight",
            funding_spread_bps=6.0, funding_regime="calm",
            credit_quality_spread_bps=75.0, credit_quality_regime="calm",
            kr_yc_spread_bps=45.0, kr_yc_inverted=False, kr_yc_regime="flat",
            kr_corp_spread_bps=65.0, kr_corp_regime="calm",
            kr_margin_change_20d=8.0, kr_margin_signal="normal",
            kr_tier_relative_perf=2.0, kr_tier_signal="neutral",
            equity_bond_corr_120d=0.15, equity_bond_corr_regime="positive_flip",
        ),
        4.0, 6.5, "neutral",
    ),
    (
        "2026-05 current (KR ETF context)",
        _case(
            vix=22.0, vix_z=1.3, vix_pct=0.72, vix_change_4w=4.0,
            vkospi=24.0, vkospi_change_4w=5.0,
            ig_bps=135.0, ig_pct=0.62, ig_momentum_z=0.8,
            hy_bps=420.0, hy_widening=True, hy_momentum_z=1.2,
            fg_label="fear", fg_value=28,
            breadth_kr_adv=0.32, breadth_us_adv=0.42,
            pca_first_share=0.62, pca_concentrated=True,
            vix_term_ratio=0.96, vix_term_regime="flat",
            skew_value=138.0, skew_signal="elevated",
            vxn=28.0, vxn_spread_vs_vix=6.0,
            tips_10y=1.6, real_yields_regime="tight",
            funding_spread_bps=14.0, funding_regime="elevated",
            credit_quality_spread_bps=125.0, credit_quality_regime="elevated",
            kr_yc_spread_bps=-15.0, kr_yc_inverted=True, kr_yc_regime="inverted",
            kr_corp_spread_bps=130.0, kr_corp_regime="elevated",
            kr_margin_change_20d=-18.0, kr_margin_signal="deleveraging",
            kr_tier_relative_perf=-4.0, kr_tier_signal="large_cap_risk_off",
            equity_bond_corr_120d=0.10, equity_bond_corr_regime="positive_flip",
        ),
        6.0, 8.5, "risk_off",
    ),
]


@pytest.mark.eval
@pytest.mark.parametrize(
    "case_name,inputs,score_min,score_max,expected_regime",
    HISTORICAL_CASES,
)
def test_systemic_score_accuracy(
    case_name, inputs, score_min, score_max, expected_regime,
):
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

    clf = SystemicScoreClassifier(quick, deep)
    result = clf.invoke(**inputs)

    assert score_min <= result.score <= score_max, (
        f"{case_name}: score {result.score} out of [{score_min}, {score_max}]. "
        f"drivers={result.drivers}"
    )
    assert result.regime == expected_regime, (
        f"{case_name}: got regime {result.regime}, expected {expected_regime}. "
        f"score={result.score}, drivers={result.drivers}"
    )
