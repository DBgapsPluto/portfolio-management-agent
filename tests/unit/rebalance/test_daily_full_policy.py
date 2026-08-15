"""F1 통합 레벨(MF-8) — defensive 트리거 발동 시 daily_full 전체 경로(overlay →
daily_full.py 의 3x category/risk 수선 루프) 실행 후에도 defensive_target 과 위기 보호가
살아남아야 한다. category 수선의 risk-blind 물채움이 defensive_target 을 되돌리는 걸 방지.
"""
import tradingagents.rebalance.daily_full as df
from tradingagents.dataflows.universe import Universe, ETFEntry


def _uni():
    return Universe(version="t", etfs=[
        # 위험자산(매도 가능) — 서로 다른 category 로 분산해 단일/category cap 위반 없이 시작.
        ETFEntry(ticker="EQ1", name="kr eq", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="국내주식_지수", gaps_bucket="b1_kr_equity"),
        ETFEntry(ticker="EQ2", name="us eq", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="해외주식_지수", gaps_bucket="b2_dm_core"),
        # 위기 보호 자산(sell_ok=False) — 금. FX 및 원자재 cap=0.20, 단독 점유라 무변화.
        ETFEntry(ticker="GOLD1", name="gold", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="FX 및 원자재", sub_category="gold",
                 gaps_bucket="a5_gold_infl"),
        # 물채움 목적지 제외(dest_ok=False) — 하이일드 크레딧. 8-bucket 상 credit(=safe)라
        # is_risk=False 이지만 crisis_policy 는 목적지에서 제외한다.
        ETFEntry(ticker="HY1", name="us hy", aum_krw=1e12, underlying_index="x",
                 bucket="안전", category="해외채권_회사채", gaps_bucket="b9_risk_credit"),
        # 안전 목적지 2종 — 같은(타이트한) category 를 공유해 overlay 물채움 후 category cap
        # 초과를 유발한다(해외채권_회사채는 이미 HY1 이 쓰므로 국내채권_회사채 사용, cap 0.30).
        ETFEntry(ticker="SAFE1", name="kr ig", aum_krw=1e12, underlying_index="x",
                 bucket="안전", category="국내채권_회사채", gaps_bucket="a2_kr_rates"),
        ETFEntry(ticker="SAFE2", name="kr ig 2", aum_krw=1e12, underlying_index="x",
                 bucket="안전", category="국내채권_회사채", gaps_bucket="a2_kr_rates"),
    ])


def _common(monkeypatch, prev_target):
    tickers = list(prev_target)
    monkeypatch.setattr(df, "fetch_current_prices",
                        lambda d: {t: 10000.0 for t in tickers})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni())
    prev_qty = {t: int(round(w * 1_000_000)) for t, w in prev_target.items()}
    monkeypatch.setattr(df, "_load_prev", lambda p: (prev_qty, 0, prev_target))
    monkeypatch.setattr(df, "_load_clusters", lambda *a, **k: [])


def test_defensive_target_survives_downstream_category_repair(tmp_path, monkeypatch):
    # prev_target: EQ1/EQ2 위험 0.20 씩(0.40), GOLD1 보호 0.10 → risk_sum=0.50.
    # SAFE1/SAFE2 는 overlay 물채움으로 각 0.20 까지 차올라 국내채권_회사채(cap 0.30) 를
    # 초과하도록 설계 — 현행 코드는 그 초과분을 risk-blind 로 EQ1/EQ2/GOLD1 에 되채워
    # defensive_target 을 되돌린다(MF-8 실증).
    prev_target = {"EQ1": 0.20, "EQ2": 0.20, "GOLD1": 0.10,
                   "HY1": 0.20, "SAFE1": 0.15, "SAFE2": 0.15}
    _common(monkeypatch, prev_target)
    monkeypatch.setitem(df.DEFAULT_CONFIG["rebalance"], "defensive_target", 0.30)
    monkeypatch.setattr(df, "_eval_triggers",
                        lambda **k: ("drift:defensive", {"fired": ["drift:defensive"]}, False))

    res = df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)

    is_risk = df.make_is_risk(_uni())
    realized = res.realized_weights
    risk_now = sum(w for t, w in realized.items() if is_risk(t))
    assert risk_now <= 0.30 + 1e-6, (
        f"defensive_target 0.30 이 다운스트림 category 수선에서 되돌아감: risk={risk_now:.4f}"
    )
    # 위기 보호 자산(GOLD1)이 수선 루프에서 원 비중(0.10) 아래로 축소되지 않아야 한다.
    assert realized.get("GOLD1", 0.0) >= prev_target["GOLD1"] - 1e-3
