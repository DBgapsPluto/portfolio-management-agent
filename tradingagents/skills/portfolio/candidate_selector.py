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


# === heterogeneous(이종) 버킷 — sub_category 가 진짜 다른 노출(테마)인 버킷 ===
# 동질(homogeneous) 버킷은 같은-버킷 broad ETF 가 상관성이 높아 core-by-AUM 으로 충분하나,
# 이종 버킷은 sub-theme 별 노출이 갈리므로 LLM sub_category 선호 → risk-adj 모멘텀 top-K.
HETEROGENEOUS_BUCKETS: set[str] = {"b2_dm_core", "b3_global_tech", "b5_other_intl"}
SUBCAT_PREF_THRESHOLD: float = 0.3


def _dedup_by_index(
    ts: list[str], underlying_index: dict[str, str], seen_keys: set[str],
) -> list[str]:
    """underlying_index 정규화 키로 dedup. select_representative_candidates 내부
    _dedup 클로저와 동일한 의미(중복 노출 제거)를 모듈 레벨에서 재현."""
    out: list[str] = []
    for t in ts:
        key = _normalize_index(underlying_index.get(t)) or t
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(t)
    return out


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
    fx_regime: str | None = None,
    sub_category_views: dict[str, float] | None = None,   # this bucket: sub_cat -> pref
    momentum: dict[str, float] | None = None,
    min_etf_aum_krw: float | None = None,
    top_k: int | None = None,
    trace: dict | None = None,
) -> list[str]:
    """버킷 내 대표 운반체 선정 (결정론).

    이종(heterogeneous) 버킷(b2/b3/b5)이고 momentum 이 주어지면 → sub_category 선호
    필터 후 risk-adj 모멘텀 top-K. 그 외(동질 버킷)는 기존 core-by-AUM 경로:
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
    if bucket_key in HETEROGENEOUS_BUCKETS and momentum is not None:
        return _select_heterogeneous(
            bucket_key=bucket_key, eligible=eligible, aum=aum,
            sub_category=sub_category, underlying_index=underlying_index,
            bucket_weight=bucket_weight, sub_category_views=sub_category_views or {},
            momentum=momentum, min_etf_aum_krw=min_etf_aum_krw or 0.0,
            top_k=top_k or 3, trace=trace,
        )
    return _select_core_by_aum(
        bucket_key=bucket_key, eligible=eligible, aum=aum, sub_category=sub_category,
        underlying_index=underlying_index, bucket_weight=bucket_weight,
        quadrant=quadrant, fx_regime=fx_regime, name=name, trace=trace,
    )


def _select_heterogeneous(
    *, bucket_key, eligible, aum, sub_category, underlying_index,
    bucket_weight, sub_category_views, momentum, min_etf_aum_krw,
    top_k, trace=None,
):
    """이종 버킷: sub_category 선호 필터 → risk-adj 모멘텀 정렬 → index dedup top-K.

    1) 강한 비선호(pref < -tau) sub_category 제외 → 2) 유동성 바닥(AUM ≥ floor),
    전멸 시 완화 → 3) 강한 선호(pref > +tau) 있으면 그 sub_category 로 좁힘 →
    풀이 비면 core-by-AUM 폴백 → 4) 모멘텀 desc(타이브레이크 -AUM, ticker) →
    5) index dedup 후 N = clamp(top_k, [n_floor, |pool|]) 만큼 선택.
    """
    tau = SUBCAT_PREF_THRESHOLD
    revert = None
    # 1. exclude (pref < -tau)
    pool = [t for t in eligible
            if sub_category_views.get(sub_category.get(t), 0.0) >= -tau]
    # 2. liquidity floor
    floored = [t for t in pool if aum.get(t, 0.0) >= min_etf_aum_krw]
    if not floored and pool:
        floored, revert = pool, "floor_relaxed"
    pool = floored
    # 3. narrow to favored (pref > +tau) if any
    favored = [t for t in pool
               if sub_category_views.get(sub_category.get(t), 0.0) > tau]
    if favored:
        pool = favored
    # empty -> core-by-AUM fallback
    if not pool:
        if trace is not None:
            trace.update({"bucket": bucket_key, "revert": "core_aum"})
        return _select_core_by_aum(
            bucket_key=bucket_key, eligible=eligible, aum=aum,
            sub_category=sub_category, underlying_index=underlying_index,
            bucket_weight=bucket_weight,
        )
    # 4. risk-adj momentum desc, tiebreak (-aum, ticker)
    ranked = sorted(
        pool, key=lambda t: (-momentum.get(t, float("-inf")), -aum.get(t, 0.0), t),
    )
    # 5. dedup by underlying index -> top clamp(top_k, [n_floor, |deduped|])
    deduped = _dedup_by_index(ranked, underlying_index, set())
    n_floor = max(1, math.ceil(bucket_weight / SINGLE_CAP - 1e-9))
    n = min(max(n_floor, min(top_k, len(deduped))), len(deduped))
    selected = deduped[:n]
    if trace is not None:
        trace.update({"bucket": bucket_key, "selected": list(selected),
                      "revert": revert, "n_floor": n_floor})
    return selected


def _select_core_by_aum(
    *,
    bucket_key: str,
    eligible: list[str],
    aum: dict[str, float],
    sub_category: dict[str, str | None],
    underlying_index: dict[str, str],
    bucket_weight: float,
    quadrant: str | None = None,
    fx_regime: str | None = None,
    name: dict[str, str] | None = None,
    trace: dict | None = None,
) -> list[str]:
    """동질 버킷 core-by-AUM 경로 (기존 동작 보존)."""
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
