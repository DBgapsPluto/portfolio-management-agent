import json, pathlib, collections
import pytest
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
from tradingagents.skills.portfolio.candidate_selector import (
    _normalize_index, CORE_SUBCATEGORIES, KNOWN_THEMATIC,
    select_representative_candidates,
    duration_tier, is_hedged, regime_selection_prefs,
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


# === Task 1: 레짐 조건부 risk-filter 순수 함수 ===

def test_duration_tier_from_year():
    assert duration_tier("ACE 미국30년국채액티브(H)") == 3
    assert duration_tier("TIGER 미국채10년선물") == 2
    assert duration_tier("KODEX 국고채3년") == 1


def test_duration_tier_from_tokens():
    assert duration_tier("KODEX CD금리액티브(합성)") == 0
    assert duration_tier("KODEX 머니마켓액티브") == 0
    assert duration_tier("KODEX 종합채권(AA-이상)액티브") == 2
    assert duration_tier("PLUS 미국장기우량회사채") == 3
    assert duration_tier("PLUS 미국단기회사채(AAA~A)") == 1
    assert duration_tier("TIGER 중장기국채") == 2
    assert duration_tier("KODEX 200") == 2   # 마커 없음 → 기본 중기


def test_is_hedged_kr_convention():
    assert is_hedged("ACE 미국30년국채액티브(H)") is True
    assert is_hedged("TIGER 미국30년국채스트립액티브(합성 H)") is True
    assert is_hedged("ACE 미국30년국채엔화노출액티브(H)") is True
    assert is_hedged("ACE 미국30년국채액티브") is False
    assert is_hedged("KODEX 미국S&P500산업재(합성)") is False
    assert is_hedged("ACE KRX금현물") is False


def test_is_hedged_uh_guard():
    # (UH) 환노출 명시 표기는 (H)로 끝나는 글자에 오탐되지 않아야 함
    assert is_hedged("ACE 미국30년국채(UH)") is False


def test_regime_selection_prefs():
    assert regime_selection_prefs("growth_inflation", "neutral") == (True, True)
    assert regime_selection_prefs("recession_inflation", "neutral") == (True, True)
    assert regime_selection_prefs("growth_disinflation", "neutral") == (False, False)
    assert regime_selection_prefs("recession_disinflation", "neutral") == (False, False)
    # 비인플레라도 stress/credit 시나리오면 UH 선호만 켜짐
    assert regime_selection_prefs("growth_disinflation", "kr_stress") == (False, True)
    assert regime_selection_prefs("growth_disinflation", "global_credit") == (False, True)
    assert regime_selection_prefs(None, None) == (False, False)


# === Task 2: selector 레짐 조건부 정렬 ===

def _call_regime(rows, bucket_key, *, quadrant, scenario="neutral", w=0.10):
    """rows: (ticker, aum, sub, idx, name). 레짐 인자 포함 호출."""
    eligible = [t for t, *_ in rows]
    aum = {t: a for t, a, _, _, _ in rows}
    sub = {t: s for t, _, s, _, _ in rows}
    idx = {t: i for t, _, _, i, _ in rows}
    name = {t: nm for t, _, _, _, nm in rows}
    return select_representative_candidates(
        bucket_key=bucket_key, eligible=eligible, aum=aum,
        sub_category=sub, underlying_index=idx, name=name,
        quadrant=quadrant, dominant_scenario=scenario,
        bucket_weight=w, capital_krw=1_000_000_000,
    )


# 실 universe 축약: a3_us_rates 30년(H, 최대 AUM) / 30년(UH) / 10년(UH)
_A3_ROWS = [
    ("A453850", 1.82e12, "us_treasury", "미국30년국채", "ACE 미국30년국채액티브(H)"),
    ("A476760", 3.171e11, "us_treasury", "미국30년국채", "ACE 미국30년국채액티브"),
    ("A305080", 2.446e11, "us_treasury", "미국채10년", "TIGER 미국채10년선물"),
]


def test_a3_inflation_picks_short_unhedged():
    # growth_inflation → 단기·UH 선호 → AUM 1등 30년(H) 대신 10년(UH)
    out = _call_regime(_A3_ROWS, "a3_us_rates", quadrant="growth_inflation", w=0.08)
    assert out == ["A305080"]


def test_a3_disinflation_keeps_aum_default():
    # growth_disinflation → 페널티 0 → AUM 1등(30년 H) 유지 (회귀 보장)
    out = _call_regime(_A3_ROWS, "a3_us_rates", quadrant="growth_disinflation", w=0.08)
    assert out == ["A453850"]


def test_a2_inflation_prefers_shorter_kr_bond():
    rows = [
        ("KB30", 900.0, "kr_treasury", "국고채30년", "KODEX 국고채30년액티브"),
        ("KB3",  100.0, "kr_treasury", "국고채3년", "KODEX 국고채3년"),
    ]
    out = _call_regime(rows, "a2_kr_rates", quadrant="growth_inflation", w=0.10)
    assert out == ["KB3"]   # 단기 선호로 AUM 9배 큰 30년을 이김


def test_a5_inflation_prefers_unhedged_gold():
    rows = [
        ("GOLDH", 500.0, "gold", "골드선물", "KODEX 골드선물(H)"),
        ("GOLDP", 300.0, "gold", "금현물", "ACE KRX금현물"),
    ]
    out = _call_regime(rows, "a5_gold_infl", quadrant="growth_inflation", w=0.10)
    assert out == ["GOLDP"]   # AUM 더 작아도 UH(금현물) 우선


def test_b8_oil_only_hedged_is_noop():
    # 유가는 (H)뿐 + b8은 필터 버킷 아님 → AUM 1등 그대로
    rows = [
        ("A261220", 1428.0, "oil_energy", "WTI", "KODEX WTI원유선물(H)"),
        ("AENERGY", 410.0, "materials_energy", "에너지", "TIGER 200 에너지화학"),
    ]
    out = _call_regime(rows, "b8_cyclical_commodity", quadrant="growth_inflation", w=0.10)
    assert out == ["A261220"]


def test_credit_scenario_prefers_unhedged_in_a3():
    # 비인플레(growth_disinflation)지만 global_credit → prefer_unhedged 만 켜짐
    # 듀레이션 페널티 0 이라 30년끼리는 UH가 H를 이김
    rows = [
        ("A453850", 1.82e12, "us_treasury", "미국30년국채", "ACE 미국30년국채액티브(H)"),
        ("A476760", 3.171e11, "us_treasury", "미국30년국채A", "ACE 미국30년국채액티브"),
    ]
    out = _call_regime(rows, "a3_us_rates", quadrant="growth_disinflation",
                       scenario="global_credit", w=0.08)
    assert out == ["A476760"]   # UH 30년
