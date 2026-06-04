import pytest
from datetime import date, datetime
from tradingagents.schemas.llm_overlay import (
    LLMBucketView, CredibilityState, LLMOverlayJournal,
    Stage2NarrativeView, Stage3CandidateBoostView,
)


def test_llm_bucket_view_8_buckets():
    v = LLMBucketView(
        kr_equity=0.5, global_equity=0.3, precious_metals=-0.2,
        cyclical_commodity_fx=0.0, kr_bond=-0.1, credit=-0.3,
        global_duration=0.2, cash_mmf=0.1,
        confidence=0.7, reasoning="growth strong", cited_events=["FOMC minutes hawkish"],
    )
    deltas = v.to_delta_dict()
    assert set(deltas.keys()) == {
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    }
    assert deltas["kr_equity"] == 0.5


def test_llm_bucket_view_delta_bounds():
    with pytest.raises(Exception):
        LLMBucketView(
            kr_equity=1.5, global_equity=0, precious_metals=0, cyclical_commodity_fx=0,
            kr_bond=0, credit=0, global_duration=0, cash_mmf=0,
            confidence=0.5, reasoning="", cited_events=[],
        )


def test_llm_bucket_view_confidence_bounds():
    with pytest.raises(Exception):
        LLMBucketView(
            kr_equity=0, global_equity=0, precious_metals=0, cyclical_commodity_fx=0,
            kr_bond=0, credit=0, global_duration=0, cash_mmf=0,
            confidence=1.5, reasoning="", cited_events=[],
        )


def test_credibility_state_default_prior():
    cs = CredibilityState(bucket_cred={}, history_count=0, last_updated=date(2026, 6, 1))
    assert cs.bucket_cred == {}
    assert cs.history_count == 0


def test_llm_overlay_journal_optional_realized():
    j = LLMOverlayJournal(
        timestamp=datetime(2026, 6, 1, 9, 0),
        quant_target={"kr_equity": 0.15}, llm_views=[],
        novelty=0.3, consensus={"kr_equity": 0.8},
        credibility_snapshot={"kr_equity": 0.3},
        final_target={"kr_equity": 0.16}, audit={"kr_equity": {"w_LLM": 0.072}},
    )
    assert j.realized_returns is None


def test_stage2_narrative_view_contract():
    v = Stage2NarrativeView(
        base_scenario="goldilocks",
        overlays=["policy_surprise", "valuation_extreme"],
        bucket_deltas={
            "kr_equity": 0.3,
            "global_equity": 0.2,
            "precious_metals": -0.1,
            "cyclical_commodity_fx": 0.0,
            "kr_bond": -0.2,
            "credit": 0.0,
            "global_duration": -0.1,
            "cash_mmf": 0.1,
        },
        risk_budget_delta=0.2,
        confidence=0.65,
        evidence=["FOMC tone softened", "AI breadth narrowing"],
        expiry_days=3,
        conflict_with_quant=False,
        reasoning="Narrative supports mild risk-on but concentration limits apply.",
    )
    assert v.bucket_deltas["kr_equity"] == 0.3
    assert v.expiry_days == 3


def test_stage2_narrative_view_rejects_unknown_bucket():
    with pytest.raises(Exception):
        Stage2NarrativeView(
            base_scenario="goldilocks",
            overlays=[],
            bucket_deltas={"unknown_bucket": 1.0},
            risk_budget_delta=0.0,
            confidence=0.5,
            evidence=[],
            expiry_days=1,
            conflict_with_quant=False,
            reasoning="bad bucket",
        )


def test_stage3_candidate_boost_filters_to_allowed_tickers():
    v = Stage3CandidateBoostView(
        ticker_boosts={"A069500": 0.5, "A999999": 1.0},
        subcategory_boosts={"semiconductor": 0.4},
        confidence=0.55,
        evidence=["semiconductor export surprise"],
        reasoning="Prefer semis among the candidate longlist.",
    )
    assert v.filtered_ticker_boosts({"A069500"}) == {"A069500": 0.5}


def test_stage3_candidate_boost_rejects_out_of_range_boost():
    with pytest.raises(Exception):
        Stage3CandidateBoostView(
            ticker_boosts={"A069500": 1.2},
            subcategory_boosts={},
            confidence=0.5,
            evidence=[],
            reasoning="too strong",
        )
