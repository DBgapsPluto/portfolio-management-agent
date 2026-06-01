"""ETF sub_category — universe.json enrichment용 라벨 + LLM 분류 helper.

매일 호출하지 않고 universe.json refresh 시 1회만 실행 (scripts/enrich_universe_subcategory.py).
분류 결과는 universe.json의 ETFEntry.sub_category 필드에 영구 저장.

Stage 3 candidate_selector는 SCENARIO_SUBCATEGORY_BOOST를 통해 dominant_scenario
별로 sub_category 가중치를 score에 부여 (log-boost, 부호 보존).
"""
import math
import json
import logging
import re
from typing import Final, Iterable

logger = logging.getLogger(__name__)


# bucket → 허용된 sub_category 라벨 목록.
# Tier 1 (2026-05-28): 5 → 8 bucket split
VALID_SUB_CATEGORIES: dict[str, list[str]] = {
    "kr_equity": [
        "index_broad",
        "semiconductor",
        "it_software",
        "ai_robotics",
        "battery_ev",
        "biotech_pharma",
        "finance",
        "consumer",
        "industrial_defense",
        "materials_energy",
        "factor_value_dividend",
        "thematic_other",
    ],
    "global_equity": [
        "us_broad",
        "us_tech_nasdaq",
        "us_sector",
        "europe",
        "japan",
        "china",
        "india",
        "emerging_other",
        "ai_theme_global",
        "thematic_other",
    ],
    # NEW: split from fx_commodity
    "precious_metals": [
        "gold",
        "silver_precious",
    ],
    "cyclical_commodity_fx": [
        "oil_energy",
        "agricultural",
        "broad_commodity",
        "usd_fx",
        "jpy_fx",
    ],
    # NEW: split from bond
    "kr_bond": [
        "kr_treasury",
        "inflation_linked",   # KR TIPS (e.g. 물가채) — domestic inflation-linked
        "short_duration",  # NOTE: universe-level review — may be KR or global
    ],
    "credit": [
        "kr_corporate",
        "us_high_yield",
        "us_aggregate",
        "em_bond",
    ],
    "global_duration": [
        "us_treasury",
        "inflation_linked",
    ],
    "cash_mmf": [
        "mmf_kr",
        "mmf_usd",
        "short_kr_bond",
    ],
}


# Tier 1 special marker — category alone is ambiguous (needs sub_category split).
_SPLIT_MARKER: Final[str] = "_split_by_sub_category"

_CATEGORY_TO_BUCKET: dict[str, str] = {
    "국내주식_지수": "kr_equity",
    "국내주식_섹터": "kr_equity",
    "해외주식_지수": "global_equity",
    "해외주식_섹터": "global_equity",
    "FX 및 원자재": _SPLIT_MARKER,         # split: precious_metals vs cyclical_commodity_fx
    "국내채권_종합": _SPLIT_MARKER,        # split: kr_bond vs credit
    "국내채권_회사채": "credit",
    "해외채권_종합": _SPLIT_MARKER,        # split: credit vs global_duration
    "해외채권_회사채": "credit",
    "금리연계형/초단기채권": "cash_mmf",
}


# Tier 1: for _SPLIT_MARKER categories, which buckets are valid split targets.
# bucket_for_etf restricts the sub_category scan to these (prevents cross-category
# leakage, e.g. a KR inflation-linked bond → global_duration).
_SPLIT_TARGETS: dict[str, tuple[str, ...]] = {
    "FX 및 원자재":   ("precious_metals", "cyclical_commodity_fx"),
    "국내채권_종합":  ("kr_bond", "credit"),
    "해외채권_종합":  ("credit", "global_duration"),
}


def bucket_for_category(category: str) -> str | None:
    """Backward-compat: legacy single-category lookup. Returns None for ambiguous."""
    result = _CATEGORY_TO_BUCKET.get(category)
    return result if result and result != _SPLIT_MARKER else None


def bucket_for_etf(etf) -> str | None:
    """8-bucket classification using (category, sub_category).

    For categories with _SPLIT_MARKER (FX 및 원자재, 국내채권_종합, 해외채권_종합),
    split by sub_category — but ONLY among the buckets valid for that category
    (_SPLIT_TARGETS), preventing cross-category leakage.

    Returns None for unknown category or unclassified sub_category.
    """
    cat = _CATEGORY_TO_BUCKET.get(etf.category)
    if cat is None:
        return None
    if cat != _SPLIT_MARKER:
        return cat
    sub = getattr(etf, "sub_category", None)
    if not sub:
        return None
    targets = _SPLIT_TARGETS.get(etf.category, tuple(VALID_SUB_CATEGORIES.keys()))
    for bucket in targets:
        if sub in VALID_SUB_CATEGORIES.get(bucket, []):
            return bucket
    return None


