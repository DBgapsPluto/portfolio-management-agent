"""F3 회전율 측정 충실화 — 체결 기반 메트릭 + CASH phantom 배제 (C1, MF-5/MF-6).
C2: buy_krw/sell_krw/begin_value/end_value 필드 영속화 + 월누적(MTD) 집계."""
import json

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.rebalance.engine import build_rebalance_plan, validate_rebalance
from tradingagents.rebalance.types import RebalanceResult
from tradingagents.reports.rebalance_plan import (
    write_rebalance_json, compute_turnover_month_to_date,
)


def _uni():
    # 6종, 서로 다른 category — single/category cap 충돌 없이 드리프트만 관찰 가능하게.
    cats = ["국내주식_지수", "해외주식_지수", "FX 및 원자재",
            "국내채권_회사채", "해외채권_회사채", "금리연계형/초단기채권"]
    etfs = [ETFEntry(ticker=t, name=t, aum_krw=1e12, underlying_index="x",
                     bucket="안전", category=c)
            for t, c in zip("ABCDEF", cats)]
    return Universe(version="t", etfs=etfs)


def _run_monthly_engine(trades, drift_pct, floor):
    # 지난 리밸런싱 이후 거래 없음(trades=[]) — 보유수량 불변, 가격만 드리프트.
    tickers = "ABCDEF"
    prev_qty = {t: 100 for t in tickers}
    price_before = {t: 10000.0 for t in tickers}
    prev_value = sum(prev_qty[t] * price_before[t] for t in tickers)
    previous_weights = {t: prev_qty[t] * price_before[t] / prev_value for t in tickers}

    prices = dict(price_before)
    prices["A"] = price_before["A"] * (1 + drift_pct)   # A 만 드리프트
    current_value = sum(prev_qty[t] * prices[t] for t in tickers)
    current = {t: prev_qty[t] * prices[t] / current_value for t in tickers}
    target = dict(current)   # trades=[] → 이번 달 목표 = 현재(재조정 없음)
    assert trades == []

    dials = dict(no_trade_band=0.005)
    plan_out = build_rebalance_plan(current, target, prev_qty, int(current_value),
                                    prices, is_risk=lambda t: False, dials=dials)
    return validate_rebalance(
        plan_out["realized_weights"], universe=_uni(), clusters=[],
        previous_weights=previous_weights, current_value=int(current_value),
        floor_pct=floor, trade_turnover=plan_out["turnover"])


def test_monthly_floor_authority_is_engine_trade_notional():
    # 거래 0 + 가격 드리프트 12% → floor 미충족이어야 함 (드리프트 착시 제거).
    validation = _run_monthly_engine(trades=[], drift_pct=0.12, floor=0.10)
    assert any(v.rule == "turnover_floor" for v in validation.violations)


def _run_validate_rebalance(realized, previous, floor):
    etfs = [ETFEntry(ticker="A", name="A", aum_krw=1e12, underlying_index="x",
                     bucket="위험", category="국내주식_지수")]
    return validate_rebalance(realized, universe=Universe(version="t", etfs=etfs),
                              clusters=[], previous_weights=previous,
                              current_value=1_000_000, floor_pct=floor)


def test_cash_phantom_excluded_in_validate_rebalance():
    # 실제 팬텀 지점(감사 MF-6): full_wv는 CASH 포함, previous_weights는 미포함
    # → validate 경로에서 CASH 를 delta 집계에서 제외해야 함.
    # 판별적 단언(리뷰 반영): CASH 를 제외하면 A 자체 델타는 0.5→0.5 로 0 이므로
    # turnover=0.0 → floor 위반이 "발생해야" 하고, 그 설명에 MF-6 마커가 붙어야
    # 하며, 보고된 turnover 수치도 0.0000 이어야 한다(=CASH 델타가 거래로 잡히지
    # 않았다는 뜻). CASH 를 배제하지 않으면 turnover=0.5≥floor 로 위반 자체가
    # 생기지 않아 이 단언은 실패한다.
    v = _run_validate_rebalance(realized={"A": 0.5, "CASH": 0.5},
                                previous={"A": 0.5}, floor=0.10)
    hard = [x for x in v.violations
            if x.rule == "turnover_floor" and x.severity == "hard"]
    assert len(hard) == 1
    assert "CASH phantom delta excluded — MF-6" in hard[0].description
    assert "0.0000" in hard[0].description


