"""F1 통합 레벨(MF-8) — defensive 트리거 발동 시 daily_full 전체 경로(overlay →
daily_full.py 의 3x category/risk 수선 루프) 실행 후에도 defensive_target 과 위기 보호가
살아남아야 한다. category 수선의 risk-blind 물채움이 defensive_target 을 되돌리는 걸 방지.
"""
import logging

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


def test_reassess_tier_wires_sell_ok_and_protects_gold(tmp_path, monkeypatch):
    # 리뷰 must_fix #1: daily_full.py:172 의 reassess_target(..., sell_ok=sell_ok) 는
    # defensive_overlay 호출부와 달리 실제 daily_full 경로에서 unwired 상태로 남아도
    # 스위트가 green 이었다(뮤테이션 검증: sell_ok=sell_ok 삭제해도 기존 스위트 무변화).
    # kwarg 캡처 스파이로 배선 자체를 단언하고, GOLD1 이 다른 위험자산과 함께 비례로
    # 축소되지 않는지(=보호가 실제로 살아있는지) 실측치로도 확인한다.
    prev_target = {"EQ1": 0.20, "EQ2": 0.20, "GOLD1": 0.10,
                   "HY1": 0.20, "SAFE1": 0.15, "SAFE2": 0.15}
    _common(monkeypatch, prev_target)
    monkeypatch.setattr(df, "_eval_triggers",
                        lambda **k: ("reassess", {"fired": ["reassess"]}, True))
    import tradingagents.rebalance.reassess as ra
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": True,
                                   "tilt_proposed": {"risk_asset_delta": -0.10}})())

    captured = {}
    real_reassess = df.reassess_target

    def spy_reassess(*args, **kwargs):
        captured["sell_ok"] = kwargs.get("sell_ok")
        return real_reassess(*args, **kwargs)

    monkeypatch.setattr(df, "reassess_target", spy_reassess)

    res = df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)

    assert res.tier == "reassess"
    assert captured["sell_ok"] is not None

    # sell_ok 가 실제로 전달되지 않으면(unwired) GOLD1 도 EQ1/EQ2 와 동일 비율로 축소되어
    # 0.10 * (risk 목표/risk 총합) < 0.10 이 된다 — 배선이 살아있는지의 직접 증거.
    realized = res.realized_weights
    assert realized.get("GOLD1", 0.0) >= prev_target["GOLD1"] - 1e-3


# --- B4 리뷰 후속: 196-205 수렴 가드 자체의 커버리지 -----------------------------------
#
# 위의 recipient_ok CASH-파킹 수정(이 WP 의 category_repair.py 리크 수정)이 정확히
# 가드가 원래 방어하려던 시나리오(정책 목적지 풀 포화 → risk-blind 되돌림)를 원인에서
# 막아버린다 — 실측: 위 시나리오도, 리뷰어가 제시한 재현 시나리오(EQ1/EQ2 .30, SAFE1/
# SAFE2 .15, HY1 .10, defensive_target .30)도 이제 overlay 1회 호출만으로 risk=0.30 에
# 정확히 수렴하고, 가드(196-205)는 아예 발동하지 않는다(overlay 재호출 0회 — 확인됨).
# repair_risk_cap 자신의(WP-B 범위 밖) water-fill 버그를 defensive_target>0.70 로 끌어내는
# 경로도 검토했으나, overlay 가 risk 를 정확히 defensive_target 로 수렴시키는 구조상
# repair_risk_cap 의 water-fill 손실은 대수적으로 defensive_target 을 절대 재초과할 수
# 없음이 증명됨(손실 상한은 freed=defensive_target-0.70 자체이고, 재초과에는
# freed>0.30 이 필요 — 즉 defensive_target>1.0 이 되어야 하므로 불가능).
#
# 따라서 가드 자체의 제어 흐름(재적용 → 여전히 초과 시 경고)을 실제 코드 경로로 계속
# 검증하려면 원인을 인위적으로 주입해야 한다 — repair_category_caps 를 감싸 "향후에
# 생길 수 있는 미지의 잔여 누수"를 시뮬레이션한다(방어 자산엔 손대지 않음). 이 주입을
# 제외한 나머지(overlay·repair_risk_cap·재적용 판정·경고 로그)는 전부 실제 프로덕션
# 코드다. 뮤테이션 검증: `if False and _is_defensive_tier:` 로 가드를 끄면 target 에
# 전달되는 risk 가 0.48(realized 0.40)로 남고 경고도 없다 — 실제 가드는 0.36
# (realized 0.3566)으로 줄이지만(측정 가능한 개선), 주입된 잔여가 가드의 단일
# 재시도보다 크도록 설계했으므로 완전 수렴은 못 하고 — 그래서 잔여 경고가 반드시 떠야
# 한다(리뷰 must_fix #2).
def _uni_guard():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="R1", name="r1", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="국내주식_지수", gaps_bucket="b1_kr_equity"),
        ETFEntry(ticker="R2", name="r2", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="해외주식_지수", gaps_bucket="b2_dm_core"),
        ETFEntry(ticker="SAFE1", name="s1", aum_krw=1e12, underlying_index="x",
                 bucket="안전", category="국내채권_회사채", gaps_bucket="a2_kr_rates"),
        ETFEntry(ticker="SAFE2", name="s2", aum_krw=1e12, underlying_index="x",
                 bucket="안전", category="해외채권_회사채", gaps_bucket="a3_us_rates"),
    ])


