"""research_manager 의 factor model pipeline e2e."""
from unittest.mock import MagicMock

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.schemas.research import ResearchDecision


def _full_state():
    s = {}
    s["macro_summary"] = "test"
    s["risk_summary"] = "test"
    s["technical_summary"] = "test"
    s["news_summary"] = "test"

    s["macro_report"] = MagicMock()
    s["macro_report"].growth.gdp_nowcast = 2.0
    s["macro_report"].growth.cfnai = 0.0
    s["macro_report"].growth.nfci = 0.0
    s["macro_report"].employment.sahm_trigger = False
    s["macro_report"].yield_curve.slope_2_10y_bps = 80
    s["macro_report"].yield_curve.slope_5_30y_bps = 120
    s["macro_report"].cpi.yoy_pct = 2.5
    s["macro_report"].cpi.three_month_annualized_pct = 2.5
    s["macro_report"].cpi.core_pce_yoy = 2.0
    s["macro_report"].inflation_exp.five_y_five_y_pct = 2.3
    s["macro_report"].inflation_exp.michigan_1y_pct = 3.0
    s["macro_report"].real_yields.ten_y_pct = 0.5
    s["macro_report"].fed_path.implied_change_6m_bps = 0
    s["macro_report"].kr_macro.bok_us_rate_diff_bps = -100
    s["macro_report"].kr_macro.exports_yoy_pct = 5.0
    s["macro_report"].foreign_flow.net_flow_z = 0.0

    s["risk_report"] = MagicMock()
    s["risk_report"].credit_spread_us_hy.current_bps = 400
    s["risk_report"].credit_spread_us_hy.momentum_z = 0.0
    s["risk_report"].credit_quality.quality_spread_bps = 90
    s["risk_report"].funding_stress.spread_bps = 10
    s["risk_report"].vix.current_value = 20.0
    s["risk_report"].vix.z_score = 0.0
    s["risk_report"].vix.term_ratio = 1.0
    s["risk_report"].move.current_value = 90
    s["risk_report"].realized_vol.sixty_d = 0.012
    s["risk_report"].equity_bond_corr.correlation_60d = -0.2
    s["risk_report"].skew.change_1m = 0.0

    s["technical_report"] = MagicMock()
    s["technical_report"].sector_dispersion = 1.0
    s["technical_report"].breadth = 0.55
    s["technical_report"].kospi_pbr = 1.0

    s["news_report"] = MagicMock()
    s["news_report"].release_surprise.surprise_index_30d = 0.0
    s["news_report"].release_surprise.bias_30d = "balanced"
    s["news_report"].release_surprise.high_importance_today = 1
    s["news_report"].news_sentiment.avg_sentiment = {"macro": 0.0, "corporate": 0.0}
    s["news_report"].news_sentiment.count_change_vs_7d = {"corporate": 0, "geopolitical": 0}
    s["news_report"].news_sentiment.sentiment_dispersion = 0.3
    s["news_report"].news_sentiment.rising_category = None
    s["news_report"].global_overnight.risk_regime_overnight = "mixed"
    s["news_report"].global_overnight.krw.change_pct = 0.0
    s["news_report"].cb_speakers.fed_voting_balance = 0.0
    s["news_report"].cb_speakers.fed_tone_balance = 0.0
    s["news_report"].cb_speakers.bok_tone_balance = 0.0

    return s


def test_research_manager_returns_research_decision():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    assert "research_decision" in result
    assert "bucket_target" in result
    assert "research_debate_summary" in result
    assert isinstance(result["research_decision"], ResearchDecision)


def test_research_decision_has_factor_scores():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    rd = result["research_decision"]
    assert len(rd.factor_scores) == 9
    assert "F1_growth" in rd.factor_scores


def test_bucket_target_mandate_safe():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    bt = result["bucket_target"]
    risk = bt.kr_equity + bt.global_equity + bt.fx_commodity
    assert risk <= 0.70 + 1e-6
    assert abs(bt.kr_equity + bt.global_equity + bt.fx_commodity + bt.bond + bt.cash_mmf - 1.0) < 1e-6


def test_research_decision_has_safety_diagnostics():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    rd = result["research_decision"]
    assert "pre_projection_risk_asset" in rd.safety_diagnostics
    assert "projection_l2_distance" in rd.safety_diagnostics


def test_research_decision_has_factor_contributions():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    rd = result["research_decision"]
    assert len(rd.factor_contributions) == 9
    assert "kr_equity" in rd.factor_contributions["F1_growth"]


def test_research_decision_has_baseline_bucket():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    rd = result["research_decision"]
    assert "kr_equity" in rd.baseline_bucket


def test_research_decision_dominant_scenario_set():
    """legacy compat — dominant_scenario string 이 항상 valid."""
    VALID_SCENARIOS = {
        "global_credit", "kr_stress", "kr_boom",
        "overheating", "goldilocks", "stagflation", "broad_recession",
    }
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    rd = result["research_decision"]
    assert rd.dominant_scenario in VALID_SCENARIOS


def test_research_decision_conviction_set():
    VALID_CONVICTIONS = {"high", "medium", "low"}
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    rd = result["research_decision"]
    assert rd.conviction in VALID_CONVICTIONS