# ---------- C2: 월누적(MTD) 추적 — 필드 영속화 (MF-7) ----------


def test_build_plan_returns_trade_notional_and_values():
    current = {"A": 0.5, "B": 0.5}
    target = {"A": 0.1, "B": 0.1, "C": 0.2, "D": 0.2, "E": 0.2, "F": 0.2}
    prices = {t: 10000.0 for t in "ABCDEF"}
    dials = dict(no_trade_band=0.005)
    res = build_rebalance_plan(current, target, prev_qty={"A": 50, "B": 50},
                               current_value=1_000_000, prices=prices,
                               is_risk=lambda t: False, dials=dials)
    assert res["buy_krw"] > 0
    assert res["sell_krw"] > 0
    assert res["begin_value"] == 1_000_000
    # MF-6: end_value(=invested+cash_residual) == begin_value 항등.
    assert res["end_value"] == res["begin_value"]


def test_json_persists_trade_notional_fields(tmp_path):
    r = RebalanceResult(as_of="2026-06-07", tier="monthly")
    r.buy_krw = 50_000
    r.sell_krw = 20_000
    r.begin_value = 1_000_000
    r.end_value = 1_000_000
    out = tmp_path / "2026-06-07(rebalancing).json"
    write_rebalance_json(r, out, previous_path="artifacts/2026-06-05")
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["buy_krw"] == 50_000
    assert d["sell_krw"] == 20_000
    assert d["begin_value"] == 1_000_000
    assert d["end_value"] == 1_000_000


def _write_plan(base, as_of, *, buy_krw, sell_krw, begin_value, legacy=False):
    day_dir = base / as_of
    day_dir.mkdir(parents=True, exist_ok=True)
    payload = {"as_of_date": as_of, "turnover": (buy_krw + sell_krw) / begin_value}
    if not legacy:
        payload.update(buy_krw=buy_krw, sell_krw=sell_krw,
                       begin_value=begin_value, end_value=begin_value)
    (day_dir / f"{as_of}(rebalancing).json").write_text(
        json.dumps(payload), encoding="utf-8")


def test_turnover_mtd_aggregates_persisted_plans(tmp_path):
    _write_plan(tmp_path, "2026-06-01", buy_krw=40_000, sell_krw=10_000, begin_value=1_000_000)
    _write_plan(tmp_path, "2026-06-15", buy_krw=20_000, sell_krw=5_000, begin_value=1_010_000)
    # 다른 달 — 집계 제외
    _write_plan(tmp_path, "2026-07-01", buy_krw=999_999, sell_krw=999_999, begin_value=2_000_000)
    result = compute_turnover_month_to_date("2026-06-20", floor_pct=0.10,
                                            artifacts_dir=str(tmp_path))
    expected = (40_000 + 10_000 + 20_000 + 5_000) / ((1_000_000 + 1_010_000) / 2)
    assert abs(result["turnover_month_to_date"] - expected) < 1e-9
    assert result["n_observed"] == 2


def test_turnover_mtd_excludes_pre_persistence_artifacts(tmp_path):
    # 필드 영속화 이전 아티팩트(buy_krw 등 없음) — 소급 집계 불가, 자연 제외.
    _write_plan(tmp_path, "2026-06-02", buy_krw=0, sell_krw=0, begin_value=1_000_000, legacy=True)
    _write_plan(tmp_path, "2026-06-03", buy_krw=5_000, sell_krw=5_000, begin_value=1_000_000)
    result = compute_turnover_month_to_date("2026-06-20", floor_pct=0.10,
                                            artifacts_dir=str(tmp_path))
    assert result["n_observed"] == 1


def test_turnover_mtd_flags_projected_shortfall(tmp_path):
    _write_plan(tmp_path, "2026-06-01", buy_krw=1_000, sell_krw=0, begin_value=1_000_000)
    result = compute_turnover_month_to_date("2026-06-20", floor_pct=0.10,
                                            artifacts_dir=str(tmp_path))
    assert result["projected_shortfall"] is True


def test_turnover_mtd_no_observations_is_shortfall(tmp_path):
    result = compute_turnover_month_to_date("2026-06-20", floor_pct=0.10,
                                            artifacts_dir=str(tmp_path))
    assert result["n_observed"] == 0
    assert result["projected_shortfall"] is True