# 24-cell framework — axis별 boost를 곱(multiplicative)으로 합성.
# 7-scenario dict를 24개로 확장하지 않고 (cycle/tail/kr) 좌표별 따로.
BOOST_BY_CYCLE: dict[str, dict[str, float]] = {
    "A": {  # growth + disinflation
        "index_broad": 1.2, "us_broad": 1.2, "us_tech_nasdaq": 1.2,
        "ai_theme_global": 1.3, "ai_robotics": 1.3,
    },
    "B": {  # growth + inflation
        "materials_energy": 1.5, "broad_commodity": 1.4,
        "oil_energy": 1.4, "inflation_linked": 1.4,
    },
    "C": {  # recession + disinflation
        "factor_value_dividend": 1.3, "us_treasury": 1.3,
        "us_aggregate": 1.3, "short_duration": 1.2,
        "kr_treasury": 1.3,
    },
    "D": {  # stagflation
        "gold": 1.8, "silver_precious": 1.4,
        "oil_energy": 1.5, "agricultural": 1.3,
        "broad_commodity": 1.5, "materials_energy": 1.4,
        "inflation_linked": 1.6,
    },
}

BOOST_BY_TAIL: dict[str, dict[str, float]] = {
    "N": {},  # normal — boost 없음
    "T": {  # systemic tail
        "us_treasury": 1.5, "kr_treasury": 1.3,
        "us_high_yield": 0.4, "em_bond": 0.6,
        "mmf_kr": 1.3, "mmf_usd": 1.3, "short_kr_bond": 1.2,
        "short_duration": 1.4,
        "gold": 1.3,             # tail flight to gold
        # 2026-05-26 #4 fix — 캐리 통화 unwind (USD/JPY 약세) 시 안전자산 flight.
        "usd_fx": 1.2,           # 달러 강세 (안전자산 dollar smile)
        "jpy_fx": 1.2,           # 엔 강세 (carry unwind)
    },
}

BOOST_BY_KR: dict[str, dict[str, float]] = {
    "F": {},  # follow — boost 없음
    "boom": {  # KR-specific 호황
        "semiconductor": 1.7, "ai_robotics": 1.4,
        "battery_ev": 1.3, "industrial_defense": 1.2,
        "index_broad": 1.3,
    },
    "stress": {  # KR-specific 위기
        "us_broad": 1.3, "us_treasury": 1.3,
        "kr_corporate": 0.5,
    },
}


def compose_boost(cycle: str, tail: str, kr: str) -> dict[str, float]:
    """3축 boost를 곱셈으로 합성. sub_category → composed multiplier."""
    result: dict[str, float] = {}
    for source in (
        BOOST_BY_CYCLE.get(cycle, {}),
        BOOST_BY_TAIL.get(tail, {}),
        BOOST_BY_KR.get(kr, {}),
    ):
        for sub, mult in source.items():
            result[sub] = result.get(sub, 1.0) * mult
    return result


def boost_for_cell(cycle: str | None, tail: str | None, kr: str | None) -> dict[str, float]:
    """24-cell의 한 cell coord에 대한 합성 boost. None이면 empty."""
    if cycle is None or tail is None or kr is None:
        return {}
    return compose_boost(cycle, tail, kr)


# Legacy 7-scenario name → 24-cell axis 좌표 매핑 (back-compat).
# candidate_selector 같이 dominant_scenario 문자열을 받는 caller가 있어서 유지.
# 새 코드는 boost_for_cell(cycle, tail, kr) 직접 호출 권장.
_LEGACY_SCENARIO_TO_AXES: dict[str, tuple[str, str, str]] = {
    "goldilocks":       ("A", "N", "F"),
    "ai_concentration": ("A", "N", "F"),  # 정확한 cell 매핑 없음 (breadth는 axis 아님)
    "overheating":      ("B", "N", "F"),  # Issue #7: B (growth+inflation) 신규 label
    "stagflation":      ("D", "N", "F"),
    "broad_recession":  ("C", "N", "F"),
    "global_credit":    ("C", "T", "F"),
    "kr_boom":          ("A", "N", "boom"),
    "kr_stress":        ("A", "N", "stress"),
    # 2026-05-26 #5 fix — late_cycle + sticky inflation.
    # B cycle (growth+inflation) 의 약화 버전. inflation_hedge 자산 boost
    # (stagflation 보다 약함). F5 약세 반영.
    "late_cycle":       ("B", "N", "F"),
}


def log_boost(scenario: str | None, sub_category: str | None) -> float:
    """Additive boost = ln(composed multiplier). 0이면 영향 없음.

    `scenario` 인자:
      - legacy 7-scenario name 문자열 (e.g. "stagflation") → axis tuple 매핑 후 합성
      - 또는 "{cycle}_{tail}_{kr}" 형식의 cell key (e.g. "D_N_F") → 그대로 사용
      - None → 0 반환
    """
    if not sub_category or not scenario:
        return 0.0
    coords = _scenario_to_axes(scenario)
    if coords is None:
        return 0.0
    composed = compose_boost(*coords).get(sub_category, 1.0)
    if composed <= 0:
        return -10.0
    return math.log(composed)


