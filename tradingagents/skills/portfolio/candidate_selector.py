"""Stage 3 trader Step B — 결정론적 대표 운반체(carrier) 선정.

버킷 비중(Step A)은 이미 결정됨. 여기서는 그 노출을 실현할 ETF 를 고른다:
core(broad) sub_category 우선 → AUM → underlying_index dedup → adaptive N.
regime-alpha/모멘텀/펀더멘털 미사용(적대 리뷰: 미검증 sub-theme 베팅 배제).
"""
from __future__ import annotations

import re

# 각 버킷의 '대표(broad) 노출' sub_category (v1 시드, 튜닝 대상).
CORE_SUBCATEGORIES: dict[str, set[str]] = {
    "a1_cash":               {"mmf_kr"},
    "a2_kr_rates":           {"kr_treasury", "kr_corporate"},
    "a3_us_rates":           {"us_treasury"},
    "a4_safe_fx":            {"usd_fx", "jpy_fx"},
    "a5_gold_infl":          {"gold", "inflation_linked"},
    "b1_kr_equity":          {"index_broad"},
    "b2_dm_core":            {"us_broad", "us_tech_nasdaq"},
    "b3_global_tech":        {"us_tech_nasdaq", "ai_theme_global"},
    "b4_china":              {"china"},
    "b5_other_intl":         {"japan", "india", "europe", "emerging_other"},
    "b6_defensive_equity":   {"factor_value_dividend"},
    "b7_reits":              {"thematic_other"},
    "b8_cyclical_commodity": {"oil_energy", "agricultural", "materials_energy"},
    "b9_risk_credit":        {"us_high_yield"},
}

# core 가 아닌(thematic) sub_category — coverage 불변식용.
# universe sync 로 신규 sub_category 가 생기면 coverage 테스트가 실패 → 여기/CORE 에 추가.
KNOWN_THEMATIC: dict[str, set[str]] = {
    "a1_cash":               {"us_treasury", "kr_corporate", "kr_treasury"},
    "a2_kr_rates":           set(),
    "a3_us_rates":           {"us_high_yield", "kr_treasury"},
    "a4_safe_fx":            {"us_treasury"},
    "a5_gold_infl":          {"silver_precious"},
    "b1_kr_equity":          {"thematic_other", "industrial_defense", "consumer",
                              "finance", "materials_energy"},
    "b2_dm_core":            {"thematic_other", "us_sector"},
    "b3_global_tech":        {"semiconductor", "ai_robotics", "battery_ev",
                              "it_software", "thematic_other", "materials_energy"},
    "b4_china":              set(),
    "b5_other_intl":         {"thematic_other"},
    "b6_defensive_equity":   {"thematic_other", "us_sector", "biotech_pharma", "consumer"},
    "b7_reits":              set(),
    "b8_cyclical_commodity": {"thematic_other"},
    "b9_risk_credit":        set(),
}

# dedup 키 정규화: 수익률 계산 변종(TR/Total Return/NTR/ER) + 'index/지수' 제거.
# sub-index 명("정보기술" 등)은 보존 → 다른 노출 분리.
_INDEX_DROP_TOKENS: set[str] = {
    "tr", "tr지수", "total", "return", "net", "ntr",
    "excess", "er", "지수", "index",
}
_SEP = re.compile(r"[\s\-/(),.]+")


def _normalize_index(s: str | None) -> str:
    if not s:
        return ""
    tokens = [t for t in _SEP.split(s.lower()) if t]
    return "".join(t for t in tokens if t not in _INDEX_DROP_TOKENS)
