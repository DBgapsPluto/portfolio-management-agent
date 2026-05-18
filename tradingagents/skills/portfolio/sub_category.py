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
from typing import Iterable

logger = logging.getLogger(__name__)


# bucket → 허용된 sub_category 라벨 목록.
# 너무 세분화하면 LLM 일관성 떨어짐 → 각 bucket 3-9개.
VALID_SUB_CATEGORIES: dict[str, list[str]] = {
    "kr_equity": [
        "index_broad",         # KOSPI200, KOSPI 등 광역
        "semiconductor",       # 반도체
        "it_software",         # IT/소프트웨어 (AI 제외)
        "ai_robotics",         # AI/로봇 테마
        "battery_ev",          # 2차전지/전기차
        "biotech_pharma",      # 바이오/제약
        "finance",             # 금융/증권/보험
        "consumer",            # 소비재/유통
        "industrial_defense",  # 산업재/방산
        "materials_energy",    # 소재/에너지
        "factor_value_dividend",  # 가치/배당
        "thematic_other",
    ],
    "global_equity": [
        "us_broad",            # S&P500/Russell 등 광역
        "us_tech_nasdaq",      # 나스닥/IT/반도체
        "us_sector",           # 미국 섹터 (헬스/금융/에너지)
        "europe",              # 유럽 (STOXX/DAX 등)
        "japan",               # 일본
        "china",               # 중국/홍콩
        "india",               # 인도
        "emerging_other",      # 베트남/이머징
        "ai_theme_global",     # 글로벌 AI/반도체 테마
        "thematic_other",
    ],
    "fx_commodity": [
        "gold",
        "silver_precious",
        "oil_energy",
        "agricultural",
        "broad_commodity",
        "usd_fx",
    ],
    "bond": [
        "kr_treasury",         # 한국 국고채
        "kr_corporate",        # 한국 회사채
        "us_treasury",         # 미국 국채
        "us_aggregate",        # 미국 종합/IG
        "us_high_yield",       # 미국 HY
        "em_bond",             # 이머징 채권
        "inflation_linked",    # 물가연동
        "short_duration",      # 단기
    ],
    "cash_mmf": [
        "mmf_kr",
        "mmf_usd",
        "short_kr_bond",       # 초단기 KR 채권
    ],
}


# bucket → category 매핑 (sub_category 검증용; candidate_selector와 정합)
_CATEGORY_TO_BUCKET: dict[str, str] = {
    "국내주식_지수": "kr_equity",
    "국내주식_섹터": "kr_equity",
    "해외주식_지수": "global_equity",
    "해외주식_섹터": "global_equity",
    "FX 및 원자재": "fx_commodity",
    "국내채권_종합": "bond",
    "국내채권_회사채": "bond",
    "해외채권_종합": "bond",
    "해외채권_회사채": "bond",
    "금리연계형/초단기채권": "cash_mmf",
}


def bucket_for_category(category: str) -> str | None:
    return _CATEGORY_TO_BUCKET.get(category)


# Stage 2 dominant_scenario → sub_category boost 배율.
# 값 > 1.0 = 가중치 ↑, < 1.0 = 페널티, 미명시 = 1.0 (영향 없음).
# 안전 위해 [0.3, 2.0] 범위로 제한 — 극단 boost는 다른 factor를 너무 가림.
SCENARIO_SUBCATEGORY_BOOST: dict[str, dict[str, float]] = {
    "goldilocks": {
        # 광범위 risk-on, 별 boost 없음 (균형)
        "index_broad": 1.2, "us_broad": 1.2,
    },
    "ai_concentration": {
        # AI mega-cap rally — narrow leadership
        "ai_robotics": 2.0, "semiconductor": 1.8, "it_software": 1.4,
        "us_tech_nasdaq": 2.0, "ai_theme_global": 2.0,
    },
    "stagflation": {
        # 인플레 hedge
        "gold": 2.0, "silver_precious": 1.5,
        "oil_energy": 1.8, "agricultural": 1.4,
        "broad_commodity": 1.6,
        "materials_energy": 1.5,
        "inflation_linked": 1.8,
    },
    "broad_recession": {
        # 안전자산 + defensive equity
        "kr_treasury": 1.5, "us_treasury": 1.5,
        "us_aggregate": 1.3,
        "factor_value_dividend": 1.3,
        "short_duration": 1.2,
    },
    "global_credit": {
        # 극단 defensive — HY 회피
        "us_treasury": 2.0, "kr_treasury": 1.8,
        "short_duration": 1.5,
        "mmf_kr": 1.5, "mmf_usd": 1.5,
        "us_high_yield": 0.3, "em_bond": 0.5,
    },
    "kr_boom": {
        # KR-specific 호황 — 수출/반도체/AI
        "semiconductor": 1.8, "ai_robotics": 1.5,
        "battery_ev": 1.3, "industrial_defense": 1.3,
        "index_broad": 1.4,
    },
    "kr_stress": {
        # KR 회피 + 안전자산
        "us_broad": 1.3, "us_treasury": 1.5,
        "kr_corporate": 0.5,  # KR 신용 위험 회피
    },
}


def boost_for_scenario(scenario: str | None) -> dict[str, float]:
    """Return sub_category → boost dict. Unknown scenario → empty dict (= 영향 없음)."""
    if scenario is None:
        return {}
    return SCENARIO_SUBCATEGORY_BOOST.get(scenario, {})


def log_boost(scenario: str | None, sub_category: str | None) -> float:
    """Additive boost = ln(multiplier). 0이면 영향 없음.

    - boost=1.0 → 0
    - boost=2.0 → +ln(2) ≈ +0.69
    - boost=0.3 → ln(0.3) ≈ -1.20

    score_candidates 결과 (음수 가능)에 *가산*하여 부호 안전.
    """
    if not scenario or not sub_category:
        return 0.0
    boost = SCENARIO_SUBCATEGORY_BOOST.get(scenario, {}).get(sub_category, 1.0)
    if boost <= 0:
        return -10.0  # effective elimination
    return math.log(boost)


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