def test_guard_reapplies_overlay_and_warns_on_residual(tmp_path, monkeypatch, caplog):
    prev_target = {"R1": 0.25, "R2": 0.15, "SAFE1": 0.30, "SAFE2": 0.30}
    _common(monkeypatch, prev_target)
    monkeypatch.setattr(df, "load_universe", lambda p: _uni_guard())
    monkeypatch.setitem(df.DEFAULT_CONFIG["rebalance"], "defensive_target", 0.30)
    monkeypatch.setattr(df, "_eval_triggers",
                        lambda **k: ("drift:defensive", {"fired": ["drift:defensive"]}, False))

    real_repair = df.repair_category_caps

    def repair_with_injected_residual(weights, cat_of, caps, recipient_ok=None):
        out = real_repair(weights, cat_of, caps, recipient_ok=recipient_ok)
        # recipient_ok is not None 은 defensive 경로 마커. 안전자산에서 위험자산으로
        # 0.06 을 되돌려 "가드가 방어해야 할 잔여 누수"를 인위적으로 재현한다.
        if recipient_ok is not None and out.get("SAFE1", 0.0) >= 0.06:
            out = dict(out)
            out["R1"] = out.get("R1", 0.0) + 0.03
            out["R2"] = out.get("R2", 0.0) + 0.03
            out["SAFE1"] -= 0.06
        return out

    monkeypatch.setattr(df, "repair_category_caps", repair_with_injected_residual)

    overlay_calls = []
    real_overlay = df.defensive_overlay
    monkeypatch.setattr(df, "defensive_overlay",
                        lambda *a, **k: overlay_calls.append(1) or real_overlay(*a, **k))

    captured_target = {}
    real_run_rebalance = df.run_rebalance

    def spy_run_rebalance(*args, **kwargs):
        captured_target["weights"] = dict(kwargs.get("target_weights", {}))
        return real_run_rebalance(*args, **kwargs)

    monkeypatch.setattr(df, "run_rebalance", spy_run_rebalance)

    with caplog.at_level(logging.WARNING):
        df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)

    is_risk = df.make_is_risk(_uni_guard())
    risk_final = sum(w for t, w in captured_target["weights"].items() if is_risk(t))

    # 가드(196-205)가 실제로 실행됨: overlay 가 tier-dispatch 1회 + 가드 재적용 1회 = 2회.
    assert len(overlay_calls) == 2
    # 인위 주입이 가드의 단일 재시도보다 커서 완전 수렴은 안 되지만, 잔여는 남는다
    # (그래서 아래 경고가 뜬다) — silent 통과가 아니었음을 함께 확인.
    assert risk_final > 0.30 + 1e-6
    assert any(
        "defensive" in r.message and "0.30" in r.message for r in caplog.records
    ), f"잔여 초과가 경고 없이 조용히 반환됨: risk={risk_final:.4f}, records={[r.message for r in caplog.records]}"
