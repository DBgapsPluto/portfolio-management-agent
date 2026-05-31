import pytest
from datetime import date, datetime
from tradingagents.schemas.llm_overlay import (
    LLMBucketView, CredibilityState, LLMOverlayJournal,
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
