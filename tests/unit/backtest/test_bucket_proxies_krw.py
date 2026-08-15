import pandas as pd, numpy as np
from pathlib import Path
from tradingagents.backtest import bucket_proxies as bp

def _series(vals, start="2026-01-05"):
    return pd.Series(vals, index=pd.bdate_range(start, periods=len(vals)), dtype=float)

def test_krw_composite_exact():
    r_usd = _series([0.01, -0.02, 0.005]); r_fx = _series([0.002, 0.03, -0.001])
    out = bp._to_krw(r_usd, r_fx)
    pd.testing.assert_series_equal(out, ((1+r_usd)*(1+r_fx)-1).dropna(), check_names=False)

def test_hedged_share_from_name_convention():
    # is_hedged 필드는 universe에 없음(감사 A-1/MF-12 확인) — 이름 규약으로 유도.
    # 기존 헬퍼 candidate_selector.is_hedged(name) 재사용 (candidate_selector.py:38-43).
    class E:
        def __init__(self, b, aum, name):
            self.gaps_bucket, self.aum_krw, self.name = b, aum, name
    etfs = [E("a3_us_rates", 700, "KODEX 미국채10년(H)"),
            E("a3_us_rates", 300, "TIGER 미국채10년"),
            E("b3_global_tech", 300, "TIGER 미국나스닥100")]
    s = bp._hedged_share_by_bucket(etfs)
    assert s["a3_us_rates"] == 0.7 and s["b3_global_tech"] == 0.0

def test_hedged_share_wiring_real_universe():
    # 스텁-그린/라이브-데드 방지: 실제 data/universe.json 대상 배선 단언 (감사 A-1)
    from tradingagents.dataflows.universe import load_universe
    uni = load_universe(Path("data/universe.json"))
    s = bp._hedged_share_by_bucket(uni.etfs)
    assert s["a3_us_rates"] >= 0.5      # 실측 0.835 — local(헤지 근사) 유지 대상
    assert s["b3_global_tech"] < 0.5    # composite 대상

def test_a4_proxy_is_usdkrw_not_dxy():
    assert bp.BUCKET_PROXY["a4_safe_fx"][0] == ("fred", "usd_krw")
