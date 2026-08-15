"""위기 전용 정책 (F1) — defensive overlay/reassess/daily 수선이 쓰는 매도(sell)·목적지(dest)
적격성을 GAPS 14-bucket(gaps_bucket) 기준으로 독립 판정한다.

공식 8-bucket mandate 분류(bucket_for_etf/RISK_BUCKET_NAMES, engine.make_is_risk)는 risk/safe
분할(risk_sum 계산) 자체로 그대로 쓰이며 불변이다 — sell_ok/dest_ok 는 그 분할 *안에서* 개별
티커의 적격성만 좁힌다. GAPS 기준이라 향후 8-bucket 분류-통일 결정과 절연된다(스펙 G4).

실측(2026-08-15, data/universe.json 기준):
  - a4_safe_fx(안전통화 선물)·a5_gold_infl(금/은 실물·선물) ETF는 8-bucket 상
    cyclical_commodity_fx/precious_metals 로 분류되어 is_risk=True(매도 대상)가 되지만,
    위기 시 도피처(flight-to-quality) 자산을 위험자산과 비례로 팔아치우는 것은 방향이
    틀렸다 → 매도 보호.
  - b9_risk_credit(하이일드 크레딧) ETF는 8-bucket 상 credit(=safe, is_risk=False)으로
    분류되어 물채움 대상이 되지만, 실제로는 위기 시 스프레드가 벌어지는 위험 자산이다
    → 물채움 목적지에서 제외.
"""
from __future__ import annotations

from collections.abc import Callable

# 위기 시 매도 보호(sell_ok=False) — 도피처 자산이면서 8-bucket 상 risk 로 분류되는 GAPS bucket.
CRISIS_PROTECTED_SELL: frozenset[str] = frozenset({"a4_safe_fx", "a5_gold_infl"})

# 위기 시 물채움 목적지 제외(dest_ok=False) — 위험자산이면서 8-bucket 상 safe 로 분류되는 GAPS bucket.
CRISIS_EXCLUDED_DEST: frozenset[str] = frozenset({"b9_risk_credit"})


def make_sell_ok(universe) -> Callable[[str], bool]:
    """ticker → 위기 매도 적격 여부.

    CASH·미분류(gaps_bucket=None)·universe 외 ticker는 fail-open(True) — 감사 N3:
    모르는 자산은 보호하지 않는다(=정상적으로 매도 가능 취급), 즉 crisis_policy 도입 이전과
    동일하게 참여한다.
    """
    meta = {e.ticker: e for e in universe.etfs}

    def sell_ok(ticker: str) -> bool:
        e = meta.get(ticker)
        if e is None:
            return True
        gb = getattr(e, "gaps_bucket", None)
        if gb is None:
            return True
        return gb not in CRISIS_PROTECTED_SELL

    return sell_ok


def make_dest_ok(universe) -> Callable[[str], bool]:
    """ticker → 위기 물채움 목적지 적격 여부.

    CASH 는 최후 보루로 항상 목적지 가능. 미분류(gaps_bucket=None)·universe 외 ticker는
    fail-open(True, 감사 N3).
    """
    meta = {e.ticker: e for e in universe.etfs}

    def dest_ok(ticker: str) -> bool:
        if ticker == "CASH":
            return True
        e = meta.get(ticker)
        if e is None:
            return True
        gb = getattr(e, "gaps_bucket", None)
        if gb is None:
            return True
        return gb not in CRISIS_EXCLUDED_DEST

    return dest_ok
