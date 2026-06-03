import json, pathlib, collections
import pytest
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
from tradingagents.skills.portfolio.candidate_selector import (
    _normalize_index, CORE_SUBCATEGORIES, KNOWN_THEMATIC,
)


def test_normalize_collapses_tr_variants():
    assert _normalize_index("코스피 200") == _normalize_index("코스피 200 TR지수")
    assert _normalize_index("S&P 500") == _normalize_index("S&P 500 Total Return Index")
    assert _normalize_index("NASDAQ 100") == _normalize_index("NASDAQ-100 Total Return Index")


def test_normalize_preserves_subindex():
    assert _normalize_index("코스피 200") != _normalize_index("코스피 200 정보기술")


def test_normalize_handles_none_empty():
    assert _normalize_index(None) == ""
    assert _normalize_index("") == ""


def test_core_keys_match_buckets():
    assert set(CORE_SUBCATEGORIES) == set(GAPS_BUCKET_KEYS)
    assert set(KNOWN_THEMATIC) == set(GAPS_BUCKET_KEYS)


def test_coverage_every_universe_subcategory_classified():
    """universe 의 모든 (bucket, sub_category) 가 CORE∪KNOWN 에 분류돼야 함.
    미분류 신규 sub_category → 실패(사람이 분류 갱신)."""
    u = json.loads(pathlib.Path(DEFAULT_CONFIG["universe_path"]).read_text())
    observed = collections.defaultdict(set)
    for e in u["etfs"]:
        observed[e["gaps_bucket"]].add(e.get("sub_category"))
    unmapped = {}
    for bkey, subs in observed.items():
        classified = CORE_SUBCATEGORIES.get(bkey, set()) | KNOWN_THEMATIC.get(bkey, set())
        missing = {s for s in subs if s is not None} - classified
        if missing:
            unmapped[bkey] = missing
    assert not unmapped, f"미분류 sub_category(분류 갱신 필요): {unmapped}"
