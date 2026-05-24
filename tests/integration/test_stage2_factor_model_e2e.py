"""Stage 2 factor model — full pipeline e2e with mock state."""
from unittest.mock import MagicMock

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.skills.research.factor_to_bucket import INITIAL_BASELINE


def _mock_state_2026_05_15_like():
    """2026-05-15 같은 macro 환경 시뮬레이션 (B regime — overheating).

    Real 2026-05-15 archived state 가 macro_quant 의 cycle B 0.84 였음.

    2026-05-23 (C1, PR0 hotfix): mock path 를 실제 schema 와 매칭.
    - macro_report.growth.gdp_nowcast → macro_report.gdp_nowcast.nowcast_pct
    - macro_report.growth.nfci → macro_report.financial_conditions.nfci
    - macro_report.employment.sahm_trigger → .sahm_rule_triggered
    - macro_report.yield_curve.slope_2_10y_bps → .spread_10y_2y_bps
    - macro_report.cpi.* → macro_report.inflation.*
    - macro_report.inflation_exp.* → macro_report.inflation_expectations.*
    - macro_report.real_yields → risk_report.real_yields.tips_10y
    - macro_report.fed_path.implied_change_6m_bps → .path_bps
    - macro_report.kr_macro → macro_report.kr_divergence / kr_export
    - macro_report.foreign_flow.net_flow_z → .net_20d_krw
    - risk_report.vix.z_score → .zscore_30d
    - risk_report.vix.term_ratio → risk_report.vix_term.ratio
    - risk_report.move.current_value → macro_report.tail_risk.move
    - risk_report.credit_spread_us_hy.momentum_z → .momentum_zscore
    - technical_report.breadth → risk_report.breadth_kr.advancing_pct
    - 5 C8 placeholder (cfnai, slope_5_30y, realized_vol, kospi_pbr, sector_dispersion,
      skew_change) 은 weight=0 이라 read 되지 않음.
    """
    s = {}
    s["macro_summary"] = "B-cycle dominant"
    s["risk_summary"] = "neutral"
    s["technical_summary"] = "rising"
    s["news_summary"] = "macro acceleration"

    s["macro_report"] = MagicMock()
    s["macro_report"].gdp_nowcast.nowcast_pct = 4.0  # +z growth
    s["macro_report"].financial_conditions.nfci = -0.5  # easy = +growth
    s["macro_report"].employment.sahm_rule_triggered = False
    s["macro_report"].yield_curve.spread_10y_2y_bps = 50
    s["macro_report"].inflation.cpi_yoy = 3.9  # +inflation
    s["macro_report"].inflation.momentum_3mo = 7.3
    s["macro_report"].inflation.core_pce_yoy = 3.5
    s["macro_report"].inflation_expectations.breakeven_5y5y = 2.5
    s["macro_report"].inflation_expectations.michigan_1y = 3.8
    s["macro_report"].fed_path.path_bps = 25
    s["macro_report"].kr_divergence.us_kr_rate_gap_bps = -150
    s["macro_report"].kr_export.yoy_pct = 50.2
    s["macro_report"].foreign_flow.net_20d_krw = -1.5e12  # 외국인 순매도 (KRW)
    s["macro_report"].fx.usd_krw = 1350.0  # weak KRW (vs baseline ~1250)
    s["macro_report"].tail_risk.move = 100  # MOVE in macro_report.tail_risk

    s["risk_report"] = MagicMock()
    s["risk_report"].credit_spread_us_hy.current_bps = 280
    s["risk_report"].credit_spread_us_hy.momentum_zscore = -0.04
    s["risk_report"].credit_quality.quality_spread_bps = 60
    s["risk_report"].funding_stress.spread_bps = -4
    s["risk_report"].vix.current_value = 18.4
    s["risk_report"].vix.zscore_30d = -0.15
    s["risk_report"].vix_term.ratio = 1.21
    s["risk_report"].equity_bond_corr.correlation_60d = 0.20
    s["risk_report"].real_yields.tips_10y = 1.5  # real_yields moved here
    s["risk_report"].breadth_kr.advancing_pct = 0.50

    s["technical_report"] = MagicMock()
    # sector_dispersion / breadth / kospi_pbr — C8 placeholder, weight=0

    s["news_report"] = MagicMock()
    s["news_report"].release_surprise.surprise_index_30d = +0.8
    s["news_report"].release_surprise.bias_30d = "hawkish_surprise"
    s["news_report"].release_surprise.high_importance_today = 2
    s["news_report"].news_sentiment.avg_sentiment = {"macro": +0.3, "corporate": +0.2}
    s["news_report"].news_sentiment.count_change_vs_7d = {"corporate": +1, "geopolitical": 0}
    s["news_report"].news_sentiment.sentiment_dispersion = 0.4
    s["news_report"].news_sentiment.rising_category = None
    s["news_report"].global_overnight.risk_regime_overnight = "mixed"
    s["news_report"].global_overnight.krw.change_pct = +1.2
    s["news_report"].cb_speakers.fed_voting_balance = +0.3
    s["news_report"].cb_speakers.fed_tone_balance = +0.2
    s["news_report"].cb_speakers.bok_tone_balance = -0.1

    return s


def test_2026_05_15_like_state_produces_overheating_or_similar():
    """B regime macro 환경 → overheating 또는 유사 scenario expected."""
    node = create_research_manager(deep_llm=None)
    result = node(_mock_state_2026_05_15_like())
    rd = result["research_decision"]
    # Acceptance: F1 + F2 가 모두 positive 일 가능성 큰 환경
    # Sign convention: F1>0 growth, F2>0 inflation
    f1 = rd.factor_scores["F1_growth"]
    f2 = rd.factor_scores["F2_inflation"]
    # 강한 hawkish + GDP 4 → 둘 다 positive 예상
    assert f1 > 0 or f2 > 0, f"Expected growth or inflation positive, got F1={f1}, F2={f2}"


def test_2026_05_15_like_mandate_safe():
    node = create_research_manager(deep_llm=None)
    result = node(_mock_state_2026_05_15_like())
    bt = result["bucket_target"]
    risk = bt.kr_equity + bt.global_equity + bt.fx_commodity
    assert risk <= 0.70 + 1e-6
    assert abs(bt.kr_equity + bt.global_equity + bt.fx_commodity + bt.bond + bt.cash_mmf - 1.0) < 1e-6


def test_2026_05_15_like_full_factor_attribution():
    """Attribution audit trail check."""
    node = create_research_manager(deep_llm=None)
    result = node(_mock_state_2026_05_15_like())
    rd = result["research_decision"]
    # 9 factor 모두 contributions
    assert len(rd.factor_contributions) == 9
    # baseline 가 INITIAL_BASELINE
    assert rd.baseline_bucket["bond"] == INITIAL_BASELINE["bond"]
