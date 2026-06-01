"""Critical 2 — factor_estimators mode='historical' flag.

Backward-compat 보장:
- mode='production' (default) → PR1 의 100% identical behavior
- mode='historical' → news weight 0 + quant weight renormalize
"""
from copy import deepcopy

import pytest

from tradingagents.skills.research.factor_estimators import (
    compute_all_factors, NEWS_DERIVED_COMPONENTS,
)
from tradingagents.backtest.historical.stage1_builder import (
    _build_baseline_macro_report,
    _build_baseline_risk_report,
    _build_baseline_technical_report,
    _build_baseline_news_report,
)


def _build_baseline_state() -> dict:
    return {
        "macro_report": _build_baseline_macro_report(),
        "risk_report": _build_baseline_risk_report(),
        "technical_report": _build_baseline_technical_report(),
        "news_report": _build_baseline_news_report(),
    }


def test_production_mode_default_matches_explicit() -> None:
    """default mode = explicit 'production' — backward-compat 보장."""
    state = _build_baseline_state()
    no_arg = compute_all_factors(state)  # PR1 의 기존 호출
    explicit = compute_all_factors(state, mode="production")
    for f in ("growth_surprise", "inflation_surprise", "real_rate",
              "term_premium", "credit_cycle", "krw_regime",
              "equity_vol_regime", "valuation", "market_dispersion"):
        sa = getattr(no_arg, f)
        sb = getattr(explicit, f)
        assert sa.z_score == pytest.approx(sb.z_score, abs=1e-12), f
        assert sa.confidence == pytest.approx(sb.confidence, abs=1e-12), f


def test_historical_mode_drops_news_components() -> None:
    """historical mode 의 factor z 는 news-derived component 영향 받지 않음.

    Tier 0 (2026-05-28): geopolitical_surge 는 NEWS_DERIVED_COMPONENTS 에서
    제거됨 (GPR Index 로 대체 예정, quant). 따라서 geopolitical count_change_vs_7d
    perturbation 은 이 테스트에서 제외 — 해당 component 는 이제 historical mode
    에서도 살아남음 (quant component 로 분류).
    """
    state_base = _build_baseline_state()
    state_perturbed = deepcopy(state_base)

    # Perturb only true news-derived fields (NEWS_DERIVED_COMPONENTS 소속).
    state_perturbed["news_report"].news_sentiment.sentiment_dispersion = 1.5
    # NOTE: geopolitical count_change_vs_7d 는 Tier 0 이후 quant component →
    # historical mode 에서 살아남으므로 여기서 perturb 하지 않음.
    # surprise_index_30d
    state_perturbed["news_report"].release_surprise.surprise_index_30d = 2.5
    # cb_speakers
    state_perturbed["news_report"].cb_speakers.fed_tone_balance = 0.8

    # historical mode: identical despite news perturbation
    h_base = compute_all_factors(state_base, mode="historical")
    h_pert = compute_all_factors(state_perturbed, mode="historical")
    for f in ("growth_surprise", "inflation_surprise", "real_rate",
              "term_premium", "credit_cycle", "krw_regime",
              "equity_vol_regime", "valuation", "market_dispersion"):
        sa = getattr(h_base, f).z_score
        sb = getattr(h_pert, f).z_score
        assert sa == pytest.approx(sb, abs=1e-12), (
            f"{f} should be unchanged in historical mode but {sa} != {sb}"
        )

    # production mode: at least one factor should differ (news has weight)
    p_base = compute_all_factors(state_base, mode="production")
    p_pert = compute_all_factors(state_perturbed, mode="production")
    diff_found = any(
        abs(getattr(p_base, f).z_score - getattr(p_pert, f).z_score) > 1e-6
        for f in ("growth_surprise", "inflation_surprise", "equity_vol_regime",
                  "term_premium", "credit_cycle", "market_dispersion")
    )
    assert diff_found, "production mode should reflect news perturbation"


def test_historical_mode_confidence_in_valid_range() -> None:
    """historical mode 의 confidence 는 quant-only weight sum, (0, 1] 범위."""
    state = _build_baseline_state()
    hist = compute_all_factors(state, mode="historical")
    for f in ("growth_surprise", "inflation_surprise", "real_rate",
              "term_premium", "credit_cycle", "krw_regime",
              "equity_vol_regime", "valuation", "market_dispersion"):
        score = getattr(hist, f)
        # F8 valuation has 0 news components — confidence should be unchanged.
        # Other factors should have confidence ≤ production (news weights removed).
        assert 0 < score.confidence <= 1.0 + 1e-9, (
            f"{f} confidence {score.confidence} out of (0, 1]"
        )


def test_news_derived_components_constant_includes_expected_keys() -> None:
    """NEWS_DERIVED_COMPONENTS contains the keys used by compute_F*.
    Tier 0 (2026-05-28): geopolitical_surge removed — GPR Index is quant now.
    """
    # Sanity — well-known news component keys must be in the set.
    must_have = {
        "release_surprise", "hawkish_bias", "macro_sent", "risk_regime_overnight",
        "release_hawkish", "fed_voting_balance", "fed_tone_balance",
        "corporate_distress", "dovish_bias",
        "krw_overnight_pct", "bok_tone_balance",
        "sentiment_dispersion",
        "event_cluster", "rising_signal",
    }
    assert must_have.issubset(NEWS_DERIVED_COMPONENTS)
    # geopolitical_surge is now quant (GPR Index) — must NOT be in news set
    assert "geopolitical_surge" not in NEWS_DERIVED_COMPONENTS
