"""Regression tests for Tier 1: AUM filter removal from candidate_selector."""
import inspect
from datetime import date

from tradingagents.dataflows.universe import ETFEntry, Universe
from tradingagents.schemas.llm_overlay import Stage3CandidateBoostView
from tradingagents.skills.portfolio.candidate_selector import (
    _eligible_for_bucket, apply_llm_candidate_boost,
)


def _make_universe(etfs):
    return Universe(version="t", etfs=etfs)


def test_aum_filter_removed_small_etfs_pass():
    """After Tier 1: small AUM ETFs are eligible (no filter)."""
    universe = _make_universe([
        ETFEntry(ticker="A100001", name="BIG", aum_krw=1_000_000_000_000,
                 underlying_index="u1", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A100002", name="SMALL", aum_krw=50_000_000_000,
                 underlying_index="u2", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A100003", name="TINY", aum_krw=10_000_000_000,
                 underlying_index="u3", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A100004", name="MICRO", aum_krw=1_000_000_000,
                 underlying_index="u4", bucket="위험", category="국내주식_지수"),
    ])

    # Tier 1 contract: _eligible_for_bucket takes an 8-bucket NAME (not a category).
    # 국내주식_지수 category → kr_equity bucket via bucket_for_etf.
    eligible = _eligible_for_bucket(universe, "kr_equity")
    assert len(eligible) == 4  # all 4 pass (no AUM filter)
    tickers = [e.ticker for e in eligible]
    assert "A100003" in tickers and "A100004" in tickers  # TINY and MICRO pass


def test_eligible_for_bucket_signature_no_min_aum_param():
    """Verify _eligible_for_bucket no longer accepts min_aum_krw param."""
    sig = inspect.signature(_eligible_for_bucket)
    assert "min_aum_krw" not in sig.parameters


def test_eligible_for_bucket_category_mismatch_excluded():
    """ETFs that classify into a different bucket are excluded."""
    universe = _make_universe([
        ETFEntry(ticker="A111111", name="A", aum_krw=1_000_000_000_000,
                 underlying_index="u1", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A222222", name="B", aum_krw=1_000_000_000_000,
                 underlying_index="u2", bucket="안전", category="해외주식_지수"),
    ])
    # kr_equity bucket: only the 국내주식_지수 ETF; 해외주식_지수 → global_equity.
    eligible = _eligible_for_bucket(universe, "kr_equity")
    tickers = [e.ticker for e in eligible]
    assert tickers == ["A111111"]
    assert "A222222" not in tickers


def test_eligible_for_bucket_empty_universe():
    """Empty universe returns empty list."""
    universe = _make_universe([])
    assert _eligible_for_bucket(universe, "kr_equity") == []


def test_apply_llm_candidate_boost_is_bounded():
    view = Stage3CandidateBoostView(
        ticker_boosts={"A1": 1.0},
        subcategory_boosts={"semiconductor": 1.0},
        confidence=1.0,
        evidence=["semiconductor narrative"],
        reasoning="test",
    )
    scores, audit = apply_llm_candidate_boost(
        alpha_scores={"A1": 0.20, "A2": 0.20},
        ticker_to_sub_category={"A1": "semiconductor", "A2": "consumer"},
        llm_candidate_view=view,
        allowed_tickers={"A1", "A2"},
        boost_cap=0.08,
    )
    assert scores["A1"] <= 0.28 + 1e-9
    assert scores["A2"] == 0.20
    assert audit["A1"]["clipped_boost"] <= 0.08 + 1e-9


def test_apply_llm_candidate_boost_ignores_unsupported_ticker():
    view = Stage3CandidateBoostView(
        ticker_boosts={"A999": 1.0},
        subcategory_boosts={},
        confidence=1.0,
        evidence=[],
        reasoning="test",
    )
    scores, audit = apply_llm_candidate_boost(
        alpha_scores={"A1": 0.20},
        ticker_to_sub_category={"A1": "semiconductor"},
        llm_candidate_view=view,
        allowed_tickers={"A1"},
        boost_cap=0.08,
    )
    assert scores == {"A1": 0.20}
    assert audit == {}


def test_apply_llm_candidate_boost_does_not_flip_negative_alpha_positive():
    view = Stage3CandidateBoostView(
        ticker_boosts={"A1": 1.0},
        subcategory_boosts={},
        confidence=1.0,
        evidence=["narrative"],
        reasoning="test",
    )
    scores, audit = apply_llm_candidate_boost(
        alpha_scores={"A1": -0.01},
        ticker_to_sub_category={"A1": "semiconductor"},
        llm_candidate_view=view,
        allowed_tickers={"A1"},
        boost_cap=0.08,
    )
    assert scores["A1"] <= 0.0
    assert audit["A1"]["crossed_positive_alpha"] is True
