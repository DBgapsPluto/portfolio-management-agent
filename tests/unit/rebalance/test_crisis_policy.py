"""F1 — 위기 전용 정책(crisis_policy): 매도/목적지 적격성을 GAPS 14-bucket 기준으로
공식 8-bucket mandate 분류(is_risk)와 절연해 독립 판정한다 (스펙 §WP-B G4).
"""
from pathlib import Path

from tradingagents.dataflows.universe import Universe, ETFEntry, load_universe
from tradingagents.rebalance.crisis_policy import make_sell_ok, make_dest_ok


def _e(ticker, gaps_bucket, category, sub_category=None, name="x"):
    return ETFEntry(ticker=ticker, name=name, aum_krw=1e11, underlying_index="x",
                    bucket="위험", category=category, sub_category=sub_category,
                    gaps_bucket=gaps_bucket)


def _uni(entries):
    return Universe(version="t", etfs=entries)


def test_sell_ok_protects_flight_to_quality_gaps_buckets():
    # 실측(data/universe.json): a5_gold_infl(금)·a4_safe_fx(안전통화 선물)는 8-bucket 상
    # precious_metals/cyclical_commodity_fx = risk 로 분류되지만, 위기 시 도피처 자산을
    # 위험자산과 비례로 팔아치우는 건 방향이 틀렸다(F1) — sell 보호.
    uni = _uni([
        _e("GOLD1", "a5_gold_infl", "FX 및 원자재", sub_category="gold"),
        _e("FX1", "a4_safe_fx", "FX 및 원자재", sub_category="usd_fx"),
        _e("EQ1", "b1_kr_equity", "국내주식_지수"),
    ])
    sell_ok = make_sell_ok(uni)
    assert sell_ok("GOLD1") is False
    assert sell_ok("FX1") is False
    assert sell_ok("EQ1") is True


def test_dest_ok_excludes_high_yield_credit():
    # b9_risk_credit(하이일드)는 8-bucket 상 credit(=safe, is_risk=False)로 분류되어 물채움
    # 대상이 되지만 실제로는 위기 시 스프레드가 벌어지는 위험 자산이다(F1) — dest 제외.
    uni = _uni([
        _e("HY1", "b9_risk_credit", "해외채권_회사채"),
        _e("KTB1", "a2_kr_rates", "국내채권_종합"),
    ])
    dest_ok = make_dest_ok(uni)
    assert dest_ok("HY1") is False
    assert dest_ok("KTB1") is True
    assert dest_ok("CASH") is True   # 현금은 항상 최후 목적지


def test_unclassified_gaps_bucket_is_fail_open():
    # 미분류(gaps_bucket=None)는 fail-open — 매도 가능·목적지 가능(감사 N3: 모르면
    # 보호/제외하지 않는다).
    uni = _uni([_e("UNK1", None, "국내주식_지수")])
    assert make_sell_ok(uni)("UNK1") is True
    assert make_dest_ok(uni)("UNK1") is True


def test_unknown_ticker_not_in_universe_is_fail_open():
    uni = _uni([_e("EQ1", "b1_kr_equity", "국내주식_지수")])
    assert make_sell_ok(uni)("GHOST") is True
    assert make_dest_ok(uni)("GHOST") is True


def test_policy_wiring_real_universe():
    # 스텁-그린/라이브-데드 방지 (감사 A-1 패턴 준용): 실제 data/universe.json 배선 단언.
    uni = load_universe(Path("data/universe.json"))
    sell_ok = make_sell_ok(uni)
    dest_ok = make_dest_ok(uni)
    gold = next(e for e in uni.etfs if e.gaps_bucket == "a5_gold_infl"
               and e.sub_category in ("gold", "silver_precious"))
    hy = next(e for e in uni.etfs if e.gaps_bucket == "b9_risk_credit")
    assert sell_ok(gold.ticker) is False
    assert dest_ok(hy.ticker) is False
