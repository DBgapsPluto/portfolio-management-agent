"""Phase B — sub_category enrichment helper tests."""
from unittest.mock import MagicMock

from tradingagents.skills.portfolio.sub_category import (
    VALID_SUB_CATEGORIES, bucket_for_category, classify_batch_via_llm,
    is_valid_subcategory,
)


def test_bucket_for_category_known():
    assert bucket_for_category("국내주식_지수") == "kr_equity"
    assert bucket_for_category("해외주식_섹터") == "global_equity"
    assert bucket_for_category("FX 및 원자재") == "fx_commodity"
    assert bucket_for_category("국내채권_종합") == "bond"
    assert bucket_for_category("금리연계형/초단기채권") == "cash_mmf"


def test_bucket_for_category_unknown_returns_none():
    assert bucket_for_category("unknown_category") is None


def test_is_valid_subcategory():
    assert is_valid_subcategory("kr_equity", "semiconductor")
    assert is_valid_subcategory("global_equity", "us_tech_nasdaq")
    assert is_valid_subcategory("fx_commodity", "gold")
    assert is_valid_subcategory("bond", "kr_treasury")
    assert not is_valid_subcategory("kr_equity", "gold")  # gold는 fx_commodity
    assert not is_valid_subcategory("bond", "semiconductor")


def test_classify_batch_via_llm_parses_response():
    items = [
        {"ticker": "A069500", "name": "KODEX 200", "underlying_index": "KOSPI 200",
         "bucket": "kr_equity"},
        {"ticker": "A114800", "name": "KODEX 반도체", "underlying_index": "KRX 반도체",
         "bucket": "kr_equity"},
    ]
    fake_llm = MagicMock()
    fake_llm.invoke.return_value.content = (
        '[{"idx":0,"sub_category":"index_broad"},'
        ' {"idx":1,"sub_category":"semiconductor"}]'
    )
    result = classify_batch_via_llm(items, fake_llm)
    assert result["A069500"] == "index_broad"
    assert result["A114800"] == "semiconductor"


def test_classify_batch_invalid_label_falls_back():
    items = [
        {"ticker": "A001", "name": "T", "underlying_index": "x", "bucket": "kr_equity"},
    ]
    fake_llm = MagicMock()
    fake_llm.invoke.return_value.content = (
        '[{"idx":0,"sub_category":"made_up_label"}]'
    )
    result = classify_batch_via_llm(items, fake_llm)
    # invalid → "thematic_other" (kr_equity에 존재)
    assert result["A001"] == "thematic_other"


def test_classify_batch_llm_failure_returns_partial():
    items = [
        {"ticker": "A001", "name": "T", "underlying_index": "x", "bucket": "kr_equity"},
    ]
    fake_llm = MagicMock()
    fake_llm.invoke.side_effect = RuntimeError("api down")
    result = classify_batch_via_llm(items, fake_llm)
    assert result == {}


def test_classify_batch_splits_into_batches():
    items = [
        {"ticker": f"A{str(i).zfill(6)}", "name": f"T{i}",
         "underlying_index": "x", "bucket": "kr_equity"}
        for i in range(15)
    ]
    fake_llm = MagicMock()
    # 두 번 다른 응답을 줘야 batch_size=10 split 검증 가능
    responses = [
        '[' + ",".join(f'{{"idx":{i},"sub_category":"index_broad"}}' for i in range(10)) + ']',
        '[' + ",".join(f'{{"idx":{i},"sub_category":"semiconductor"}}' for i in range(5)) + ']',
    ]
    fake_llm.invoke.return_value.content = responses[0]

    def side_effect(prompt):
        m = MagicMock()
        m.content = responses[0] if "A000000" in prompt else responses[1]
        return m
    fake_llm.invoke.side_effect = side_effect

    result = classify_batch_via_llm(items, fake_llm, batch_size=10)
    assert len(result) == 15


def test_all_valid_labels_have_no_overlap_across_buckets():
    """라벨 이름은 bucket 안에서만 유효. 서로 다른 bucket에 같은 이름 X (혼란 회피)."""
    seen = {}
    for bucket, labels in VALID_SUB_CATEGORIES.items():
        for label in labels:
            if label == "thematic_other":
                continue  # 공유 OK
            assert label not in seen, (
                f"label {label} duplicated across buckets {seen[label]} and {bucket}"
            )
            seen[label] = bucket


# ---- 2026-05-26 #4 fix: FX/원자재 의미 분류 ----


def test_jpy_fx_in_valid_subcategories():
    """엔선물 별도 분류 (이전엔 gold 로 잘못 라벨링)."""
    from tradingagents.skills.portfolio.sub_category import VALID_SUB_CATEGORIES
    assert "jpy_fx" in VALID_SUB_CATEGORIES["fx_commodity"]


def test_fx_subcategory_group_classifies_inflation_hedge():
    from tradingagents.skills.portfolio.sub_category import fx_subcategory_group
    assert fx_subcategory_group("gold") == "inflation_hedge"
    assert fx_subcategory_group("oil_energy") == "inflation_hedge"
    assert fx_subcategory_group("agricultural") == "inflation_hedge"


def test_fx_subcategory_group_classifies_safe_haven():
    from tradingagents.skills.portfolio.sub_category import fx_subcategory_group
    assert fx_subcategory_group("usd_fx") == "safe_haven"
    assert fx_subcategory_group("jpy_fx") == "safe_haven"


def test_fx_subcategory_group_returns_none_for_unknown():
    from tradingagents.skills.portfolio.sub_category import fx_subcategory_group
    assert fx_subcategory_group(None) is None
    assert fx_subcategory_group("") is None
    assert fx_subcategory_group("unknown_label") is None


def test_jpy_fx_boost_present_in_systemic_tail():
    """systemic tail 시 jpy_fx 도 boost (carry unwind)."""
    from tradingagents.skills.portfolio.sub_category import BOOST_BY_TAIL
    assert "jpy_fx" in BOOST_BY_TAIL["T"]
    assert BOOST_BY_TAIL["T"]["jpy_fx"] > 1.0
