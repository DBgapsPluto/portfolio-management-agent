"""Tier 1 Task 7+8 — VALID_SUB_CATEGORIES 8-bucket + bucket_for_etf tests."""
import pytest
from tradingagents.skills.portfolio.sub_category import (
    VALID_SUB_CATEGORIES, bucket_for_etf, bucket_for_category,
)


def test_valid_sub_categories_8_buckets():
    expected = {
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    }
    assert set(VALID_SUB_CATEGORIES.keys()) == expected


def test_precious_metals_categories():
    assert "gold" in VALID_SUB_CATEGORIES["precious_metals"]
    assert "silver_precious" in VALID_SUB_CATEGORIES["precious_metals"]


def test_cyclical_commodity_categories():
    cc = VALID_SUB_CATEGORIES["cyclical_commodity_fx"]
    assert "oil_energy" in cc
    assert "broad_commodity" in cc
    assert "usd_fx" in cc


def test_bond_split():
    assert "kr_treasury" in VALID_SUB_CATEGORIES["kr_bond"]
    assert "us_high_yield" in VALID_SUB_CATEGORIES["credit"]
    assert "us_treasury" in VALID_SUB_CATEGORIES["global_duration"]


def test_bucket_for_etf_uses_sub_category():
    class ETF:
        def __init__(self, cat, sub):
            self.category = cat
            self.sub_category = sub

    # KR equity straightforward
    assert bucket_for_etf(ETF("국내주식_지수", "index_broad")) == "kr_equity"

    # FX 및 원자재 — split by sub_category
    assert bucket_for_etf(ETF("FX 및 원자재", "gold")) == "precious_metals"
    assert bucket_for_etf(ETF("FX 및 원자재", "oil_energy")) == "cyclical_commodity_fx"

    # 국내채권 — split (kr_treasury → kr_bond, kr_corporate → credit)
    assert bucket_for_etf(ETF("국내채권_종합", "kr_treasury")) == "kr_bond"
    assert bucket_for_etf(ETF("국내채권_종합", "kr_corporate")) == "credit"

    # 해외채권_회사채 → credit directly
    assert bucket_for_etf(ETF("해외채권_회사채", "us_high_yield")) == "credit"

    # 금리연계형 → cash_mmf
    assert bucket_for_etf(ETF("금리연계형/초단기채권", "mmf_kr")) == "cash_mmf"

    # Unknown sub_category → None
    assert bucket_for_etf(ETF("FX 및 원자재", "unknown_label")) is None

    # Unknown category → None
    assert bucket_for_etf(ETF("unknown_category", "gold")) is None


def test_bucket_for_category_backward_compat():
    """Legacy direct lookups still work for non-ambiguous categories."""
    assert bucket_for_category("국내주식_지수") == "kr_equity"
    assert bucket_for_category("국내채권_회사채") == "credit"
    # Ambiguous category → None
    assert bucket_for_category("FX 및 원자재") is None
    assert bucket_for_category("국내채권_종합") is None
