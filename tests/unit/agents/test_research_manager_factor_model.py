"""research_manager 의 factor model pipeline e2e."""
from unittest.mock import MagicMock

import pytest

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
    s["risk_report"].equity_bond_corr.correlation_120d = -0.2
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
    # 2026-05-27 — F10 추가. fixture 에 systemic_liquidity components 있으면 10,
    # 없으면 9 (graceful skip). 9 이상 보장.
    assert len(rd.factor_scores) >= 9
    assert "F1_growth" in rd.factor_scores


def test_bucket_target_mandate_safe():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    bt = result["bucket_target"]
    risk = bt.risk_asset_weight
    assert risk <= 0.70 + 1e-6
    assert abs(bt.total - 1.0) < 1e-6


def test_research_decision_has_safety_diagnostics():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    rd = result["research_decision"]
    assert "pre_projection_risk_asset" in rd.safety_diagnostics
    assert "projection_l2_distance" in rd.safety_diagnostics


def test_safety_diagnostics_includes_extreme_components():
    """2026-05-26 #3 fix: component-level outlier signal (|z| ≥ 3) 추출."""
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    rd = result["research_decision"]
    # field 존재 확인 (list — 비어있을 수 있음, fixture 의 z 값에 따라)
    assert "extreme_components" in rd.safety_diagnostics
    assert isinstance(rd.safety_diagnostics["extreme_components"], list)


def test_research_decision_has_factor_contributions():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    rd = result["research_decision"]
    assert len(rd.factor_contributions) >= 9
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
        "late_cycle",  # 2026-05-26 #5 fix
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


# ---- 2026-05-26 #5 fix: late_cycle scenario cell ----


def test_late_cycle_scenario_classified():
    """F1>0 + F2≥0.4 + F5≤-0.2 + (cycle threshold 못 넘김) → late_cycle."""
    from tradingagents.agents.managers.research_manager import _strict_classify_scenario
    # F1=0.3 (cycle 0.5 미만 — overheating 진입 못 함),
    # F2=0.5 (인플레 잔존), F5=-0.4 (신용 약세),
    # F6=0, F7=0 (KR/vol 정상)
    scenario = _strict_classify_scenario(
        f1=0.3, f2=0.5, f5=-0.4, f6=0.0, f7=0.0,
    )
    assert scenario == "late_cycle"


def test_late_cycle_not_triggered_when_credit_strong():
    """F5 양수 (신용 정상) 이면 late_cycle 진입 안 함 → goldilocks."""
    from tradingagents.agents.managers.research_manager import _strict_classify_scenario
    scenario = _strict_classify_scenario(
        f1=0.3, f2=0.5, f5=0.2,  # credit 양수
        f6=0.0, f7=0.0,
    )
    assert scenario == "goldilocks"


def test_late_cycle_priority_below_stagflation():
    """SCENARIO_PRIORITY 에서 late_cycle 이 stagflation 보다 less urgent."""
    from tradingagents.agents.managers.research_manager import SCENARIO_PRIORITY
    assert SCENARIO_PRIORITY["late_cycle"] > SCENARIO_PRIORITY["stagflation"]
    assert SCENARIO_PRIORITY["late_cycle"] > SCENARIO_PRIORITY["overheating"]
    assert SCENARIO_PRIORITY["late_cycle"] < SCENARIO_PRIORITY["goldilocks"]


def test_late_cycle_method_picker_returns_risk_parity():
    """late_cycle scenario 에서 method_picker 가 risk_parity 선택."""
    from tradingagents.skills.portfolio.method_picker import _SCENARIO_METHOD
    from tradingagents.schemas.portfolio import OptimizationMethod
    assert "late_cycle" in _SCENARIO_METHOD
    method, _ = _SCENARIO_METHOD["late_cycle"]
    assert method == OptimizationMethod.RISK_PARITY


def test_late_cycle_sub_category_boost_axes():
    """late_cycle → B cycle (growth+inflation) — inflation_hedge boost."""
    from tradingagents.skills.portfolio.sub_category import _scenario_to_axes
    axes = _scenario_to_axes("late_cycle")
    assert axes == ("B", "N", "F")


# ---- 2026-05-26 #8 fix: regime confidence → bucket sizing mapping ----


def test_confidence_high_amplifies_risk():
    """confidence ≥ 0.8 → 위험자산 ×1.05."""
    from tradingagents.agents.managers.research_manager import _apply_confidence_to_bucket
    bucket = {
        "kr_equity": 0.10, "global_equity": 0.10, "fx_commodity": 0.10,
        "bond": 0.40, "cash_mmf": 0.30,
    }
    new_bucket, mult = _apply_confidence_to_bucket(bucket, confidence=0.89)
    assert mult == 1.05
    new_risk = new_bucket["kr_equity"] + new_bucket["global_equity"] + new_bucket["fx_commodity"]
    # 0.30 × 1.05 = 0.315
    assert new_risk == pytest.approx(0.315, abs=1e-6)
    # Sum 보존 (1.0)
    assert sum(new_bucket.values()) == pytest.approx(1.0, abs=1e-6)


def test_confidence_low_reduces_risk():
    """confidence < 0.5 → 위험자산 ×0.92."""
    from tradingagents.agents.managers.research_manager import _apply_confidence_to_bucket
    bucket = {
        "kr_equity": 0.10, "global_equity": 0.10, "fx_commodity": 0.10,
        "bond": 0.40, "cash_mmf": 0.30,
    }
    new_bucket, mult = _apply_confidence_to_bucket(bucket, confidence=0.3)
    assert mult == 0.92
    new_risk = new_bucket["kr_equity"] + new_bucket["global_equity"] + new_bucket["fx_commodity"]
    assert new_risk == pytest.approx(0.30 * 0.92, abs=1e-6)
    assert sum(new_bucket.values()) == pytest.approx(1.0, abs=1e-6)


def test_confidence_neutral_no_change():
    """0.5 ≤ confidence < 0.8 → multiplier 1.0 (변화 없음)."""
    from tradingagents.agents.managers.research_manager import _apply_confidence_to_bucket
    bucket = {
        "kr_equity": 0.20, "global_equity": 0.10, "fx_commodity": 0.10,
        "bond": 0.40, "cash_mmf": 0.20,
    }
    new_bucket, mult = _apply_confidence_to_bucket(bucket, confidence=0.65)
    assert mult == 1.0
    assert new_bucket == bucket


def test_confidence_high_respects_mandate_cap():
    """mandate cap 70% 초과는 자동 cap."""
    from tradingagents.agents.managers.research_manager import _apply_confidence_to_bucket
    bucket = {
        "kr_equity": 0.30, "global_equity": 0.20, "fx_commodity": 0.20,  # risk 0.70
        "bond": 0.20, "cash_mmf": 0.10,
    }
    new_bucket, _ = _apply_confidence_to_bucket(bucket, confidence=0.95)
    new_risk = new_bucket["kr_equity"] + new_bucket["global_equity"] + new_bucket["fx_commodity"]
    # 0.70 × 1.05 = 0.735 → cap 0.70.
    assert new_risk == pytest.approx(0.70, abs=1e-6)
