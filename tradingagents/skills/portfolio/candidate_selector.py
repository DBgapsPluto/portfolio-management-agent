"""Stage 3 trader Step B — 결정론적 대표 운반체(carrier) 선정.

버킷 비중(Step A)은 이미 결정됨. 여기서는 그 노출을 실현할 ETF 를 고른다:
core(broad) sub_category 우선 → AUM → underlying_index dedup → N = min(n_floor, core distinct).
regime-alpha/모멘텀/펀더멘털 미사용(적대 리뷰: 미검증 sub-theme 베팅 배제).
"""
from __future__ import annotations

import math
import re

from tradingagents.skills.portfolio.within_bucket import SINGLE_CAP

# === 레짐 조건부 risk-filter (Step B, spec 2026-06-04) ===
# 듀레이션 필터 적용 버킷(채권), 헤지 필터 적용 버킷(안전 외화자산).
_DURATION_BUCKETS: set[str] = {"a2_kr_rates", "a3_us_rates"}
_HEDGE_BUCKETS: set[str] = {"a3_us_rates", "a5_gold_infl"}
_INFLATION_QUADRANTS: set[str] = {"growth_inflation", "recession_inflation"}


def duration_tier(name: str) -> int:
    """ETF명에서 듀레이션 tier. 0=초단기 … 3=장기 (클수록 인플레 레짐 페널티 큼)."""
    m = re.search(r"(\d+)\s*년", name)
    if m:
        y = int(m.group(1))
        return 3 if y >= 20 else 2 if y >= 7 else 1   # ≥20y 장기 / 7~19y 중기 / 1~6y 단기
    if any(k in name for k in ("CD", "KOFR", "머니마켓", "MMF", "SOFR", "초단기", "통안")):
        return 0
    if "중장기" in name or "중기" in name or "종합" in name:   # 장기 토큰보다 먼저
        return 2
    if any(k in name for k in ("장기", "스트립", "초장기")):
        return 3
    if "단기" in name:
        return 1
    return 2   # 기본 중기


def is_hedged(name: str) -> bool:
    """환헤지 여부. KR 관례: (H)/(합성 H) → 헤지, 무표기·(합성)·(UH) → UH."""
    n = name.strip()
    if n.endswith("(UH)"):       # 환노출 명시 — "H)"로 끝나 오탐되지 않게 먼저 배제
        return False
    return n.endswith("H)")      # (H) / (합성 H) / 엔화노출(H) → 헤지


def regime_selection_prefs(
    quadrant: str | None, fx_regime: str | None,
) -> tuple[bool, bool, bool]:
    """(prefer_short_duration, prefer_unhedged, prefer_hedged). fx.regime 기반."""
    prefer_short = quadrant in _INFLATION_QUADRANTS
    prefer_unhedged = fx_regime in ("krw_weak", "usd_risk_off")
    prefer_hedged = fx_regime == "krw_strong"
    return prefer_short, prefer_unhedged, prefer_hedged


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


def select_representative_candidates(
    *,
    bucket_key: str,
    eligible: list[str],
    aum: dict[str, float],
    sub_category: dict[str, str | None],
    underlying_index: dict[str, str],
    bucket_weight: float,
    capital_krw: float,
    name: dict[str, str] | None = None,
    quadrant: str | None = None,
    dominant_scenario: str | None = None,
    fx_regime: str | None = None,
    trace: dict | None = None,
) -> list[str]:
    """버킷 내 대표 운반체 선정 (결정론).

    core 우선 → 레짐 조건부 정렬(듀레이션·헤지 페널티 → AUM) → index dedup →
    **N = min(n_floor, core distinct)**. 같은-버킷 broad ETF 는 상관성이 높아 adaptive
    다양화 이득이 작으므로 minimal-N 을 의도적 설계로 채택.

    레짐 인자(name/quadrant/fx_regime)는 전부 기본값 → 미전달 시 기존 AUM 정렬과
    동일(no-op). 듀레이션은 _DURATION_BUCKETS·인플레 quadrant 에서, 헤지는 _HEDGE_BUCKETS·
    fx.regime(환노출/헤지 선호)에서만 페널티가 켜진다. 순수 재정렬이라 풀을 비우지 않음.

    capital_krw 는 §6(hysteresis/adaptive-N) 예약 — v1 미사용.
    """
    if not eligible:
        return []
    name = name or {}
    prefer_short, prefer_unhedged, prefer_hedged = regime_selection_prefs(quadrant, fx_regime)

    def _dur_pen(t: str) -> int:
        if bucket_key not in _DURATION_BUCKETS or not prefer_short:
            return 0
        return duration_tier(name.get(t, ""))

    def _hedge_pen(t: str) -> int:
        if bucket_key not in _HEDGE_BUCKETS:
            return 0
        h = is_hedged(name.get(t, ""))
        if prefer_unhedged and h:      # 환노출 선호인데 헤지 → 페널티
            return 1
        if prefer_hedged and not h:    # 헤지 선호인데 환노출 → 페널티
            return 1
        return 0

    def _rank(ts: list[str]) -> list[str]:
        # 레짐 조건부: (듀레이션 페널티, 헤지 페널티, -AUM, ticker). 페널티 미적용 시 AUM 정렬과 동일.
        return sorted(ts, key=lambda t: (_dur_pen(t), _hedge_pen(t), -aum.get(t, 0.0), t))

    def _dedup(ts: list[str], seen_keys: set[str]) -> list[str]:
        out: list[str] = []
        for t in ts:
            key = _normalize_index(underlying_index.get(t)) or t
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(t)
        return out

    core_set = CORE_SUBCATEGORIES.get(bucket_key, set())
    core = [t for t in eligible if sub_category.get(t) in core_set]
    if not core:
        core = list(eligible)

    seen: set[str] = set()
    deduped_core = _dedup(_rank(core), seen)

    n_floor = max(1, math.ceil(bucket_weight / SINGLE_CAP - 1e-9))
    n = min(n_floor, len(deduped_core))
    selected = deduped_core[:n]

    # forced fill — feasibility 한정. thematic 을 sub_category 별 round-robin(AUM 순, 레짐 무관).
    if len(selected) < n_floor:
        core_members = set(core)
        thematic = sorted(
            [t for t in eligible if t not in core_members],
            key=lambda t: (-aum.get(t, 0.0), t),
        )
        groups: dict[str | None, list[str]] = {}
        for t in thematic:
            groups.setdefault(sub_category.get(t), []).append(t)
        order = list(groups)
        while len(selected) < n_floor:
            advanced = False
            for sc in order:
                if len(selected) >= n_floor:
                    break
                q = groups[sc]
                while q:
                    t = q.pop(0)
                    key = _normalize_index(underlying_index.get(t)) or t
                    if key not in seen:
                        seen.add(key)
                        selected.append(t)
                        advanced = True
                        break  # sub_category 당 한 번만 — pass 마다 round-robin(다양성)
            if not advanced:
                break

    if trace is not None:
        trace.update({"bucket": bucket_key, "core_n": len(deduped_core),
                      "n_floor": n_floor, "selected": list(selected)})
    return selected
