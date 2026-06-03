import json, pathlib, collections
import pytest
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
from tradingagents.skills.portfolio.candidate_selector import (
    _normalize_index, CORE_SUBCATEGORIES, KNOWN_THEMATIC,
    select_representative_candidates,
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


def _meta(rows):
    aum = {t: a for t, a, _, _ in rows}
    sub = {t: s for t, _, s, _ in rows}
    idx = {t: i for t, _, _, i in rows}
    return [t for t, *_ in rows], aum, sub, idx


def _call(rows, bucket_key, w=0.10, capital=1_000_000_000):
    eligible, aum, sub, idx = _meta(rows)
    return select_representative_candidates(
        bucket_key=bucket_key, eligible=eligible, aum=aum,
        sub_category=sub, underlying_index=idx,
        bucket_weight=w, capital_krw=capital,
    )


def test_deterministic_same_input_same_output():
    rows = [("AB", 100.0, "index_broad", "i1"), ("AC", 200.0, "index_broad", "i2")]
    assert _call(rows, "b1_kr_equity") == _call(rows, "b1_kr_equity")


def test_core_beats_larger_thematic_no_hijack():
    rows = [
        ("ABROAD", 100.0, "index_broad", "kospi200"),
        ("ATHEME", 999.0, "industrial_defense", "defense_idx"),
    ]
    assert _call(rows, "b1_kr_equity", w=0.10) == ["ABROAD"]


def test_dedup_collapses_tr_variant():
    rows = [
        ("AKOSPI",   300.0, "index_broad", "코스피 200"),
        ("AKOSPITR", 200.0, "index_broad", "코스피 200 TR지수"),
        ("AINFO",    100.0, "index_broad", "코스피 200 정보기술"),
    ]
    out = _call(rows, "b1_kr_equity", w=0.30)
    assert "AKOSPI" in out and "AINFO" in out and "AKOSPITR" not in out


def test_aum_tie_break_by_ticker():
    rows = [("AZ", 100.0, "index_broad", "i1"), ("AA", 100.0, "index_broad", "i2")]
    assert _call(rows, "b1_kr_equity", w=0.10) == ["AA"]


def test_n_floor_satisfies_single_cap():
    rows = [(f"A{i}", 100.0 - i, "index_broad", f"i{i}") for i in range(5)]
    out = _call(rows, "b1_kr_equity", w=0.50)
    assert len(out) >= 3


def test_optional_diversification_capped_by_core():
    rows = [
        ("AB1", 200.0, "index_broad", "i1"),
        ("AB2", 150.0, "index_broad", "i2"),
        ("AT1", 999.0, "industrial_defense", "d1"),
        ("AT2", 888.0, "consumer", "d2"),
    ]
    out = _call(rows, "b1_kr_equity", w=0.10, capital=10_000_000_000)
    assert all(t in ("AB1", "AB2") for t in out)


def test_forced_fill_uses_thematic_diversity_when_core_short():
    rows = [
        ("ABROAD", 500.0, "index_broad", "i1"),
        ("AT_DEF1", 400.0, "industrial_defense", "d1"),
        ("AT_DEF2", 390.0, "industrial_defense", "d2"),
        ("AT_FIN1", 300.0, "finance", "f1"),
    ]
    out = _call(rows, "b1_kr_equity", w=0.30)  # w=0.30 → n_floor=ceil(0.30/0.20)=2
    assert "ABROAD" in out and len(out) == 2
    assert "AT_DEF1" in out


def test_empty_eligible_returns_empty():
    assert select_representative_candidates(
        bucket_key="b1_kr_equity", eligible=[], aum={}, sub_category={},
        underlying_index={}, bucket_weight=0.1, capital_krw=1e9) == []


def test_core_empty_falls_back_to_eligible():
    rows = [("AT1", 200.0, "thematic_other", "i1"), ("AT2", 100.0, "thematic_other", "i2")]
    assert _call(rows, "b1_kr_equity", w=0.10) == ["AT1"]


def test_forced_fill_skips_thematic_duping_core_index():
    # core 가 1개(IDX_A), n_floor=2 강제보충 시 같은 index 의 thematic(AT_DUP)은 dedup 으로 skip,
    # 다른 index 의 thematic(AT_OTHER)이 선택됨.
    rows = [
        ("ABROAD", 500.0, "index_broad", "IDX_A"),
        ("AT_DUP", 400.0, "industrial_defense", "IDX_A"),
        ("AT_OTHER", 300.0, "finance", "IDX_B"),
    ]
    out = _call(rows, "b1_kr_equity", w=0.30)   # n_floor=2
    assert "ABROAD" in out and "AT_OTHER" in out and "AT_DUP" not in out
