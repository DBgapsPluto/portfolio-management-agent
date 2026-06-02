"""14-bucket 분류 (docs/GAPS_ETF_버킷분류_14.xlsx 기준).

방어 5 (A1~A5) + 성장 9 (B1~B9). trader 배분 어휘.
위험/안전(mandate) 정의와는 별개 — 그건 universe.json `bucket` per-ETF.
"""
from __future__ import annotations
from typing import Final

# key → (code, 한글명, 진영)
_SPEC: Final[list[tuple[str, str, str, str]]] = [
    ("a1_cash",             "A1", "현금성",                "방어"),
    ("a2_kr_rates",         "A2", "국내 금리(국채·IG)",     "방어"),
    ("a3_us_rates",         "A3", "미국 금리(국채·IG)",     "방어"),
    ("a4_safe_fx",          "A4", "안전통화",              "방어"),
    ("a5_gold_infl",        "A5", "금·인플레헤지",          "방어"),
    ("b1_kr_equity",        "B1", "한국주식(브로드·시클리컬·테마)", "성장"),
    ("b2_dm_core",          "B2", "미국·선진 코어주식",      "성장"),
    ("b3_global_tech",      "B3", "글로벌 테크·반도체·성장테마", "성장"),
    ("b4_china",            "B4", "중국주식",              "성장"),
    ("b5_other_intl",       "B5", "기타 해외주식",          "성장"),
    ("b6_defensive_equity", "B6", "방어적 주식(배당·저변동)", "성장"),
    ("b7_reits",            "B7", "리츠(부동산)",          "성장"),
    ("b8_cyclical_commodity","B8", "경기민감 원자재·에너지",  "성장"),
    ("b9_risk_credit",      "B9", "위험 크레딧(하이일드)",   "성장"),
]

GAPS_BUCKET_KEYS: Final[tuple[str, ...]] = tuple(s[0] for s in _SPEC)
BUCKET_CODE: Final[dict[str, str]] = {s[0]: s[1] for s in _SPEC}
CODE_TO_KEY: Final[dict[str, str]] = {s[1]: s[0] for s in _SPEC}
BUCKET_KR_NAME: Final[dict[str, str]] = {s[0]: s[2] for s in _SPEC}
BUCKET_CAMP: Final[dict[str, str]] = {s[0]: s[3] for s in _SPEC}
DEFENSIVE_KEYS: Final[tuple[str, ...]] = tuple(s[0] for s in _SPEC if s[3] == "방어")
GROWTH_KEYS: Final[tuple[str, ...]] = tuple(s[0] for s in _SPEC if s[3] == "성장")