def _scenario_to_axes(scenario: str) -> tuple[str, str, str] | None:
    """legacy scenario name 을 (cycle, tail, kr) axis tuple 로.
    Factor model PR (2026-05-22): cell key path 제거. dominant_scenario 가 항상 legacy name string.
    """
    return _LEGACY_SCENARIO_TO_AXES.get(scenario)


def boost_for_scenario(scenario: str | None) -> dict[str, float]:
    if not scenario:
        return {}
    coords = _scenario_to_axes(scenario)
    if coords is None:
        return {}
    return compose_boost(*coords)


def is_valid_subcategory(bucket: str, label: str) -> bool:
    return label in VALID_SUB_CATEGORIES.get(bucket, [])


def _make_prompt(items: list[dict]) -> str:
    """LLM batch 분류 prompt. items: list of {ticker, name, underlying_index, bucket}."""
    options_block = "\n".join(
        f"- {bucket}: {', '.join(labels)}"
        for bucket, labels in VALID_SUB_CATEGORIES.items()
    )
    body = "\n".join(
        f"{i}. ticker={it['ticker']}, name={it['name']!r}, "
        f"underlying_index={it['underlying_index']!r}, bucket={it['bucket']}"
        for i, it in enumerate(items)
    )
    return (
        "You classify Korean-listed ETFs into a semantic sub_category.\n\n"
        "For each ETF, output exactly one label from the VALID list for that ETF's bucket.\n"
        "If the ETF doesn't fit any specific label, use 'thematic_other' (kr_equity/global_equity) "
        "or the most general option for the bucket.\n\n"
        f"VALID labels per bucket:\n{options_block}\n\n"
        "Return ONLY a JSON array like [{\"idx\": 0, \"sub_category\": \"semiconductor\"}, ...].\n"
        "No prose, no markdown fences.\n\n"
        f"ETFs to classify:\n{body}"
    )


def classify_batch_via_llm(
    items: list[dict], llm, batch_size: int = 10,
) -> dict[str, str]:
    """Return {ticker: sub_category} dict.

    items: list of dicts with keys: ticker, name, underlying_index, bucket.
    llm: LangChain LLM client.
    """
    result: dict[str, str] = {}
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        prompt = _make_prompt(batch)
        try:
            resp = llm.invoke(prompt).content
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.strip(), flags=re.M)
            data = json.loads(cleaned)
        except Exception as e:
            logger.warning("sub_category batch failed (start=%d): %s", start, e)
            continue

        for entry in data:
            if not isinstance(entry, dict):
                continue
            idx = entry.get("idx")
            label = entry.get("sub_category")
            if idx is None or label is None:
                continue
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                continue
            if not (0 <= idx < len(batch)):
                continue
            item = batch[idx]
            bucket = item["bucket"]
            if not is_valid_subcategory(bucket, label):
                # invalid label → fallback to "thematic_other" or first valid
                fallback = (
                    "thematic_other"
                    if "thematic_other" in VALID_SUB_CATEGORIES.get(bucket, [])
                    else VALID_SUB_CATEGORIES.get(bucket, [None])[0]
                )
                logger.warning(
                    "Invalid sub_category %r for bucket %s (ticker=%s) → fallback %s",
                    label, bucket, item["ticker"], fallback,
                )
                if fallback:
                    result[item["ticker"]] = fallback
                continue
            result[item["ticker"]] = label
    return result


# 2026-05-26 #4 fix — FX/원자재 bucket 의미 분류 (inflation_hedge vs safe_haven).
# 평가의 핵심 비판: "FX/원자재 17.7% 인플레 헤지" 라벨링 인데 실제로는 엔선물
# 11% (디플레 통화) 가 차지 → 라벨 사기. sub_category 의 *기능 그룹* 매핑.
FX_COMMODITY_GROUP: dict[str, str] = {
    # inflation hedge
    "gold":            "inflation_hedge",
    "silver_precious": "inflation_hedge",
    "oil_energy":      "inflation_hedge",
    "agricultural":    "inflation_hedge",
    "broad_commodity": "inflation_hedge",
    "materials_energy": "inflation_hedge",
    # safe haven (캐리 unwind / dollar smile)
    "usd_fx":          "safe_haven",
    "jpy_fx":          "safe_haven",
}


def fx_subcategory_group(sub_category: str | None) -> str | None:
    """fx_commodity bucket 내 자산의 기능 그룹 반환.

    Returns 'inflation_hedge' | 'safe_haven' | None (분류 안 됨).
    F2_inflation z + 면 inflation_hedge 선호, F5 약세 면 safe_haven 선호 신호.
    """
    if not sub_category:
        return None
    return FX_COMMODITY_GROUP.get(sub_category)
